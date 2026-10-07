from pathlib import Path
import zipfile
import re
import json
import shutil
import csv

SCRATCH=Path(__file__).parent
OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-count-removal')
for test_id,variant,label in [(520,'before-count','load-vu30-r1'),(532,'after-slice','load-vu30-r3')]:
    destination=OUT/'controlled-ab'/variant/'raw'/label
    excerpts=[]
    with zipfile.ZipFile(SCRATCH/f'failure-{test_id}.zip') as archive:
        for name in archive.namelist():
            if not name.endswith('.log'):
                continue
            lines=archive.read(name).decode('utf-8',errors='replace').splitlines()
            for index,line in enumerate(lines):
                if 'SocketTimeoutException' not in line:
                    continue
                start=max(0,index-8)
                end=min(len(lines),index+12)
                excerpt='\n'.join(lines[start:end])
                excerpt=re.sub(r'eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+','[JWT REDACTED]',excerpt)
                excerpts.append({'source':name,'line':index+1,'excerpt':excerpt})
                if len(excerpts)>=3:
                    break
            if len(excerpts)>=3:
                break
    failures=[]
    for path in (destination/'request-samples').glob('*.csv'):
        with path.open(encoding='utf-8-sig',newline='') as stream:
            for sample in csv.DictReader(stream):
                if sample['success']=='true':
                    continue
                failures.append({'source':path.name,**sample})
    data={'testId':test_id,'failureCount':len(failures),'failureSamples':failures,
          'controllerLogStackTraces':excerpts,
          'note':'Controller worker log contained no detailed exception stack traces. failureRoot is from the script traversal of Throwable cause chains; request samples and history totals do not prove the exact timeout stage.'}
    (destination/'failure-analysis.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'testId':test_id,'failureCount':len(failures),'firstFailure':failures[0] if failures else None},ensure_ascii=False,indent=2))
shutil.copyfile(__file__,OUT/'execution/inspect_failure.py')
