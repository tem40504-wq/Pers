"""Строгий запрос согласия на точный список операций и журнал аудита."""
from __future__ import annotations
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Callable


class PermissionDenied(RuntimeError):
    pass


class BatchPermissionGate:
    def __init__(self, ask: Callable = input, output: Callable = print,
                 audit_path: str | Path | None = None):
        self.ask, self.output = ask, output
        self.audit_path = Path(audit_path) if audit_path else None

    def _audit(self, operations: list[dict], decision: bool):
        if self.audit_path is None:
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        event = {'ts': time.time(), 'approved': decision, 'operations': operations}
        with self.audit_path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(event, ensure_ascii=False, sort_keys=True)+'\n')

    def approve(self, operations: list[dict]) -> bool:
        if not operations:
            return False
        self.output('\n=== РАЗРЕШЕНИЕ ВЛАДЕЛЬЦА: ПК Level 9 ===')
        for i, op in enumerate(operations, 1):
            self.output(f'[{i}] {op["name"]}')
            self.output(f'  Точная операция: {op["action"]}')
            self.output(f'  Техническая причина: {op["reason"]}')
            self.output(f'  Польза: {op["benefit"]}')
            self.output(f'  Риски: {op["risks"]}')
        self.output('Разрешение относится ТОЛЬКО к перечисленным операциям. Отказ ничего не меняет.')
        try:
            response = self.ask('Подтвердить весь список? [Y/N]: ')
        except (KeyboardInterrupt, EOFError, OSError):
            response = 'N'
        approved = isinstance(response, str) and response.strip().upper() == 'Y'
        self._audit(operations, approved)
        return approved
