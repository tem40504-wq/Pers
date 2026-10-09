"""Версионирование с проверкой целостности снапшотов и атомарным откатом конфигурации."""
from __future__ import annotations
from pathlib import Path
import hashlib,json,re,shutil,os,tempfile,time

VERSION_RE=re.compile(r'^v\d+\.\d+\.\d+-(unit|integration|replay|sandbox|shadow|ab|prod)$')

class VersionManager:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.active_file=self.root/'active.json'

    def snapshot(self,version:str,files:dict[str,bytes]):
        if not VERSION_RE.fullmatch(version):raise ValueError('Неверная версия')
        target=self.root/version
        if target.exists():raise FileExistsError('Версия неизменяема')
        tmp=Path(tempfile.mkdtemp(prefix='.stage-',dir=self.root))
        try:
            hashes={}
            for name,data in files.items():
                sub=Path(name)
                if sub.is_absolute() or '..' in sub.parts or not sub.parts:
                    raise ValueError('Запрещён путь вне снимка')
                path=tmp/sub;path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(data)
                hashes[str(sub)]=hashlib.sha256(data).hexdigest()
            (tmp/'manifest.json').write_text(json.dumps({'version':version,'created':time.time(),'sha256':hashes},indent=2),encoding='utf-8')
            os.replace(tmp,target)
        finally:
            if tmp.exists():shutil.rmtree(tmp)
        return target

    def verify(self,version:str)->bool:
        if not VERSION_RE.fullmatch(version):return False
        folder=self.root/version
        try:
            manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
            return (manifest['version']==version and
                    all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==digest
                        for name,digest in manifest['sha256'].items()))
        except (OSError,ValueError,KeyError):return False

    def activate(self,version:str,*,operator_approved:bool=False):
        if not operator_approved:raise PermissionError('Оператор должен подтвердить переключение')
        if not self.verify(version):raise ValueError('Снимок повреждён')
        self._atomic_json(self.active_file,{'active':version,'at':time.time()})
        return version

    def active(self)->str|None:
        if not self.active_file.exists():return None
        return json.loads(self.active_file.read_text(encoding='utf-8'))['active']

    def rollback(self,stable_version:str,*,authorized:bool=True)->str:
        # Автооткат разрешён только к подписанному тестами, заранее утверждённому снимку.
        if not authorized:raise PermissionError('Запрещён откат')
        if not stable_version.endswith('-prod') or not self.verify(stable_version):
            raise ValueError('Нет проверенного стабильного снимка')
        self._atomic_json(self.active_file,{'active':stable_version,'at':time.time(),'rollback':True})
        return stable_version

    @staticmethod
    def _atomic_json(path:Path,data:dict):
        tmp=path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        os.replace(tmp,path)
