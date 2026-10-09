"""ADB-мост: последовательные команды, восстановление связи и полный PNG."""
from __future__ import annotations
import logging
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from .png_capture import PNGError, validate_png

_LOG_LOCK = threading.Lock()


def _text(value):
    return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')


def _hint(reason):
    reason = reason.lower()
    if 'unauthorized' in reason:
        return 'Разблокируй телефон и разреши отладку по USB.'
    if 'offline' in reason:
        return 'Переподключи телефон; проверь состояние ADB.'
    if 'permission denied' in reason:
        return 'Проверь доступ к каталогу и разрешения на телефоне.'
    if 'more than one' in reason:
        return 'Укажи нужный телефон через --device или --serial.'
    return 'Проверь USB-кабель, порт и отладку. Подробности: logs/adb_bridge.log.'


class ADBError(RuntimeError):
    def __init__(self, operation, serial=None, stderr='', hint='', *, input_uncertain=False):
        self.operation, self.serial = operation, serial
        self.stderr, self.hint = stderr, hint
        self.input_uncertain = input_uncertain
        super().__init__(operation)

    def __str__(self):
        lines = [f'ADB: {self.operation}', f'Устройство: {self.serial or "не выбрано"}']
        if self.stderr: lines.append('Причина: ' + self.stderr)
        if self.hint: lines.append('Что сделать: ' + self.hint)
        if self.input_uncertain:
            lines.append('Действие могло выполниться. Автоматически не повторять.')
        return '\n'.join(lines)


@dataclass(frozen=True)
class Device:
    serial: str
    state: str


