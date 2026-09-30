"""Collect SQL statistics and bound EXPLAIN ANALYZE after local controls finish."""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import time
import urllib.parse


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    parser.add_argument('--jar',required=True,type=Path)
    args=parser.parse_args();directory=args.directory.resolve();output=directory/'sql-diagnostics';output.mkdir(exist_ok=True)
    spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('run-roommate-board-baseline.py'))
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    request=runner.request;save=runner.save;backend=runner.BACKEND
    cases=json.loads((directory/'suite-summary.json').read_text(encoding='utf-8'))
    valid=[r for r in cases if r['phase']=='control' and r.get('measurementComplete',r['passed']) and not r.get('excludedFromControls')]
    if len(valid)!=12:raise RuntimeError('Complete all 12 accounting-verified controls before diagnostics')
    import base64,os
    auth='Basic '+base64.b64encode((os.getenv('NGRINDER_USERNAME','admin')+':'+os.getenv('NGRINDER_PASSWORD','admin')).encode()).decode()
    if request(runner.CONTROLLER+'/perftest/api/status',headers={'Authorization':auth})['runningTestsCount']!=0:
        raise RuntimeError('Controller must be idle')
    if request(backend+'/actuator/health')['components']['db']['details']['database']!='H2':raise RuntimeError('Local H2 only')
    db=runner.H2()
    def execute(sql):
        html=request(backend+'/h2-console/query.do?jsessionid='+db.sid,'POST',{'sql':sql,'maxrows':'0'},form=True)
        if 'class="error"' in html:raise RuntimeError('H2 diagnostic command failed: '+sql[:100])
        return html
    def rows(sql):
        table=runner.ResultTable();table.feed(execute(sql))
        if not table.rows:raise RuntimeError('H2 diagnostic query returned no table')
        return [dict(zip(table.rows[0],row)) for row in table.rows[1:]]
    # This bundled H2 does not expose QUERY_STATISTICS in SETTINGS.
    initial_stats=db.query('SELECT SQL_STATEMENT,EXECUTION_COUNT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')
    if initial_stats:raise RuntimeError('Unexpected statistics collected before diagnostics')
    save(output/'statistics-preflight.json',{'entriesBeforeEnable':len(initial_stats),
        'observation':'QUERY_STATISTICS not listed in SETTINGS; no entries after completed load; enable/disable commands verified with statistics table'})
    members=db.query('SELECT ID,PROVIDER_ID FROM MEMBER WHERE ID=2')
    token=runner.jwt_tokens(args.jar,members)[0]
    config=json.loads((directory/'fixture-config.json').read_text(encoding='utf-8'))
    paths=['list-anonymous','list-authenticated','search-frequent-anonymous','search-frequent-authenticated']
    loggers=('org.hibernate.SQL','org.hibernate.orm.jdbc.bind')
    original={name:request(backend+'/actuator/loggers/'+name).get('configuredLevel') for name in loggers}
    stats_sql='SELECT SQL_STATEMENT,EXECUTION_COUNT,CUMULATIVE_EXECUTION_TIME,AVERAGE_EXECUTION_TIME,MAX_EXECUTION_TIME FROM INFORMATION_SCHEMA.QUERY_STATISTICS'
    def snapshot():
        # Fresh command avoids reusing a cached result of this changing meta-table.
        probe=stats_sql.replace('SELECT ',f'SELECT /* perfstats-{time.time_ns()} */ ',1)
        return {r['SQL_STATEMENT']:r for r in db.query(probe)}
    def get(profile):
        item=config['profiles'][profile]['inputs'][0];query=dict(item['query'])
        if profile.startswith('search-'):query['keyword']=item['keyword']
        headers={'Accept':'application/json'}
        if config['profiles'][profile]['auth']=='authenticated':headers['Authorization']='Bearer '+token
        start=time.perf_counter();data=request(backend+'/roommate/boards?'+urllib.parse.urlencode(query,doseq=True),headers=headers)
        duration=(time.perf_counter()-start)*1000
        if data['status']!=200 or data['data']['totalElements']!=item['expect']['totalElements']:
            raise RuntimeError('Diagnostic response contract failed: '+profile)
        return duration
    started=datetime.now(timezone.utc).isoformat();groups=[];captures=[]
    try:
        execute('SET QUERY_STATISTICS_MAX_ENTRIES 1000');execute('SET QUERY_STATISTICS TRUE')
        for profile in paths:
            for _ in range(3):get(profile)
            before=snapshot();history_before=db.snapshot([2]);http=[]
            for _ in range(10):http.append(get(profile))
            after=snapshot();history_after=db.snapshot([2]);statements=[]
            save(output/(profile+'-statistics-snapshots.json'),{'before':before,'after':after})
            for sql,entry in after.items():
                if 'INFORMATION_SCHEMA' in sql.upper() or sql.upper().startswith(('SELECT COUNT(*) AS TOTAL','SET ')):continue
                previous=before.get(sql,{})
                count=int(entry['EXECUTION_COUNT'])-int(previous.get('EXECUTION_COUNT',0))
                elapsed=float(entry['CUMULATIVE_EXECUTION_TIME'])-float(previous.get('CUMULATIVE_EXECUTION_TIME',0))
                if count>0:statements.append({'sql':sql,'executions':count,'totalMs':elapsed,'meanMs':elapsed/count})
            statements.sort(key=lambda r:r['totalMs'],reverse=True)
            group={'profile':profile,'requests':10,'httpMeanMs':sum(http)/len(http),'httpDurationsMs':http,
                'historyDelta':history_after['total']-history_before['total'],'statements':statements,
                'sqlTotalMs':sum(s['totalMs'] for s in statements)}
            expected=10 if profile=='search-frequent-authenticated' else 0
            if group['historyDelta']!=expected:raise RuntimeError('Diagnostic history delta mismatch')
            groups.append(group);save(output/(profile+'-statistics.json'),group)
            content=[s for s in statements if re.search(r'from roommate_board\b',s['sql'].lower()) and not s['sql'].lower().startswith('select count(')]
            counts=[s for s in statements if re.search(r'from roommate_board\b',s['sql'].lower()) and s['sql'].lower().startswith('select count(')]
            if sum(s['executions'] for s in content)!=10 or sum(s['executions'] for s in counts)!=10:
                raise RuntimeError('Content/count execution deltas must each equal diagnostic requests: '+profile)
            if profile.startswith('search-') and not all(' like ' in s['sql'].lower() for s in content+counts):
                raise RuntimeError('Search SQL statistics do not contain the keyword predicate')
        for name,level in zip(loggers,('DEBUG','TRACE')):
            request(backend+'/actuator/loggers/'+name,'POST',{'configuredLevel':level})
        logfile=directory/'backend.out.log'
        for profile in paths:
            offset=logfile.stat().st_size
            get(profile);time.sleep(.5)
            with logfile.open('rb') as source:source.seek(offset);text=source.read().decode('utf-8',errors='replace')
            safe=[line for line in text.splitlines() if 'org.hibernate.SQL' in line or 'org.hibernate.orm.jdbc.bind' in line]
            (output/(profile+'-bound-sql.log')).write_text('\n'.join(safe)+'\n',encoding='utf-8')
            statements=[];current=None
            for line in safe:
                match=re.search(r'org.hibernate.SQL\s*:\s*(.*)',line)
                if match:
                    current={'sql':match.group(1),'bindings':{}};statements.append(current)
                elif current:
                    match=re.search(r'binding parameter \((\d+):([^)]*)\) <- \[(.*)\]',line)
                    if match:current['bindings'][int(match.group(1))]={'type':match.group(2),'value':match.group(3)}
            plans=[]
            for n,statement in enumerate(statements):
                if not statement['sql'].lower().startswith('select '):continue
                sql=statement['sql'];binding=statement['bindings'];index=0
                def literal(_):
                    nonlocal index
                    index+=1;parameter=binding[index];kind=parameter['type'];value=parameter['value']
                    if value=='null':return 'NULL'
                    if kind in ('BIGINT','INTEGER','SMALLINT','TINYINT','FLOAT','DOUBLE','DECIMAL','NUMERIC'):
                        if not re.fullmatch(r'[-+0-9.eE]+',value):raise ValueError('Non numeric bind')
                        return value
                    if kind=='BOOLEAN':return value.lower()
                    quoted="'"+value.replace("'","''")+"'"
                    if kind.startswith('TIMESTAMP'):return 'TIMESTAMP '+quoted
                    if kind=='DATE':return 'DATE '+quoted
                    return quoted
                try:bound=re.sub(r'\?',literal,sql)
                except (KeyError,ValueError) as error:
                    plans.append({'statementIndex':n,'error':type(error).__name__,'sql':sql});continue
                # Only SELECT: EXPLAIN ANALYZE executes the bound statement.
                result=rows('EXPLAIN ANALYZE '+bound)
                plan='\n'.join(str(v) for row in result for v in row.values())
                (output/f'{profile}-select-{n:02d}-plan.txt').write_text('EXPLAIN ANALYZE '+bound+'\n\n'+plan+'\n',encoding='utf-8')
                plans.append({'statementIndex':n,'sql':sql,'boundSql':bound,'plan':plan,'scanCounts':[int(x) for x in re.findall(r'scanCount: (\d+)',plan)]})
            captures.append({'profile':profile,'statements':statements,'plans':plans})
        save(output/'diagnosis.json',{'startedAtUtc':started,'finishedAtUtc':datetime.now(timezone.utc).isoformat(),
            'memberId':2,'groups':groups,'captures':captures,
            'note':'Isolated SQL diagnostic after main measurements; H2 cumulative times are milliseconds; prepared statements include executions, not full HTTP/commit time.'})
    finally:
        for name,level in original.items():request(backend+'/actuator/loggers/'+name,'POST',{'configuredLevel':level})
        execute('SET QUERY_STATISTICS FALSE')
        save(output/'cleanup.json',{'loggersRestored':{name:request(backend+'/actuator/loggers/'+name).get('configuredLevel')==level for name,level in original.items()},
            'queryStatisticsDisabled':not db.query('SELECT SQL_STATEMENT,EXECUTION_COUNT FROM INFORMATION_SCHEMA.QUERY_STATISTICS')})
    print('SQL diagnostics captured:',len(groups),'paths',sum(len(c['plans']) for c in captures),'SELECT plans')


if __name__=='__main__':main()
