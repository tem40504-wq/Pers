"""Тесты на изоляцию действий, контроль согласий, SHA и ADB."""
from __future__ import annotations
import hashlib
import io
import json
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from bootstrap.environment_detector import EnvironmentDetector
from bootstrap.manifest import DependencyManifest, official_https
from bootstrap.permissions import BatchPermissionGate, PermissionDenied
from bootstrap.pc_downloader import PCDownloader, DownloadError, sha256_file
from bootstrap.model_registry import PCModelRegistry
from bootstrap.orchestrator import BootstrapOrchestrator
from bootstrap.pc_self_test import PCSelfTest
from pc_core.adb_bridge import ADBBridge, DeviceManager, ADBError
from pc_core.fast_capture import FastCapture
from pc_core.fast_input import FastInput, PanicStop

ROOT = Path(__file__).resolve().parent.parent


def manifest():
    return DependencyManifest(ROOT/'bootstrap'/'dependencies_pc.yaml')


def test_manifest_size_and_unique_ids():
    m = manifest()
    assert len(m) >= 20
    assert len(set(m.by_id)) == len(m)


def test_manifest_missing_hash_is_not_downloadable():
    assert not manifest().by_id['yolov8n'].downloadable


@pytest.mark.parametrize('url', ['http://pypi.org/x', 'https://evil.example/x',
                                'https://pypi.org.evil.test/x', 'file:///tmp/a',
                                'https://evil.test@pypi.org/x'])
def test_untrusted_hosts(url):
    assert not official_https(url)


def test_official_host():
    assert official_https('https://files.pythonhosted.org/packages/a.whl')


def test_permission_denial_and_audit(tmp_path):
    path = tmp_path/'audit.jsonl'
    p = BatchPermissionGate(ask=lambda _: 'N', output=lambda _: None, audit_path=path)
    assert not p.approve([{'name':'x','action':'safe','reason':'r','benefit':'b','risks':'k'}])
    record = json.loads(path.read_text().strip())
    assert record['approved'] is False


def test_permission_approval_requires_literal_y():
    for answer in ('yes', 'да', '', 'n'):
        assert not BatchPermissionGate(ask=lambda _, s=answer: s, output=lambda _:None).approve([{'name':'x','action':'y','reason':'z','benefit':'b','risks':'r'}])
    assert BatchPermissionGate(ask=lambda _:' Y ', output=lambda _:None).approve([{'name':'x','action':'y','reason':'z','benefit':'b','risks':'r'}])


def test_downloader_requires_hash(tmp_path):
    with pytest.raises(DownloadError):
        PCDownloader().download('https://pypi.org/x', tmp_path/'a', '')


def test_downloader_rejects_offsite(tmp_path):
    with pytest.raises(DownloadError):
        PCDownloader().download('https://bad.net/f', tmp_path/'a', 'a'*64)


def test_sha256_file(tmp_path):
    f = tmp_path/'a.bin'
    f.write_bytes(b'abc')
    assert sha256_file(f) == hashlib.sha256(b'abc').hexdigest()


def test_zip_safe_extraction(tmp_path):
    zpath = tmp_path/'good.zip'
    with zipfile.ZipFile(zpath,'w') as z:z.writestr('sub/a.txt','hello')
    PCDownloader().extract(zpath,tmp_path/'result')
    assert (tmp_path/'result/sub/a.txt').read_text()=='hello'


def test_zip_blocks_traversal(tmp_path):
    zpath = tmp_path/'bad.zip'
    with zipfile.ZipFile(zpath,'w') as z:z.writestr('../escape.txt','x')
    with pytest.raises(DownloadError):
        PCDownloader().extract(zpath, tmp_path/'result')
    assert not (tmp_path/'escape.txt').exists()


def test_model_registry_no_fake_weights(tmp_path):
    spec = manifest().by_id['yolov8n']
    assert PCModelRegistry(tmp_path).status(spec) == 'missing'


def test_model_registry_verifies_hash(tmp_path):
    spec = manifest().by_id['yolov8n']
    p = tmp_path/spec.target
    p.parent.mkdir(parents=True)
    p.write_bytes(b'valid')
    with_hash = replace(spec, sha256=hashlib.sha256(b'valid').hexdigest())
    assert PCModelRegistry(tmp_path).status(with_hash) == 'verified'
    p.write_bytes(b'bad')
    assert PCModelRegistry(tmp_path).status(with_hash) == 'hash_mismatch'


def test_detect_is_non_mutating(tmp_path):
    detector = EnvironmentDetector(tmp_path)
    r = detector.detect()
    assert r.system in {'Windows','Linux','Darwin'}
    assert r.disk_free_gb >= 0
    assert list(tmp_path.iterdir()) == []


def test_orchestrator_apply_unknown_id_doesnt_prompt(tmp_path):
    o = BootstrapOrchestrator(ROOT, gate=BatchPermissionGate(ask=lambda _:pytest.fail('should not prompt'),output=lambda _:None))
    with pytest.raises(KeyError):o.apply(['unknown-does-not-exist'])


def test_orchestrator_missing_hash_doesnt_prompt():
    o = BootstrapOrchestrator(ROOT, gate=BatchPermissionGate(ask=lambda _:pytest.fail('should not prompt'),output=lambda _:None))
    with pytest.raises(PermissionDenied):o.apply(['yolov8n'])


