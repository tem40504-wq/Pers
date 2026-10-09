from pathlib import Path
from types import SimpleNamespace
import pytest
import launch_agent

ROOT=Path(__file__).resolve().parent.parent


def test_launcher_stops_when_preflight_fails(monkeypatch):
    calls=[]
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs));return SimpleNamespace(returncode=2)
    monkeypatch.setattr(launch_agent.subprocess,'run',run)
    assert launch_agent.main([])==2
    assert len(calls)==1 and calls[0][0][-1]=='--preflight'


def test_launcher_runs_no_gestures_and_returns_agent_failure(monkeypatch):
    calls=[]
    def run(cmd,**kwargs):
        calls.append((cmd,kwargs));return SimpleNamespace(returncode=0 if len(calls)==1 else 1)
    monkeypatch.setattr(launch_agent.subprocess,'run',run)
    assert launch_agent.main([])==1
    assert calls[-1][0][-5:]==['--steps','20','--dashboard','--capture-mode','auto']
    assert '--execute' not in calls[-1][0]
    assert calls[-1][1]['env']['PYTHONUTF8']=='1'
    assert str(ROOT/'tools/android/platform-tools') in calls[-1][1]['env']['PATH']


def test_batch_is_ascii_and_has_windows_line_endings():
    data=(ROOT/'start_agent.bat').read_bytes()
    data.decode('ascii')
    assert b'\r\n' in data and b'\n' not in data.replace(b'\r\n',b'')


def test_check_launcher_does_not_connect_to_phone(monkeypatch):
    calls=[]
    monkeypatch.setattr(launch_agent.subprocess,'run',lambda cmd,**kwargs:calls.append(cmd) or SimpleNamespace(returncode=0))
    assert launch_agent.main(['--check-launcher'])==0
    assert len(calls)==1 and calls[0][1]=='-c'
    assert all('main_pc_l9' not in arg for arg in calls[0])
