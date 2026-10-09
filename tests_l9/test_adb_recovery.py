import io
import subprocess
import threading
import time
from pathlib import Path
from types import SimpleNamespace
import pytest
from PIL import Image
from pc_core.adb_bridge import ADBBridge, ADBError, ADBWatchdog, ADBDiagnostics
from pc_core.fast_input import PanicStop
import patch_main_pc_l9 as session
import verify_adb


def done(data=b'', rc=0, error=b''):
    return subprocess.CompletedProcess([], rc, data, error)


def online():return done(b'List of devices attached\nPHONE\tdevice\n')


def bridge(tmp_path, runner, **kwargs):
    return ADBBridge('PHONE', runner=runner, log_dir=str(tmp_path/'logs'), sleep=lambda _:None, **kwargs)


def test_auto_selects_first_authorized_and_remembers_serial(tmp_path):
    b=ADBBridge(runner=lambda *a,**k:done(b'A\tunauthorized\nB\tdevice\nC\tdevice\n'),log_dir=str(tmp_path))
    assert b.serial=='B'


def test_unauthorized_does_not_restart_server_or_tap(tmp_path):
    calls=[]
    def run(cmd,**kw):calls.append(cmd);return done(b'PHONE\tunauthorized\n')
    b=bridge(tmp_path,run)
    with pytest.raises(ADBError,match='разреши отладку'):b.tap(1,2)
    assert len(calls)==1


def test_disconnected_recovers_without_repeating_input(tmp_path):
    calls=[];checks=iter([done(b''),online()])
    def run(cmd,**kw):
        calls.append(cmd)
        return next(checks) if cmd[1:]==['devices'] else done()
    bridge(tmp_path,run).tap(10,20)
    assert ['adb','-s','PHONE','reconnect'] in calls
    assert sum('tap' in c for c in calls)==1


def test_offline_uses_offline_reconnect(tmp_path):
    calls=[];checks=iter([done(b'PHONE\toffline\n'),online()])
    def run(cmd,**kw):
        calls.append(cmd)
        return next(checks) if cmd[1:]==['devices'] else done()
    bridge(tmp_path,run)._ensure_device()
    assert ['adb','reconnect','offline'] in calls


def test_failed_recovery_restarts_server_once_and_stops(tmp_path):
    calls=[]
    def run(cmd,**kw):calls.append(cmd);return done()
    b=bridge(tmp_path,run)
    with pytest.raises(ADBError,match='Восстановление'):b._ensure_device()
    assert sum(c[1:]==['devices'] for c in calls)==5
    assert sum(c[1:]==['kill-server'] for c in calls)==1
    assert sum(c[1:]==['start-server'] for c in calls)==1
    with pytest.raises(ADBError):b._ensure_device()
    assert sum(c[1:]==['kill-server'] for c in calls)==1


@pytest.mark.parametrize('exception',[FileNotFoundError('missing'),OSError('broken'),subprocess.TimeoutExpired('adb',1)])
def test_execution_errors_are_structured(tmp_path,exception):
    def run(*a,**kw):raise exception
    with pytest.raises(ADBError) as caught:bridge(tmp_path,run)._run(['devices'])
    assert caught.value.operation and caught.value.serial=='PHONE'


def test_input_error_is_uncertain_and_never_retried(tmp_path):
    calls=[]
    def run(cmd,**kw):
        calls.append(cmd)
        return online() if cmd[1:]==['devices'] else done(rc=1,error=b'device not found')
    with pytest.raises(ADBError) as caught:bridge(tmp_path,run).tap(1,2)
    assert caught.value.input_uncertain
    assert sum('tap' in c for c in calls)==1


def test_pull_mode_never_streams_and_temp_file_is_removed(tmp_path):
    out=io.BytesIO();Image.new('RGB',(2,3),'red').save(out,'PNG');png=out.getvalue()
    calls=[]
    def run(cmd,**kw):
        calls.append(cmd)
        if cmd[1:]==['devices']:return online()
        if 'pull' in cmd:Path(cmd[-1]).write_bytes(png)
        return done()
    b=bridge(tmp_path,run,capture_mode='pull')
    assert b.screenshot_png()==png
    assert not any('exec-out' in c for c in calls)
    assert not Path(next(c[-1] for c in calls if 'pull' in c)).exists()
    assert any(c[3:5]==['shell','rm'] for c in calls)


