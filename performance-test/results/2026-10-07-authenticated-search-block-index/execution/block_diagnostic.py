import json
import re

def capture_block_plans(lib,target,variant):
    def explain(sql):
        html=lib.base.request(lib.base.BACKEND+'/h2-console/query.do?jsessionid='+lib.db.sid,'POST',
                              {'sql':'EXPLAIN ANALYZE '+sql,'maxrows':'0'},form=True)
        table=lib.base.ResultTable()
        table.feed(html)
        if not table.rows:
            raise RuntimeError('H2 did not return an EXPLAIN result')
        return '\n'.join(cell for row in table.rows[1:] for cell in row)
    requester=int(lib.ids[0])
    if variant=='before-or':
        condition=f'NOT EXISTS(SELECT 1 FROM block b WHERE b.is_deleted=FALSE AND ((b.blocker_id={requester} AND b.blocked_id=rb.member_id) OR (b.blocker_id=rb.member_id AND b.blocked_id={requester})))'
    else:
        condition=f'NOT EXISTS(SELECT 1 FROM block b WHERE b.is_deleted=FALSE AND b.blocked_id={requester} AND b.blocker_id=rb.member_id) AND NOT EXISTS(SELECT 1 FROM block c WHERE c.is_deleted=FALSE AND c.blocker_id={requester} AND c.blocked_id=rb.member_id)'
    sql='SELECT rb.id FROM roommate_board rb WHERE '+condition+' ORDER BY rb.created_at DESC,rb.id DESC LIMIT 21'
    plan=explain(sql)
    summary=json.loads((target/'sql-diagnostics/summary.json').read_text('utf-8'))
    content=[row for row in summary['statements'] if re.search(r'\bfrom roommate_board\b',row['sql'].lower()) and not row['sql'].lower().startswith('select count(')]
    if len(content)!=1:
        raise RuntimeError('Expected exactly one content query shape')
    content_sql=content[0]['sql']
    blocked_subqueries=len(re.findall(r'not exists\(select 1 from block\b',content_sql,re.I))
    expected=1 if variant=='before-or' else 2
    if blocked_subqueries!=expected or summary['boardCountExecutions']!=0:
        raise RuntimeError('Runtime content SQL does not match expected Block predicates/count removal')
    has_index='IDX_BLOCK_BLOCKER_BLOCKED_DELETED' in plan.upper()
    lib.save(target/'sql-diagnostics/block-plan.json',{'note':'Read-only EXPLAIN ANALYZE of the same Block predicates on roommate_board; this focused query excludes API joins, filters and history storage.',
        'query':sql,'plan':plan,'runtimeContentSql':content_sql,'blockNotExistsSubqueries':blocked_subqueries,
        'newCompositeIndexUsedByFocusedPlan':has_index,
        'contentSqlMeanMs':content[0]['meanMs'],'contentSqlTotalMs':content[0]['totalMs']})
    if variant=='after-index-and' and not has_index:
        raise RuntimeError('New composite index was not used by the focused Block plan')
    print(f'BLOCK PLAN subqueries={blocked_subqueries} compositeIndex={has_index}',flush=True)