class DeviceManager:
    def __init__(self, adb_path='adb', runner=subprocess.run):
        self.adb_path, self.runner = adb_path, runner

    def devices(self):
        try:
            p = self.runner([self.adb_path, 'devices'], capture_output=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ADBError('Список устройств', stderr=str(exc), hint=_hint(str(exc))) from exc
        if p.returncode:
            reason = _text(p.stderr)
            raise ADBError('Список устройств', stderr=reason, hint=_hint(reason))
        devices = []
        for line in _text(p.stdout).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in {'device', 'offline', 'unauthorized'}:
                devices.append(Device(parts[0], parts[1]))
        return devices

    def selected(self, serial=None):
        devices = self.devices()
        enabled = [d for d in devices if d.state == 'device']
        if serial:
            for d in enabled:
                if d.serial == serial: return d
            state = next((d.state for d in devices if d.serial == serial), 'device not found')
            raise ADBError('Выбор телефона', serial, state, _hint(state))
        if len(enabled) != 1:
            raise ADBError('Выбор телефона', stderr=f'Авторизованных устройств: {len(enabled)}',
                           hint='Подключи один телефон или укажи --device SERIAL.')
        return enabled[0]


class ADBBridge:
    def __init__(self, serial=None, adb_path='adb', runner=subprocess.run, *,
                 reconnect_retries=3, timeout=15, log_dir='logs', capture_mode='auto',
                 sleep=time.sleep):
        # Старый позиционный serial сохранён; новые аргументы передаются по имени.
        if serial is not None and (not serial or serial.startswith('-') or '\x00' in serial or len(serial) > 256):
            raise ValueError('Недопустимый идентификатор телефона')
        if timeout <= 0 or reconnect_retries < 0 or capture_mode not in {'auto', 'pull'}:
            raise ValueError('Некорректные параметры ADB')
        self.serial, self.adb_path, self.runner = serial, str(adb_path), runner
        self.timeout, self.reconnect_retries, self.sleep = timeout, reconnect_retries, sleep
        self.lock, self._recovery_lock, self._capture_lock = threading.Lock(), threading.Lock(), threading.Lock()
        self._prefer_pull, self._last_restart = capture_mode == 'pull', float('-inf')
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK:
            self.log = logging.getLogger('uga.adb.' + str((self.log_dir/'adb_bridge.log').resolve()))
            self.log.setLevel(logging.DEBUG)
            self.log.propagate = False
            if not self.log.handlers:
                handler = RotatingFileHandler(self.log_dir/'adb_bridge.log', maxBytes=10*1024*1024,
                                              backupCount=5, encoding='utf-8')
                handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
                self.log.addHandler(handler)
        if self.serial is None:
            devices = self.list_devices()
            ready = [s for s, state in devices if state == 'device']
            if not ready:
                reason = str(devices) if devices else 'Список устройств пуст'
                raise ADBError('Выбор телефона', stderr=reason, hint=_hint(reason))
            self.serial = ready[0]
            if len(ready) > 1: self.log.warning('Выбрано первое устройство: %s', self.serial)
        self.log.info('Мост создан: %s; способ %s', self.serial, capture_mode)

    def _run(self, args, timeout=None, check=True):
        limit = self.timeout if timeout is None else timeout
        if limit <= 0: raise ValueError('Таймаут должен быть положительным')
        started = time.monotonic()
        command = [self.adb_path, *map(str, args)]
        if not self.lock.acquire(timeout=limit):
            raise ADBError('Очередь ADB', self.serial, 'timeout', 'Дождись окончания другой команды.')
        try:
            remaining = limit - (time.monotonic() - started)
            if remaining <= 0: raise ADBError('Очередь ADB', self.serial, 'timeout')
            self.log.debug('Команда: %r', command)
            try:
                p = self.runner(command, capture_output=True, timeout=remaining, check=False, shell=False)
            except subprocess.TimeoutExpired as exc:
                raise ADBError(' '.join(map(str, args[:4])), self.serial,
                               'timeout: ' + _text(exc.stderr), _hint('timeout')) from exc
            except OSError as exc:
                raise ADBError('Запуск adb', self.serial, str(exc), 'Проверь путь к adb.exe и доступ к файлам.') from exc
            self.log.debug('Время %.3f rc=%s stdout=%d stderr=%d', time.monotonic()-started,
                           p.returncode, len(p.stdout or b''), len(p.stderr or b''))
            reason = _text(p.stderr).strip()
            if reason: self.log.debug('stderr: %s', reason)
            if check and p.returncode:
                raise ADBError(' '.join(map(str, args[:4])), self.serial,
                               reason or f'Код {p.returncode}', _hint(reason))
            return p
        except ADBError as exc:
            self.log.warning('Команда не выполнена: %s', exc)
            raise
        finally:
            self.lock.release()

    def _device_args(self, args):
        return ['-s', self.serial, *args]

    def list_devices(self, timeout=None):
        p = self._run(['devices'], timeout=timeout)
        result = []
        for line in _text(p.stdout).splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] in {'device', 'offline', 'unauthorized', 'recovery', 'sideload'}:
                result.append((parts[0], parts[1]))
        return result

    def _ensure_device(self):
        with self._recovery_lock:
            errors = []
            attempts = self.reconnect_retries + 2
            for attempt in range(attempts):
                state = None
                try:
                    state = dict(self.list_devices()).get(self.serial)
                    if state == 'device': return
                    if state == 'unauthorized':
                        raise ADBError('Авторизация', self.serial, state, _hint(state))
                    errors.append(state or 'device not found')
                except ADBError as exc:
                    if 'unauthorized' in exc.stderr.lower(): raise
                    errors.append(str(exc))
                if attempt == attempts-1: break
                self.log.warning('Восстановление %d/%d: %s', attempt+1, attempts, errors[-1])
                try:
                    if attempt == 2 and time.monotonic()-self._last_restart >= 30:
                        self._last_restart = time.monotonic()
                        self.log.warning('Перезапуск общего ADB-сервера')
                        self._run(['kill-server'], check=False)
                        self._run(['start-server'])
                        self.sleep(2)
                    else:
                        cmd = ['reconnect', 'offline'] if state == 'offline' else self._device_args(['reconnect'])
                        self._run(cmd, check=False)
                        self.sleep(min(1.5 * 2**attempt, 6))
                except ADBError as exc:
                    errors.append(str(exc))
                    self.sleep(1.5)
            reason = '\n'.join(errors)
            self.log.error('Связь не восстановлена: %s', reason)
            raise ADBError('Восстановление подключения', self.serial, reason, _hint(reason))

    def wait_for_device(self, timeout=30, stop_event=None):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if stop_event is not None and stop_event.is_set(): return False
            try:
                remaining = deadline-time.monotonic()
                if dict(self.list_devices(timeout=min(self.timeout, remaining))).get(self.serial) == 'device':
                    return True
            except ADBError as exc:
                self.log.debug('Ожидание: %s', exc)
            remaining = deadline-time.monotonic()
            if remaining > 0:
                if stop_event is not None: stop_event.wait(min(1.5, remaining))
                else: self.sleep(min(1.5, remaining))
        return False

    @staticmethod
    def _valid_png(data):
        try:
            validate_png(data)
            return True
        except (PNGError, TypeError, AttributeError):
            return False

    def _capture_pull(self):
        remote = '/data/local/tmp/uga_capture_' + uuid.uuid4().hex + '.png'
        try:
            with tempfile.TemporaryDirectory(prefix='uga_capture_', dir=self.log_dir) as folder:
                local = Path(folder)/'screen.png'
                self._ensure_device()
                self._run(self._device_args(['shell', 'screencap', '-p', remote]), timeout=20)
                self._run(self._device_args(['pull', remote, str(local)]), timeout=30)
                data = local.read_bytes()
                validate_png(data)
                self.log.info('Скриншот через pull: %d байт', len(data))
                return data
        finally:
            try: self._run(self._device_args(['shell', 'rm', remote]), timeout=5, check=False)
            except ADBError as exc: self.log.debug('Очистка временного файла: %s', exc)

    def screenshot_png(self):
        with self._capture_lock:
            errors = []
            if not self._prefer_pull:
                for attempt in range(2):
                    try:
                        self._ensure_device()
                        data = self._run(self._device_args(['exec-out', 'screencap', '-p']), timeout=20).stdout
                        validate_png(data)
                        self.log.info('Скриншот exec-out: %d байт', len(data))
                        return data
                    except (ADBError, PNGError) as exc:
                        errors.append(str(exc))
                        self.log.warning('Скриншот %d: %s', attempt+1, exc)
                        if isinstance(exc, ADBError) and 'unauthorized' in exc.stderr.lower(): raise
            try:
                data = self._capture_pull()
                self._prefer_pull = True
                return data
            except (ADBError, PNGError, OSError) as exc:
                errors.append(str(exc))
                reason = '\n\n'.join(errors)
                self.log.error('Не получен полный PNG: %s', reason)
                raise ADBError('Не получен полный PNG', self.serial, reason, _hint(reason)) from exc

    def _input(self, args):
        self._ensure_device()
        try: self._run(self._device_args(['shell', 'input', *args]))
        except ADBError as exc:
            # Команда могла выполниться до обрыва ответа: повтор запрещён.
            raise ADBError(exc.operation, self.serial, exc.stderr, exc.hint, input_uncertain=True) from exc

    def tap(self, x, y):
        if any(type(v) is not int or v < 0 for v in (x, y)): raise ValueError('Недопустимые координаты')
        self.log.info('Касание: %s %s', x, y)
        self._input(['tap', str(x), str(y)])

    def swipe(self, x1, y1, x2, y2, duration_ms=300):
        if any(type(v) is not int or v < 0 for v in (x1, y1, x2, y2)): raise ValueError('Недопустимые координаты')
        if type(duration_ms) is not int or not 100 <= duration_ms <= 2000: raise ValueError('Недопустимая продолжительность жеста')
        self.log.info('Свайп: %s %s %s %s', x1, y1, x2, y2)
        self._input(['swipe', str(x1), str(y1), str(x2), str(y2), str(duration_ms)])

    def key(self, keycode):
        code = str(keycode)
        if not re.fullmatch(r'(?:[0-9]{1,4}|KEYCODE_[A-Z0-9_]+)', code): raise ValueError('Недопустимый код клавиши')
        self._input(['keyevent', code])

    def close(self):
        self.log.info('Мост закрыт; сервер оставлен работающим')


