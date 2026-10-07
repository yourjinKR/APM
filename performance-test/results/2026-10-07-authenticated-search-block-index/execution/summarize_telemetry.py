from pathlib import Path
import json
import re
import shutil
from statistics import median

OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-block-index')
summaries=[]
for variant in ['before-or','after-index-and','current-steady']:
    folder=OUT/'controlled-ab'/variant
    cases=json.loads((folder/'suite-summary.json').read_text('utf-8'))
    logs=[json.loads(line) for line in (folder/'telemetry.jsonl').read_text('utf-8').splitlines()]
    selected={row['testId']:[] for row in cases if row['phase'] in ['load','steady-observation']}
    previous_count=None
    for row in logs:
        request_count=sum(float(line.rsplit(' ',1)[1]) for line in row.get('metrics',[])
            if line.startswith('http_server_requests_seconds_count{') and 'uri="/roommate/boards"' in line)
        active=request_count is not None and previous_count is not None and request_count>previous_count
        previous_count=request_count
        if row['activeTestId'] not in selected or not active:
            continue
        values={}
        heap=0
        for line in row.get('metrics',[]):
            key=line.split('{',1)[0]
            if key in ['process_cpu_usage','system_cpu_usage','hikaricp_connections_active','hikaricp_connections_pending']:
                values[key]=float(line.rsplit(' ',1)[1])
            if key=='jvm_memory_used_bytes' and 'area="heap"' in line:
                heap+=float(line.rsplit(' ',1)[1])
        values['heapUsedBytes']=heap
        selected[row['activeTestId']].append(values)
    for case in cases:
        if case['phase'] not in ['load','steady-observation']:
            continue
        entries=selected[case['testId']]
        data={'variant':variant,'testId':case['testId'],'vu':case['vu'],'repeat':case['repeat'],
              'activeRequestScrapes':len(entries),'samplingIntervalSeconds':5}
        for key in ['process_cpu_usage','system_cpu_usage','hikaricp_connections_active','hikaricp_connections_pending','heapUsedBytes']:
            values=[entry[key] for entry in entries if key in entry]
            data[key]={'median':median(values),'max':max(values)} if values else None
        summaries.append(data)
(OUT/'telemetry-summary.json').write_text(json.dumps({'note':'Only intervals with increasing server request counts; 5-second samples, observed peaks rather than exact maxima','runs':summaries},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copyfile(__file__,OUT/'execution/summarize_telemetry.py')
print('Server CPU, heap and Hikari observations summarized')