def test_command_lock_serializes_watchdog_and_main(tmp_path):
    entered=threading.Event();release=threading.Event();counts=[]
    def run(cmd,**kw):
        counts.append(cmd)
        if len(counts)==1:entered.set();assert release.wait(2)
        return online()
    b=bridge(tmp_path,run)
    first=threading.Thread(target=b.list_devices);second=threading.Thread(target=b.list_devices)
    first.start();assert entered.wait(2);second.start()
    time.sleep(.02);assert len(counts)==1
    release.set();first.join(2);second.join(2)
    assert len(counts)==2 and not first.is_alive() and not second.is_alive()


def test_watchdog_survives_error_and_resumes(tmp_path):
    state={'ok':False}
    def run(*a,**kw):
        if not state['ok']:raise OSError('unplugged')
        return online()
    b=bridge(tmp_path,run);w=ADBWatchdog(b,interval=.01)
    w.start();assert not w.is_healthy()
    state['ok']=True
    deadline=time.monotonic()+2
    while not w.is_healthy() and time.monotonic()<deadline:time.sleep(.01)
    assert w.is_healthy()
    w.stop();assert not w._thread.is_alive() and not w.is_healthy()


def test_wait_for_device_cancelled_by_panic(tmp_path):
    flag=threading.Event();flag.set()
    b=bridge(tmp_path,lambda *a,**kw:pytest.fail('No command after cancellation'))
    assert not b.wait_for_device(timeout=30,stop_event=flag)


def test_diagnostics_reads_completed_process_stdout(tmp_path):
    def run(cmd,**kw):return online() if cmd[1:]==['devices'] else done(b'Samsung\n')
    assert ADBDiagnostics(bridge(tmp_path,run)).properties()['model']=='Samsung'


class Watch:
    stopped=False
    def __init__(self,*a,**kw):self.paused=threading.Event()
    def start(self):self.paused.clear()
    def is_healthy(self):return True
    def stop(self):Watch.stopped=True


def test_dry_session_recovers_without_legacy_traceback(tmp_path,monkeypatch,capsys):
    monkeypatch.setattr(session,'ADBWatchdog',Watch)
    b=bridge(tmp_path,lambda *a,**kw:online());calls=[]
    def step():
        calls.append(1)
        if len(calls)==1:raise ADBError('lost')
        return {'state':'test','status':'wait'}
    agent=SimpleNamespace(cfg=SimpleNamespace(max_steps=1,dry_run=True,worker_period=0),step=step)
    assert session.run_with_adb_recovery(agent,b)==1
    assert len(calls)==2 and Watch.stopped
    assert 'Traceback' not in capsys.readouterr().out


def test_real_session_does_not_repeat_step(tmp_path,monkeypatch):
    monkeypatch.setattr(session,'ADBWatchdog',Watch)
    b=bridge(tmp_path,lambda *a,**kw:online());calls=[];panic=PanicStop()
    def step():calls.append(1);raise ADBError('lost after tap')
    agent=SimpleNamespace(cfg=SimpleNamespace(max_steps=1,dry_run=False,worker_period=0),step=step)
    with pytest.raises(ADBError):session.run_with_adb_recovery(agent,b,emergency=panic)
    assert calls==[1] and panic.is_stopped() and Watch.stopped


def test_panic_stays_stopped_and_prevents_steps(tmp_path):
    b=bridge(tmp_path,lambda *a,**kw:online());panic=PanicStop();panic.stop()
    agent=SimpleNamespace(cfg=SimpleNamespace(max_steps=1,dry_run=True),step=lambda:pytest.fail('Stopped'))
    assert session.run_with_adb_recovery(agent,b,emergency=panic)==0
    assert panic.is_stopped()


def test_verifier_no_input_and_twenty_valid_small_frames(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path);monkeypatch.setattr(verify_adb.shutil,'which',lambda _: 'adb')
    monkeypatch.setattr(verify_adb.time,'sleep',lambda _:None)
    class Fake:
        serial='PHONE'
        def __init__(self,**kw):assert kw['capture_mode']=='pull'
        def list_devices(self):return [('PHONE','device')]
        def _device_args(self,a):return a
        def _run(self,a):return done(b'Samsung')
        def screenshot_png(self):return b'valid tiny png'
        def _valid_png(self,data):return True
        def close(self):return None
        def tap(self,*a):pytest.fail('No input')
        def swipe(self,*a):pytest.fail('No input')
    monkeypatch.setattr(verify_adb,'ADBBridge',Fake)
    assert verify_adb.main(['--no-input','--capture-mode','pull'])==0
    assert (tmp_path/'reports/adb_verify_report.json').is_file()
