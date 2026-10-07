from pathlib import Path
import json
import math

SCRATCH=Path(__file__).parent
OUT=Path(r'C:\dev\workspace\prography\APM\performance-test\results\2026-10-07-authenticated-search-block-index')
loads=[row for row in json.loads((OUT/'controlled-ab/after-index-and/suite-summary.json').read_text('utf-8')) if row['phase']=='load' and row['vu']==30]
if len(loads)!=3 or not (OUT/'controlled-ab/after-index-and/cleanup.json').exists():
    raise RuntimeError('Finish the controlled comparison before preparing the supplemental run')
rate=max(row['successes']/row['sampleSpanSeconds'] for row in loads)
count=min(10000,max(1000,math.ceil(rate*90/30)))
target=OUT/'controlled-ab/current-steady'
target.mkdir()
runner=(SCRATCH/'run_pair.py').read_text('utf-8')
def replace(old,new):
    global runner
    if old not in runner:
        raise RuntimeError('Missing supplemental adaptation marker: '+old[:100])
    runner=runner.replace(old,new)
replace("builds = json.loads((OUT/'controlled-ab/builds.json').read_text('utf-8'))", "builds = [dict(row,variant='current-steady') for row in json.loads((OUT/'controlled-ab/builds.json').read_text('utf-8')) if row['variant']=='after-index-and']\nSTEADY_COUNT="+str(count))
replace("OUT/'execution/controlled-controller-originals.json'","OUT/'execution/steady-controller-originals.json'")
replace("OUT/'execution/run_pair.py'","OUT/'execution/run_steady.py'")
replace("variant=='after-index-and'","variant=='current-steady'")
replace("'vusers':[10,30],'requestsPerVu':100,'repetitions':3", "'vusers':[30],'requestsPerVu':STEADY_COUNT,'repetitions':1")
replace("'warmup':'1 VU x20 then 10 VU x50 (500 requests); same on both variants'", "'warmup':'1 VU x20 then 30 VU x200 (6000 requests); supplemental current-version observation'")
replace("lib.run_case('jit-warmup',10,50,1)", "lib.run_case('jit-warmup',30,200,1)")
replace('for repeat in [1,2,3]:','for repeat in [1]:')
replace('for vu in [10,30]:','for vu in [30]:')
replace("lib.run_case('load',vu,100,repeat)","lib.run_case('steady-observation',vu,STEADY_COUNT,repeat)")
replace("OUT/'controlled-ab/summary.json'","OUT/'controlled-ab/steady-summary.json'")
replace('capture_block_plans(lib,target,variant)',"capture_block_plans(lib,target,'after-index-and')")
replace("print('CONTROLLED BLOCK INDEX/AND BEFORE/AFTER COMPLETE',flush=True)","print('SUPPLEMENTAL CURRENT STEADY OBSERVATION COMPLETE',flush=True)")
(SCRATCH/'run_steady.py').write_text(runner,encoding='utf-8')
(target/'plan.json').write_text(json.dumps({'purpose':'Current implementation observed longer because comparison runs became short; excluded from before/after improvement medians',
    'vu':30,'requestsPerVu':count,'plannedRequests':30*count,'targetSeconds':90,'estimatedRateFromControlled30Vu':rate},indent=2)+'\n',encoding='utf-8')
print(f'Supplemental current run planned: 30 VU x {count} = {30*count} requests',flush=True)
