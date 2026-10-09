"""Experience Replay по профилям игр без зависимости от PyTorch.

Не называем это EWC: обучающий callback может быть подключён отдельно.
Чужие .pth файлы автоматически НЕ загружаются (pickle-риски).
"""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Callable
import hashlib
import json
import math
import os
import random
import re
import shutil
import tempfile


@dataclass(frozen=True)
class Experience:
    state: dict
    action: str
    reward: float
    next_state: dict
    terminal: bool = False


def _atomic_json(path: Path, data: object):
    path.parent.mkdir(parents=True, exist_ok=True)
    # Не повреждаем профиль при отключении питания.
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.pending-', delete=False) as f:
        tmp = Path(f.name)
        json.dump(data, f, ensure_ascii=False, allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class ContinualLearner:
    """Хранит опыт каждой игры отдельно и подмешивает старые эпизоды при обучении.

    `train_fn` и `validate_fn` должны быть реализованы доверенным кодом владельца.
    В отсутствие обучающей функции знания остаются в replay и L5 не меняется.
    """
    def __init__(self, directory='data/l6_profiles', capacity=2000, replay_ratio=.5, seed=42):
        if not 1 <= capacity <= 100_000 or not 0 <= replay_ratio <= 1:
            raise ValueError('Неверные параметры replay')
        self.root = Path(directory)
        self.capacity = capacity
        self.ratio = replay_ratio
        self._rng = random.Random(seed)
        self.game_id = None
        self.replay = deque(maxlen=capacity)

    @staticmethod
    def _game(name):
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,48}', name):
            raise ValueError('Game ID: только латиница, цифры, _ и -')
        return name

    def select_game(self, game_id: str):
        game_id = self._game(game_id)
        if self.game_id == game_id:
            return
        if self.game_id:
            self.save()
        self.game_id = game_id
        path = self.root / game_id / 'replay.json'
        self.replay = deque(maxlen=self.capacity)
        if path.is_file():
            content = json.loads(path.read_text('utf-8'))
            if content.get('schema') != 1 or content.get('game_id') != game_id:
                raise ValueError('Несовместимый профиль')
            for row in content.get('experiences', [])[-self.capacity:]:
                self.replay.append(self._checked(Experience(**row)))

    @staticmethod
    def _checked(e: Experience) -> Experience:
        if not isinstance(e.state, dict) or not isinstance(e.next_state, dict):
            raise ValueError('Неверный формат состояния')
        if len(e.state) > 40 or len(e.next_state) > 40 or len(e.action) > 128:
            raise ValueError('Слишком большой эпизод')
        if not math.isfinite(e.reward) or abs(e.reward) > 1e4:
            raise ValueError('Некорректная награда')
        for state in (e.state, e.next_state):
            if not all(isinstance(k, str) and (v is None or
                       (type(v) in (float, int, bool) and (type(v) is bool or math.isfinite(v))))
                       for k,v in state.items()):
                raise ValueError('Ожидаются числовые параметры состояния')
        return e

    def record(self, experience: Experience):
        if self.game_id is None:
            raise RuntimeError('Сначала select_game')
        self.replay.append(self._checked(experience))

    def sample(self, fresh: list[Experience], batch_size: int = 32) -> list[Experience]:
        if batch_size <= 0:
            raise ValueError('batch_size должен быть положительным')
        fresh = [self._checked(e) for e in fresh]
        n_old = min(len(self.replay), round(batch_size*self.ratio))
        n_fresh = min(len(fresh), batch_size-n_old)
        out = self._rng.sample(list(self.replay), n_old)
        out.extend(self._rng.sample(fresh, n_fresh))
        # Если свежего опыта мало, дозаполняем старой памятью.
        self._rng.shuffle(out)
        return out

    def save(self):
        if not self.game_id:
            raise RuntimeError('Сначала select_game')
        path = self.root / self.game_id / 'replay.json'
        _atomic_json(path, {'schema':1,'game_id':self.game_id,
                            'experiences':[asdict(e) for e in self.replay]})
        return path

    def train_verified(self, fresh: list[Experience], train_fn: Callable,
                       validate_fn: Callable, baseline_score: float,
                       *, min_gain: float = 0.0):
        """Обучать ТОЛЬКО проверенный локальный trainer и принять лишь результат без регрессии.

        train_fn возвращает кандидата-модель, validate_fn проверяет независимый
        набор эпизодов. При регрессии веса не сохраняем.
        """
        batch = self.sample(fresh)
        if not batch:
            return None
        candidate = train_fn(batch)
        new_score = float(validate_fn(candidate))
        if not math.isfinite(new_score) or new_score < baseline_score+min_gain:
            return None
        return candidate

    def register_weights(self, source_file: str, *, approved: bool = False):
        """Создаёт профильный snapshot файла весов, НЕ загружая его в Python.

        Требует отдельного подтверждения; не открывать через pickle/torch.load
        без weights_only и проверки происхождения.
        """
        if not approved or self.game_id is None:
            raise PermissionError('Требуется подтверждение оператора')
        source = Path(source_file)
        if source.suffix != '.pth' or not source.is_file() or source.stat().st_size > 2_000_000_000:
            raise ValueError('Неверный файл весов')
        folder = self.root / self.game_id
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / f'{self.game_id}_weights.pth'
        digest=hashlib.sha256()
        size=0
        # Потоковая копия, чтобы не держать гигабайты весов в оперативной памяти.
        with tempfile.NamedTemporaryFile('wb', dir=folder, prefix='.weights-',delete=False) as f:
            tmp=Path(f.name)
            with source.open('rb') as inp:
                while True:
                    chunk=inp.read(1024*1024)
                    if not chunk:break
                    size+=len(chunk)
                    if size>2_000_000_000:
                        tmp.unlink(missing_ok=True)
                        raise ValueError('Превышен лимит весов')
                    digest.update(chunk);f.write(chunk)
            f.flush();os.fsync(f.fileno())
        os.replace(tmp,dest)
        _atomic_json(folder/'weights_manifest.json', {'sha256':digest.hexdigest(),
                                                         'file':dest.name, 'size':size})
        return dest
