from dataclasses import replace
import hashlib
import json
from pathlib import Path
import pytest
from bootstrap.manifest import DependencyManifest, official_https, artifact_filename
from bootstrap.orchestrator import BootstrapOrchestrator
from bootstrap.permissions import BatchPermissionGate
from bootstrap.venv_manager import VenvManager

ROOT=Path(__file__).resolve().parent.parent

def test_windows_profile_closes_runtime_dependencies():
    m=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml')
    assert {'numpy','opencv-python','Pillow','requests','charset-normalizer','idna','urllib3','certifi','adb'} <= set(m.profiles['windows-base'])
    assert {'pytest','colorama','iniconfig','pluggy','packaging','pygments'} <= set(m.profiles['windows-tests'])
    assert all(m.by_id[i].downloadable for i in m.profiles['windows-base']+m.profiles['windows-tests'])

def test_evidence_matches_manifest_pins():
    m=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml')
    doc=json.loads((ROOT/'bootstrap/verification_windows.json').read_text())
    normalized={key.lower().replace('_','-'):spec for key,spec in m.by_id.items()}
    for row in doc['artifacts']:
        spec=normalized[row['id'].lower().replace('_','-')]
        assert (spec.url,spec.sha256,spec.version)==(row['url'],row['sha256'],row['version'])
    assert doc['windows_runtime_test']=='PASS'
    assert doc['windows_execution']['conclusion']=='success'

@pytest.mark.parametrize('url',['https:///empty','https://','https://evil.test@pypi.org/x'])
def test_malformed_origin_rejected(url):
    assert not official_https(url)

def test_wheel_install_uses_valid_filename_and_no_network(tmp_path,monkeypatch):
    m=DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml')
    spec=m.by_id['requests']
    assert artifact_filename(spec)=='requests-2.32.5-py3-none-any.whl'
    f=tmp_path/artifact_filename(spec);f.write_bytes(b'test wheel')
    vm=VenvManager(tmp_path)
    vm.python().parent.mkdir(parents=True);vm.python().touch()
    commands=[]
    monkeypatch.setattr('bootstrap.venv_manager.subprocess.run',lambda cmd,**kw: commands.append(cmd))
    vm.install_wheel(f,hashlib.sha256(f.read_bytes()).hexdigest())
    assert '--no-index' in commands[0] and '--no-deps' in commands[0]
    assert commands[0][-1]==str(f.resolve())

def test_wrong_platform_rejected_before_permission_or_download(monkeypatch):
    monkeypatch.setattr('bootstrap.manifest.platform.system',lambda:'Linux')
    o=BootstrapOrchestrator(ROOT,gate=BatchPermissionGate(ask=lambda _:pytest.fail('Must reject before approval'),output=lambda _:None))
    with pytest.raises(ValueError,match='требуется'):
        o.apply(['numpy'],include_venv=True)

def test_windows_runner_refuses_linux(tmp_path,monkeypatch):
    import run_windows_tests as runner
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    monkeypatch.setattr(runner.platform,'system',lambda:'Linux')
    assert runner.main([])==2
    report=json.loads((tmp_path/'reports/windows_test_report.json').read_text())
    assert report['windows_tests']=='NOT_RUN'

def test_partial_install_is_not_reported_as_success(monkeypatch):
    from bootstrap.bootstrap import main
    monkeypatch.setattr('bootstrap.bootstrap.BootstrapOrchestrator.apply',lambda *a,**kw: [])
    with pytest.raises(SystemExit) as exc:main(['--profile','windows-base'])
    assert exc.value.code==1