def test_self_test_returns_statuses_without_phone():
    checks = PCSelfTest(ROOT, manifest()).run()
    assert checks
    assert {'PASS','FAIL','WARN','SKIP'} >= {s.status for s in checks}


def ok_process(data=b'', stderr=b'', code=0):
    return SimpleNamespace(stdout=data,stderr=stderr,returncode=code)


def test_device_manager_single():
    def runner(cmd, **kwargs):
        return ok_process(b'List of devices attached\nPHONE\tdevice\n')
    assert DeviceManager(runner=runner).selected().serial == 'PHONE'


def test_device_manager_multiple_require_serial():
    def runner(cmd, **kwargs):
        return ok_process(b'List of devices attached\nPHONE\tdevice\nP2\tdevice\n')
    with pytest.raises(ADBError):DeviceManager(runner=runner).selected()
    assert DeviceManager(runner=runner).selected('P2').serial=='P2'


def test_device_manager_unauthorized_not_selected():
    def runner(cmd, **kwargs):
        return ok_process(b'List of devices attached\nPHONE\tunauthorized\n')
    with pytest.raises(ADBError):DeviceManager(runner=runner).selected()


def test_adb_bridge_uses_fixed_arguments():
    commands=[]
    def runner(cmd, **kwargs):
        commands.append(cmd)
        return ok_process()
    ADBBridge('PHONE', runner=runner).tap(100,200)
    assert commands == [['adb','-s','PHONE','shell','input','tap','100','200']]


def test_adb_bridge_fails_invalid_png():
    with pytest.raises(ADBError):ADBBridge('PHONE', runner=lambda cmd,**kwargs:ok_process(b'nonsense')).screenshot_png()


def test_fast_capture_falls_back():
    png=b'\x89PNG\r\n\x1a\nxxx'
    bridge=ADBBridge('PHONE',runner=lambda cmd,**kwargs:ok_process(png))
    frame=FastCapture(bridge,stream_provider=lambda:None).get_frame()
    assert frame.source == 'adb_screencap'


def test_fast_input_closed_by_default():
    output=[]
    class Bridge:
        def tap(self,*args):output.append(args)
    f=FastInput(Bridge(),zones=[(0,0,100,100)])
    assert not f.tap(20,20,now=2.0)
    assert output == []


def test_fast_input_zone_and_rate_limit():
    output=[]
    class Bridge:
        def tap(self,*args):output.append(args)
    f=FastInput(Bridge(),zones=[(0,0,100,100)],offline_approved=True)
    assert f.tap(20,20,now=2.0)
    assert not f.tap(20,20,now=2.1)
    assert not f.tap(150,150,now=3)
    assert not f.tap(20,20,now=4,online=True)
    assert output == [(20,20)]


def test_panic_blocks_input():
    class Bridge:
        def tap(self,*args):pytest.fail('Panic should block')
    stop=PanicStop()
    stop.stop()
    f=FastInput(Bridge(),stop,zones=[(0,0,100,100)],offline_approved=True)
    assert not f.tap(30,30,now=2.)
    with pytest.raises(PermissionError):stop.reset()
    stop.reset(user_confirmed=True)
    assert not stop.is_stopped()


def test_no_unapproved_web_download_on_preflight(monkeypatch):
    # Запуск preflight не должен трогать downloader или создавать окружение.
    from bootstrap.bootstrap import main
    monkeypatch.setattr('bootstrap.orchestrator.PCDownloader.download',lambda *a,**k:pytest.fail('download not allowed'))
    main(['--report'])


def test_guarded_legacy_device_blocks_outside_box():
    from pc_core.legacy_device import GuardedLegacyDevice
    commands=[]
    class Bridge:
        def screenshot_png(self):
            return b'\x89PNG\r\n\x1a\n'
        def tap(self, x, y):
            commands.append(('tap', x,y))
        def swipe(self,*a):
            commands.append(('swipe',a))
    bridge=Bridge()
    guard=FastInput(bridge,zones=[(10,10,100,100)],offline_approved=True)
    device=GuardedLegacyDevice(bridge,guard)
    assert device.screenshot_png().startswith(b'\x89PNG')
    with pytest.raises(PermissionError):device.tap(200,200)
    assert commands==[]


def test_local_dashboard_auth_and_panic():
    from urllib.request import urlopen, Request
    from urllib.error import HTTPError
    from pc_core.dashboard import ControlDashboard
    stop=PanicStop()
    d=ControlDashboard(stop,port=0,token='safe-test-token')
    try:
        d.start()
        try:
            urlopen('http://127.0.0.1:'+str(d.port)+'/',timeout=2)
            assert False, 'anonymous access should fail'
        except HTTPError as exc:
            assert exc.code == 403
        d.update({'action':'wait','status':'dry_run'})
        with urlopen(d.url,timeout=2) as r:
            assert b'PANIC STOP' in r.read()
        # Панель работает только с токеном, а запрос выполняется оператором.
        with urlopen(Request('http://127.0.0.1:'+str(d.port)+'/panic?token=safe-test-token',data=b'',method='POST'),timeout=2) as r:
            assert r.status==200
        assert stop.is_stopped()
    finally:
        d.close()
