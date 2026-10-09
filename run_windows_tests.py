"""Windows acceptance runner. Reports actual OS and never labels Linux as Windows."""
from __future__ import annotations
import argparse
import datetime
import json
import os
import platform
import struct
import subprocess
import sys
from pathlib import Path
from bootstrap.manifest import DependencyManifest, artifact_filename
from bootstrap.pc_downloader import PCDownloader
from bootstrap.permissions import BatchPermissionGate

ROOT = Path(__file__).resolve().parent

def main(argv=None):
    # Windows redirected stdout may use cp1252; Russian permission text needs UTF-8.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    p = argparse.ArgumentParser()
    p.add_argument('--prepare', action='store_true', help='Download pinned test/base artifacts and install only into .venv')
    p.add_argument('--yes', action='store_true', help='Explicit unattended approval for --prepare (e.g. CI)')
    p.add_argument('--phone', action='store_true', help='Also run 3 observation cycles on a connected phone; no gestures')
    p.add_argument('--optional-smoke', action='store_true', help='Also install and exercise the seven closed optional wheel dependencies')
    args = p.parse_args(argv)
    out = ROOT/'reports'
    out.mkdir(exist_ok=True)
    report = {'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'os':platform.platform(), 'python':platform.python_version(),
              'bits':struct.calcsize('P')*8, 'windows_tests':'NOT_RUN',
              'phone_tests':'NOT_RUN', 'gpu_tests':'NOT_RUN', 'checks':[]}
    def save():
        (out/'windows_test_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if platform.system() != 'Windows':
        report['reason']='Requires real Windows; current OS is '+platform.system()
        save(); print(report['reason']); return 2
    manifest = DependencyManifest(ROOT/'bootstrap/dependencies_pc.yaml')
    ids=manifest.profiles['windows-tests']+(manifest.profiles['windows-optional-smoke'] if args.optional_smoke else [])+['adb']
    specs=[manifest.by_id[i] for i in dict.fromkeys(ids)]
    if not all(s.compatible() for s in specs):
        report['reason']='Requires Windows x64, regular CPython 3.13 (not ARM64/free-threaded)'
        save();print(report['reason']);return 2
    env=os.environ.copy()
    env['PYTHONUTF8']='1'
    env['PYTHONPATH']=os.pathsep.join([str(ROOT),str(ROOT/'legacy_level8'),str(ROOT/'legacy_level8/legacy_level6')])
    env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    def run(name,cmd,timeout=600):
        result=subprocess.run(cmd,cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout)
        (out/(name+'.log')).write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        report['checks'].append({'name':name,'exit_code':result.returncode,'status':'PASS' if result.returncode==0 else 'FAIL'})
        save()
        if result.returncode:raise RuntimeError(name+' failed; see reports/'+name+'.log')
        print(name+': PASS')
    py=ROOT/'.venv/Scripts/python.exe'
    try:
        if args.prepare:
            ops=[{'name':'Windows test environment','action':f'Download {len(specs)-1} hashed wheels and ADB; create local .venv; install wheels with --no-deps --no-index; run tests',
                  'reason':'Reproducible Windows acceptance','benefit':'Report of real Windows execution','risks':'Local project files and disk space; ADB diagnostics'}]
            gate=BatchPermissionGate(ask=(lambda _: 'Y') if args.yes else input,audit_path=out/'windows_prepare_audit.jsonl')
            if not gate.approve(ops):
                report['reason']='Preparation declined';save();return 2
            dl=PCDownloader()
            downloaded=[]
            for s in specs:
                f=dl.download(s.url,ROOT/'downloads'/artifact_filename(s),s.sha256)
                downloaded.append(f)
                report['checks'].append({'name':'sha256:'+s.id,'status':'PASS'})
            run('create_venv',[sys.executable,'-m','venv',str(ROOT/'.venv')])
            run('venv_platform',[str(py),'-c',"import sys,struct,platform; assert sys.version_info[:2]==(3,13) and struct.calcsize('P')==8 and platform.machine().lower() in ('amd64','x86_64')"])
            # All transitive dependencies are already in the list; pip cannot fetch extras.
            wheels=[str(f) for s,f in zip(specs,downloaded) if s.artifact=='wheel']
            run('install_locked_wheels',[str(py),'-m','pip','install','--no-index','--no-deps','--disable-pip-version-check',*wheels])
            adb=manifest.by_id['adb']
            dl.extract(downloaded[-1],ROOT/adb.target)
            save()
        if not py.is_file():raise RuntimeError('Run with --prepare to create the pinned .venv')
        env['PATH']=str(ROOT/'tools/android/platform-tools')+os.pathsep+env.get('PATH','')
        run('pip_check',[str(py),'-m','pip','check'])
        run('runtime_imports',[str(py),'-c',"import numpy,cv2,PIL,requests; print(numpy.__version__,cv2.__version__,PIL.__version__,requests.__version__)"])
        if args.optional_smoke:
            run('optional_runtime',[str(py),str(ROOT/'optional_windows_smoke.py')])
        run('adb_version',[str(ROOT/'tools/android/platform-tools/adb.exe'),'version'])
        run('pytest',[str(py),'-m','pytest','-q','-o','addopts=','tests_l9','legacy_level8/tests/test_level8.py','--junitxml='+str(out/'windows_junit.xml')])
        run('bootstrap_report',[str(py),'-m','bootstrap.bootstrap','--report'])
        report['windows_tests']='PASS'
        if args.phone:
            run('phone_observation',[str(py),'main_pc_l9.py','--steps','3'],timeout=120)
            report['phone_tests']='PASS_OBSERVATION_ONLY'
        save();print('Report: reports/windows_test_report.json');return 0
    except Exception as exc:
        if report['windows_tests']!='PASS':report['windows_tests']='FAIL'
        if args.phone and report['windows_tests']=='PASS':report['phone_tests']='FAIL'
        report['reason']=str(exc);save();print(str(exc));return 1

if __name__=='__main__':
    raise SystemExit(main())
