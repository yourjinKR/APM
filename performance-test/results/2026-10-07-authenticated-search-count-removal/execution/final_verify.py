from pathlib import Path
from datetime import datetime, timezone, timedelta
import importlib.util
import json
import hashlib
import gzip
import re
import socket
import subprocess
import shutil

OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-count-removal')
BACKEND=Path(r'C:\dev\workspace\KnockIn\back\11th-1team-BE')
def read(path):
    return json.loads(path.read_text('utf-8-sig'))
spec=importlib.util.spec_from_file_location('focused_verify',OUT/'execution/focused_search_lib.py')
lib=importlib.util.module_from_spec(spec)
spec.loader.exec_module(lib)
originals=read(OUT/'execution/controlled-controller-originals.json')
restored={name:lib.api('/script/api/detail/'+name)['file']['content']==entry['content'] for name,entry in originals.items()}
idle=lib.api('/perftest/api/status')['runningTestsCount']==0
token_checks={}
for variant in ['before-count','after-slice']:
    folder=OUT/'controlled-ab'/variant
    token_file=read(folder/'environment.json')['tokenFile']
    containers=list(read(folder/'cleanup.json')['tokensRemoved'])
    token_checks[variant]={}
    for container in containers:
        completed=subprocess.run(['docker','exec',container,'test','!','-e',token_file],capture_output=True)
        token_checks[variant][container]=completed.returncode==0
def listening(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=1):
            return True
    except OSError:
        return False
original_server=listening(8080)
measurement_stopped=not listening(18080)
build=next(item for item in read(OUT/'controlled-ab/builds.json') if item['variant']=='after-slice')
source_match={name:hashlib.sha256((BACKEND/name).read_bytes()).hexdigest()==expected for name,expected in build['sourceHashes'].items()}
broken_links=[]
report=(OUT/'report.md').read_text('utf-8')
for link in re.findall(r'\]\(([^)]+)\)',report):
    if not link.startswith(('http://','https://')) and not (OUT/link.split('#',1)[0]).exists():
        broken_links.append(link)
secret_files=[]
jwt=re.compile(rb'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}')
for path in OUT.rglob('*'):
    if not path.is_file():
        continue
    content=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes()
    if jwt.search(content):
        secret_files.append(str(path.relative_to(OUT)))
data={'verifiedAtKst':datetime.now(timezone(timedelta(hours=9))).isoformat(),
      'controllerIdle':idle,'controllerOriginalContentRestored':restored,'ownedTokenFilesAbsent':token_checks,
      'existingBackend8080Listening':original_server,'measurementBackend18080Stopped':measurement_stopped,
      'userSliceSourceUnchanged':source_match,'brokenReportLinks':broken_links,'jwtBearingResultFiles':secret_files,
      'controlledLoadRequestsVerified':read(OUT/'verification.json')['measurementComplete']}
data['passed']=idle and all(restored.values()) and all(all(checks.values()) for checks in token_checks.values())
data['passed']=data['passed'] and original_server and measurement_stopped and all(source_match.values()) and not broken_links and not secret_files and data['controlledLoadRequestsVerified']
(OUT/'post-verification.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copyfile(__file__,OUT/'execution/final_verify.py')
print(json.dumps(data,ensure_ascii=False,indent=2))
if not data['passed']:
    raise SystemExit('Final verification failed')
