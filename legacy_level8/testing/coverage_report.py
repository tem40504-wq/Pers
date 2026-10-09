"""Отчёт coverage.json от pytest-cov; не подделываем проценты."""
from pathlib import Path
import json

def summarize(path='coverage.json',critical_prefixes=('stealth/', 'testing/')):
    path=Path(path)
    if not path.exists():
        return {'status':'MISSING','coverage':None,'uncovered':[],
                'known_bugs':['coverage.json не создан'],
                'recommendations':['Запустите pytest --cov=stealth --cov=testing --cov-report=json']}
    report=json.loads(path.read_text(encoding='utf-8'))
    files=report.get('files',{})
    included={k:v for k,v in files.items() if any(p in k.replace('\\','/') for p in critical_prefixes)}
    counts=[(v.get('summary',{}).get('covered_lines',0),v.get('summary',{}).get('num_statements',0)) for v in included.values()]
    covered,total=map(sum,zip(*counts)) if counts else (0,0)
    percent=covered/total*100 if total else 0
    missing=[{'file':name,'lines':v.get('missing_lines',[])} for name,v in included.items() if v.get('missing_lines')]
    return {'status':'PASS' if percent>=80 else 'FAIL','coverage':round(percent,1),
            'uncovered':missing,'known_bugs':[],'recommendations':[] if percent>=80 else ['Дополнить тесты критических веток']}
