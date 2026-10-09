"""Уровень 4: отсутствие скрытых установок, одноразовые Y/N, fallback."""
from __future__ import annotations
import builtins
from dataclasses import dataclass
from types import SimpleNamespace
import pytest

from game_agent.l4.security import (
    PermissionGate, PermissionRequest, PermissionDenied,
    SetupFailed, DEPENDENCIES
)
from game_agent.l4.bootstrap import preflight


@pytest.fixture
def fake_request():
    return PermissionRequest("Установить пакет", "python -m pip install example",
                             "нет библиотеки", "добавляет функцию", "затраты места")


def test_deny_non_y(fake_request):
    for answer in ("N", "", "yes", "да", "OK", "Y / N"):
        gate = PermissionGate(ask=lambda _: answer, output=lambda _: None)
        assert not gate.approve(fake_request)


def test_explicit_y_once(fake_request):
    calls = []
    gate = PermissionGate(ask=lambda p: " Y ", output=calls.append)
    assert gate.approve(fake_request)
    assert any("Техническая причина" in s for s in calls)
    assert any("Польза" in s for s in calls)
    assert any("Риски" in s for s in calls)
    assert any("Точная операция" in s for s in calls)


def test_ctrl_c_eof_deny(fake_request):
    def no_console(_):
        raise EOFError
    assert not PermissionGate(ask=no_console, output=lambda _:None).approve(fake_request)


def test_optional_dependency_denied_does_not_run(monkeypatch):
    commands = []
    gate = PermissionGate(ask=lambda _: "N", output=lambda _:None,
                          runner=lambda cmd, **kwargs: commands.append(cmd))
    monkeypatch.setattr(gate, 'available', lambda _: False)
    assert gate.ensure_dependency('easyocr', required=False) is False
    assert commands == []


def test_required_dependency_denied_stops(monkeypatch):
    commands = []
    gate = PermissionGate(ask=lambda _: "N", output=lambda _:None,
                          runner=lambda cmd, **kwargs: commands.append(cmd))
    monkeypatch.setattr(gate, 'available', lambda _: False)
    with pytest.raises(PermissionDenied):
        gate.ensure_dependency('numpy', required=True)
    assert commands == []


def test_explicit_permission_invokes_exact_allowlist_command(monkeypatch):
    called=[]
    gate=PermissionGate(ask=lambda _: 'Y',output=lambda _: None,
                        runner=lambda cmd,**kw: (called.append(cmd), SimpleNamespace(returncode=0))[1])
    states=iter([False,True])
    monkeypatch.setattr(gate,'available',lambda name:next(states))
    assert gate.ensure_dependency('serial')
    assert len(called)==1
    assert called[0][-1] == DEPENDENCIES['serial'].requirement
    assert called[0][1:4] == ['-m','pip','install']
    assert isinstance(called[0],list)


def test_no_arbitrary_dependency_name(monkeypatch):
    gate=PermissionGate(ask=lambda _: 'Y', output=lambda _:None)
    monkeypatch.setattr(gate,'available',lambda _:False)
    with pytest.raises(ValueError):
        gate.ensure_dependency("os;rm -rf /")


def test_declined_model_not_downloaded():
    calls=[]
    gate=PermissionGate(ask=lambda _: 'N',output=lambda _:None,
                        runner=lambda cmd,**kw:calls.append(cmd))
    assert not gate.ensure_ollama_model('qwen2.5vl:3b', available_models=set())
    assert calls==[]


def test_approved_model_exact_command():
    calls=[]
    gate=PermissionGate(ask=lambda _: 'Y', output=lambda _:None,
                        runner=lambda cmd,**kw:(calls.append(cmd), SimpleNamespace(returncode=0))[1])
    assert gate.ensure_ollama_model('qwen2.5vl:3b',available_models=set())
    assert calls==[['ollama','pull','qwen2.5vl:3b']]


def test_untrusted_model_never_downloaded():
    gate=PermissionGate(ask=lambda _: 'Y',output=lambda _:None)
    with pytest.raises(ValueError):
        gate.ensure_ollama_model('$(curl evil.example)',available_models=set())


def test_preflight_no_optional_installs(monkeypatch):
    calls=[]
    gate=PermissionGate(ask=lambda _: 'N',output=lambda _:None,
                        runner=lambda cmd,**kw:calls.append(cmd))
    monkeypatch.setattr(gate,'available', lambda _:True)
    cap=preflight(gate)
    assert all(not v for v in cap.values())
    assert calls==[]


def test_ocr_reader_cannot_auto_download(monkeypatch):
    import sys
    import types
    calls=[]
    fake=types.ModuleType('easyocr')
    def reader(*args,**kwargs):
        calls.append(kwargs)
        return object()
    fake.Reader=reader
    monkeypatch.setitem(sys.modules, 'easyocr', fake)
    from game_agent.perception import Perception
    Perception(enable_ocr=True)
    assert calls and calls[0]['download_enabled'] is False
