"""Отладка с ПК: запрещён `input tap`, `input swipe` и произвольный shell."""
from __future__ import annotations
import subprocess
from pathlib import Path

class ADBBridge:
    def __init__(self,adb='adb',serial=None):self.adb=adb;self.serial=serial
    def _call(self,args):
        cmd=[self.adb]+(['-s',self.serial] if self.serial else [])+args
        return subprocess.run(cmd,capture_output=True,text=True,check=True,timeout=10).stdout
    def devices(self):return self._call(['devices'])
    def logs(self,lines=100):return self._call(['logcat','-d','-t',str(min(lines,500))])
    def forward_monitor(self,port=8765):
        return self._call(['forward',f'tcp:{port}',f'tcp:{port}'])
    def pull_staging(self,remote_path:str,local_path:str):
        # Только ограниченный экспорт из staging; перед чтением учитывайте приватность.
        if not remote_path.startswith('/sdcard/Download/GameAgentStaging/'):
            raise ValueError('Получать можно только staging')
        return self._call(['pull',remote_path,local_path])
    def push_staging(self,local_path:str,remote_path:str):
        # Передача допускается только в staging, не установка и не запуск.
        if not remote_path.startswith('/sdcard/Download/GameAgentStaging/'):
            raise ValueError('Отправка разрешена только в staging')
        if not Path(local_path).is_file():raise FileNotFoundError(local_path)
        return self._call(['push',local_path,remote_path])