class ADBWatchdog:
    def __init__(self, bridge, interval=3.0):
        if interval <= 0: raise ValueError('Недопустимый интервал')
        self.bridge, self.interval = bridge, interval
        self.lock = bridge.lock
        self.paused, self.stop_flag = threading.Event(), threading.Event()
        self.paused.set()
        self._thread = threading.Thread(target=self._loop, name='ADBWatchdog', daemon=True)
        self._start_lock = threading.Lock()
        self._started = False

    def start(self):
        with self._start_lock:
            if self.stop_flag.is_set(): raise RuntimeError('Watchdog уже остановлен')
            if not self._started:
                self._started = True
                self._thread.start()

    def is_healthy(self):
        return self._started and not self.stop_flag.is_set() and not self.paused.is_set()

    def _loop(self):
        while not self.stop_flag.is_set():
            try:
                if dict(self.bridge.list_devices()).get(self.bridge.serial) == 'device':
                    if self.paused.is_set(): self.bridge.log.info('ADB восстановлен')
                    self.paused.clear()
                else:
                    if not self.paused.is_set(): self.bridge.log.warning('ADB потерян: ждём')
                    self.paused.set()
            except Exception as exc:
                self.paused.set()
                self.bridge.log.warning('Watchdog: %s', exc)
            self.stop_flag.wait(self.interval)

    def stop(self):
        self.stop_flag.set()
        if self._started and threading.current_thread() is not self._thread:
            self._thread.join(timeout=2*self.bridge.timeout+2)


class ADBDiagnostics:
    def __init__(self, bridge): self.bridge = bridge

    def properties(self):
        self.bridge._ensure_device()
        model = self.bridge._run(self.bridge._device_args(['shell', 'getprop', 'ro.product.model'])).stdout
        release = self.bridge._run(self.bridge._device_args(['shell', 'getprop', 'ro.build.version.release'])).stdout
        return {'model': _text(model).strip()[:100], 'android': _text(release).strip()[:20]}
