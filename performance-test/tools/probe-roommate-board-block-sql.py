"""Read-only SQL prototype: split symmetric block OR into two NOT EXISTS."""
import argparse
import importlib.util
import json
from pathlib import Path
import re
from statistics import median
import time


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path)
    args=parser.parse_args();directory=args.directory.resolve();output=directory/'sql-diagnostics/block-prototype';output.mkdir(exist_ok=True)
    spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('run-roommate-board-baseline.py'))
    r=importlib.util.module_from_spec(spec);spec.loader.exec_module(r)
    db=r.H2()
    if r.request(r.BACKEND+'/actuator/health')['components']['db']['details']['database']!='H2':raise RuntimeError('Local H2 only')
    data=json.loads((directory/'sql-diagnostics/diagnosis.json').read_text(encoding='utf-8'))
    pattern=re.compile(r'not exists\(select 1 from block (\w+) where (\w+\.is_deleted=false) and \(([^()]+) or ([^()]+)\)\)')
    def execute(sql):
        html=r.request(r.BACKEND+'/h2-console/query.do?jsessionid='+db.sid,'POST',{'sql':sql,'maxrows':'0'},form=True)
        if 'class="error"' in html:raise RuntimeError('Prototype SQL failed')
        table=r.ResultTable();table.feed(html)
        return [dict(zip(table.rows[0],row)) for row in table.rows[1:]] if table.rows else []
    def rewrite(sql,member=None,split=True):
        match=pattern.search(sql)
        if not match:raise RuntimeError('Expected exact symmetric block predicate')
        alias,deleted,left,right=match.groups()
        if member is not None:
            left=left.replace('=2','= '+str(member));right=right.replace('=2','= '+str(member))
        replacement=(f'(not exists(select 1 from block {alias} where {deleted} and ({left})) and '
                     f'not exists(select 1 from block {alias} where {deleted} and ({right})))') if split else (
                     f'not exists(select 1 from block {alias} where {deleted} and ({left} or {right}))')
        return sql[:match.start()]+replacement+sql[match.end():]
    def fresh(sql,label):return sql.replace('select ',f'select /* perfproto-{label}-{time.time_ns()} */ ',1)
    def stats():
        return execute(f'SELECT /* perfprobe-{time.time_ns()} */ SQL_STATEMENT,EXECUTION_COUNT,CUMULATIVE_EXECUTION_TIME FROM INFORMATION_SCHEMA.QUERY_STATISTICS')
    results=[]
    if execute('SELECT SQL_STATEMENT FROM INFORMATION_SCHEMA.QUERY_STATISTICS'):raise RuntimeError('Statistics already enabled')
    execute('SET QUERY_STATISTICS_MAX_ENTRIES 1000');execute('SET QUERY_STATISTICS TRUE')
    try:
        for capture in data['captures']:
            if not capture['profile'].endswith('authenticated') or capture['profile'].endswith('anonymous'):continue
            for plan in capture['plans']:
                original=plan.get('boundSql','')
                if not pattern.search(original):continue
                candidate=rewrite(original)
                role='count' if original.startswith('select count(') else 'content'
                label=capture['profile']+'-'+role
                checks=[]
                for member in [2,3,4,31]:
                    before=execute(fresh(rewrite(original,member,False),'check-original'))
                    after=execute(fresh(rewrite(original,member,True),'check-candidate'))
                    if before!=after:raise RuntimeError('Prototype changed results for member '+str(member))
                    checks.append({'memberId':member,'equal':True,'returnedRows':len(before),'countResult':before if role=='count' else None})
                for version,sql in [('original',original),('candidate',candidate)]:
                    for _ in range(3):execute(fresh(sql,'warm-'+version))
                wall={};query_stats={}
                for version,sql in [('original',original),('candidate',candidate)]:
                    prefix=label+'-'+version;times=[]
                    for _ in range(10):
                        start=time.perf_counter();execute(fresh(sql,prefix));times.append((time.perf_counter()-start)*1000)
                    entries=[x for x in stats() if 'perfproto-'+prefix+'-' in x['SQL_STATEMENT']]
                    count=sum(int(x['EXECUTION_COUNT']) for x in entries)
                    if count!=10:raise RuntimeError('Prototype execution count mismatch')
                    elapsed=sum(float(x['CUMULATIVE_EXECUTION_TIME']) for x in entries)
                    wall[version]={'durationsMs':times,'medianMs':median(times)}
                    query_stats[version]={'executions':count,'totalMs':elapsed,'meanMs':elapsed/count,'entries':entries}
                    plans=execute('EXPLAIN ANALYZE '+sql)
                    text='\n'.join(str(v) for row in plans for v in row.values())
                    (output/(label+'-'+version+'-plan.txt')).write_text(sql+'\n\n'+text+'\n',encoding='utf-8')
                result={'profile':capture['profile'],'role':role,'originalSql':original,'candidateSql':candidate,
                    'memberResultChecks':checks,'consoleRoundTrip':wall,'sqlExecution':query_stats,
                    'sqlMeanReductionPercent':(1-query_stats['candidate']['meanMs']/query_stats['original']['meanMs'])*100}
                results.append(result);r.save(output/'results.json',{'experiments':results,
                    'scope':'Literal SELECT SQL on same local H2, original member2, equality checks2/3/4/31. No API/JAR/source/index changes. Unique comments force fresh commands to avoid result reuse. SQL timings exclude console/HTML round trip; not API improvement metrics.'})
    finally:
        execute('SET QUERY_STATISTICS FALSE')
        r.save(output/'cleanup.json',{'queryStatisticsDisabled':not execute('SELECT SQL_STATEMENT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')})
    print('Read-only block SQL prototypes:',len(results),'query shapes')


if __name__=='__main__':main()
