"""Prepare existing local H2 load-test members for manual nGrinder UI runs.

No backend restart, direct SQL writes, or load stages. JWTs stay in container-local
files; Controller changes are runtime resources, token file references, fixture IDs and dates.
"""
import argparse
import base64
import hashlib
import hmac
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

PERF = Path(__file__).resolve().parents[1]
TOKEN_FILE = '/tmp/knockin-ngrinder-tokens.txt'
JWT_PATTERN = r'[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}'


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def docker(*args, data=None):
    result = subprocess.run(['docker', *args], input=data, capture_output=True, timeout=60)
    if result.returncode:
        raise RuntimeError('Docker operation failed: ' + result.stderr.decode('utf-8', errors='replace')[:300])
    return result.stdout.decode('utf-8', errors='replace')


def issue_tokens(project, members, hours):
    # Same HS512 claims/key source as the local test backend's TokenProvider.
    resources = project / 'src/main/resources'
    key = None
    for name in ['application.properties', 'application-secret-common.properties',
                 'application-test.properties', 'application-secret-test.properties']:
        path = resources / name
        if path.is_file():
            for line in path.read_text('utf-8').splitlines():
                match = re.match(r'^\s*jwt\.key\s*[=:]\s*(.*)$', line)
                if match:
                    key = match.group(1).strip()
    if not key or key.startswith('${'):
        raise RuntimeError('Cannot resolve the local test JWT key')
    if len(key.encode('utf-8')) < 64:
        raise RuntimeError('Local JWT key does not support HS512')
    def encode(value):
        raw = json.dumps(value, separators=(',', ':')).encode('utf-8')
        return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()
    issued = int(time.time())
    expires = issued + hours * 3600
    tokens = []
    for member in members:
        message = encode({'alg': 'HS512'}) + '.' + encode({
            'sub': member['PROVIDER_ID'], 'memberId': int(member['ID']),
            'role': 'USER', 'iat': issued, 'exp': expires})
        signature = base64.urlsafe_b64encode(hmac.new(key.encode('utf-8'), message.encode(),
                                                   hashlib.sha512).digest()).rstrip(b'=').decode()
        tokens.append(message + '.' + signature)
    return tokens, expires


def classify_validation(script, log, source='api'):
    """A missing Totals table means unknown execution results, not a failed API."""
    totals = re.search(r'(?m)^Totals\s+(\d+)\s+(\d+)', log)
    successes, errors = (int(totals[1]), int(totals[2])) if totals else (None, None)
    explicit = re.search(r'(CONTRACT_MISMATCH|HTTP_REQUEST_FAILED|TRANSPORT_FAILED):\s*([^\r\n]+)', log)
    has_error = bool(re.search(r'\bERROR\b|Caused by:', log))
    if explicit:
        outcome = explicit[1]
        # Runtime diagnostics consist only of fixed failure codes/classes and HTTP status.
        diagnostic = re.match(r'[A-Za-z0-9_]+(?:/[A-Za-z0-9_]+)? \(HTTP \d+\)', explicit[2])
        message = diagnostic[0] if diagnostic else 'See validation log'
    elif totals and successes == 1 and errors == 0 and not has_error:
        outcome, message = 'PASSED', 'One request succeeded'
    elif has_error and re.search(r'beforeProcess|beforeThread|initializ|MultipleCompilationErrorsException', log, re.IGNORECASE):
        outcome, message = 'SETUP_FAILED', 'Script compilation or initialization failed; see validation log'
    elif not totals and has_error:
        outcome, message = 'SETUP_FAILED', 'Script compilation or initialization failed; see validation log'
    elif totals and (errors or has_error):
        outcome, message = 'REQUEST_FAILED', 'Request execution failed; see validation log'
    else:
        outcome, message = 'RESULT_COLLECTION_FAILED', 'Expected Totals for one request were not collected'
    return {'script': script, 'passed': outcome == 'PASSED', 'outcome': outcome,
            'message': message, 'logSource': source, 'successes': successes, 'errors': errors}


def validation_content(content, marker):
    anchor = 'static void beforeProcess() {'
    if content.count(anchor) != 1:
        raise RuntimeError('Cannot correlate validation: expected one beforeProcess method')
    return content.replace(anchor, anchor + "\n        grinder.logger.info('" + marker + "')", 1)


def resolve_validation_log(api_log, marker, read_process_log, pause=time.sleep):
    if re.search(r'(?m)^Totals\s+\d+\s+\d+', api_log):
        return api_log, 'api'
    # nGrinder 3.5.9 can return stderr alone. Never accept another validation's process log.
    for attempt in range(3):
        try:
            process_log = read_process_log()
        except (RuntimeError, OSError):
            process_log = ''
        if marker in process_log and re.search(r'(?m)^Totals\s+\d+\s+\d+|\bERROR\b|Caused by:', process_log):
            return process_log, 'controller-process-log'
        if attempt < 2:
            pause(0.2)
    return api_log, 'api'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend-project', required=True, type=Path)
    parser.add_argument('--output-directory', type=Path)
    parser.add_argument('--token-hours', type=int, default=168,
                        help='Local test token lifetime; default matches the backend access token lifetime (7 days)')
    parser.add_argument('--validate-all', action='store_true', help='One UI Validate per registered read script')
    parser.add_argument('--verify-agent', action='store_true', help='One authenticated search request on an Agent')
    args = parser.parse_args()
    if not 1 <= args.token_hours <= 168:
        parser.error('--token-hours must be between 1 and 168')
    spec = importlib.util.spec_from_file_location('board_baseline', PERF / 'tools/run-roommate-board-baseline.py')
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)
    auth = 'Basic ' + base64.b64encode((os.getenv('NGRINDER_USERNAME', 'admin') + ':' +
                                      os.getenv('NGRINDER_PASSWORD', 'admin')).encode()).decode()
    def api(path, payload=None, form=False, method=None):
        body = None
        headers = {'Authorization': auth}
        if payload is not None:
            body = (urllib.parse.urlencode(payload).encode() if form else
                    json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            headers['Content-Type'] = ('application/x-www-form-urlencoded' if form else
                                       'application/json;charset=UTF-8')
        request = urllib.request.Request('http://localhost' + path, data=body,
                                         headers=headers, method=method)
        with urllib.request.urlopen(request, timeout=120) as response:
            text = response.read().decode('utf-8')
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text
    if api('/perftest/api/status')['runningTestsCount']:
        raise RuntimeError('Controller has an active performance test')
    health = baseline.request('http://localhost:8080/actuator/health')
    if health.get('status') != 'UP' or health.get('components', {}).get('db', {}).get('details', {}).get('database') != 'H2':
        raise RuntimeError('Only the healthy local H2 test backend is supported')
    database = baseline.H2()
    members = database.query("SELECT m.ID,m.PROVIDER_ID,b.ID AS BOARD_ID,c.CHATTING_ROOM_ID,h.ID AS HOUSE_RULE_ID,cal.START_DATE FROM MEMBER m JOIN ROOMMATE_BOARD b ON b.MEMBER_ID=m.ID AND b.IS_DELETED=FALSE JOIN CHAT_ROOM_MEMBER c ON c.MEMBER_ID=m.ID AND c.IS_LEFT=FALSE JOIN ROOMMATE_HOUSE_RULE h ON h.MEMBER_ID=m.ID AND h.IS_DELETED=FALSE JOIN ROOMMATE_CALENDAR cal ON cal.MEMBER_ID=m.ID AND cal.IS_DELETED=FALSE WHERE m.ROLE='USER' AND m.IS_DELETE=FALSE AND m.PROVIDER_ID LIKE 'load_test_user_%' ORDER BY m.ID LIMIT 30")
    if len(members) != 30 or len({row['ID'] for row in members}) != 30 or not all(
            row['PROVIDER_ID'].startswith('load_test_user_') for row in members):
        raise RuntimeError('Expected 30 distinct existing load-test members with fixtures')
    dates = {datetime.fromisoformat(row['START_DATE']).date() for row in members}
    if len(dates) != 1:
        raise RuntimeError('Calendar fixtures have mixed dates')
    calendar = dates.pop()
    tokens, expires = issue_tokens(args.backend_project.resolve(), members, args.token_hours)
    probe = urllib.request.Request('http://localhost:8080/users/me/boards?page=0&size=20',
                                   headers={'Authorization': 'Bearer ' + tokens[0]})
    with urllib.request.urlopen(probe, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError('Current backend rejected the test member/token (HTTP status)')
    agent_names = docker('ps', '--filter', 'ancestor=ngrinder/agent:3.5.9-p1', '--format', '{{.Names}}').splitlines()
    if not agent_names:
        raise RuntimeError('No running nGrinder Agents')
    containers = ['ngrinder-controller'] + agent_names
    for container in containers:
        docker('exec', container, 'sh', '-c',
               'test -z "$ROOMMATE_BOARD_TOKENS" && test -z "$ROOMMATE_BOARD_TOKEN_FILE"')
    scripts = sorted(path for path in (PERF / 'script').rglob('*.groovy') if 'resources' not in path.parts)
    if len(scripts) != 17:
        raise RuntimeError('Expected the 17 read scripts')
    originals, updates = {}, {}
    for script in scripts:
        entry = api('/script/api/detail/' + script.name)['file']
        originals[script.name] = entry
        content = entry['content']
        if script.stem not in ['RoommateBoardListGetTest', 'RoommateBoardListKeywordGetTest']:
            content, count = re.subn(r'(?m)^(\s*static final List<String> TOKEN_POOL = )[^\r\n]+',
                                    lambda match: match[1] + "new File('" + TOKEN_FILE + "').readLines('UTF-8')", content)
            if count != 1:
                raise RuntimeError('Unexpected token declaration: ' + script.name)
            pools = {'BOARD_ID_POOL': 'BOARD_ID', 'OWNED_BOARD_ID_POOL': 'BOARD_ID',
                     'CHAT_ROOM_ID_POOL': 'CHATTING_ROOM_ID', 'HOUSE_RULE_ID_POOL': 'HOUSE_RULE_ID',
                     'TARGET_MEMBER_ID_POOL': 'ID'}
            for pool, field in pools.items():
                fixture = members[1:] + members[:1] if pool == 'TARGET_MEMBER_ID_POOL' else members
                content = re.sub(r'(?m)^(\s*static final List<Long> ' + pool + r' = )[^\r\n]+',
                                 lambda match: match[1] + '[' + ','.join(row[field] + 'L' for row in fixture) + ']', content)
            for field, value in [('YEAR', calendar.year), ('MONTH', calendar.month), ('DAY', calendar.day)]:
                content = re.sub(r'(static final int ' + field + r' = )\d+',
                                 lambda match: match[1] + str(value), content)
        updates[script.name] = content
    config_path = 'resources/roommate-board-list.json'
    originals[config_path] = api('/script/api/detail/' + config_path)['file']
    config = json.loads(originals[config_path]['content'])
    config['tokenFile'] = TOKEN_FILE
    config.setdefault('expectedStatusCodes', [200])
    config.setdefault('responseValidator', None)
    if config.get('runId') == 'CHANGE-ME':
        config['runId'] = 'ui-' + datetime.now().strftime('%Y%m%d-%H%M%S')
    updates[config_path] = json.dumps(config, ensure_ascii=False, indent=2) + '\n'
    for name in ['RoommateBoardListSupport.txt', 'RoommateBoardPageContract.txt']:
        path = 'resources/' + name
        entry = api('/script/api/detail/' + path).get('file')
        originals[path] = entry or {'fileType': 'TXT', 'content': None, 'encoding': 'UTF-8'}
        updates[path] = (PERF / 'script/roommate/resources' / name).read_text('utf-8')
    output = (args.output_directory or PERF / 'results' / (datetime.now().strftime('%Y-%m-%d') + '-ui-readiness') /
              datetime.now().strftime('%H%M%S')).resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / 'summary.json').exists():
        raise RuntimeError('Use a new output directory to preserve previous checks')
    def deploy(path, content):
        entry = originals[path]
        api('/script/api/save/' + path, {'fileEntry': {'path': path, 'content': content,
            'fileType': entry['fileType'], 'description': entry.get('description') or '',
            'encoding': entry.get('encoding') or 'UTF-8'}, 'targetHosts': 'host.docker.internal',
            'validated': '0', 'createLibAndResource': False})
        actual = api('/script/api/detail/' + path)['file']
        if actual['content'] != content:
            raise RuntimeError('Deployment content mismatch: ' + path)
        return {'path': path, 'revision': actual['revision'],
                'sha256': hashlib.sha256(content.encode()).hexdigest()}
    summary = {'startedAt': datetime.now().astimezone().isoformat(),
               'tokenExpiresAt': datetime.fromtimestamp(expires, timezone(timedelta(hours=9))).isoformat(),
               'tokenCount': 30, 'tokenFile': TOKEN_FILE, 'containers': containers,
               'memberIds': [int(row['ID']) for row in members], 'calendarDate': calendar.isoformat(),
               'activeKeywordProfile': config['activeKeywordProfile'],
               'expectedStatusCodes': config.get('profiles', {}).get(config['activeKeywordProfile'], {}).get('expectedStatusCodes', config['expectedStatusCodes']),
               'responseValidator': config.get('profiles', {}).get(config['activeKeywordProfile'], {}).get('responseValidator', config['responseValidator']),
               'deployments': [], 'validations': []}
    changed = []
    try:
        for container in containers:
            docker('exec', '-i', container, 'sh', '-c',
                   'umask 077; cat > ' + TOKEN_FILE + '.tmp && chmod 600 ' + TOKEN_FILE + '.tmp && mv ' + TOKEN_FILE + '.tmp ' + TOKEN_FILE,
                   data=('\n'.join(tokens) + '\n').encode('utf-8'))
        for path, content in updates.items():
            if content == originals[path]['content']:
                continue
            changed.append(path)
            summary['deployments'].append(deploy(path, content))
    except Exception:
        for path in reversed(changed):
            if originals[path]['content'] is not None:
                deploy(path, originals[path]['content'])
        raise
    print('Prepared 30 local fixture members on Controller and ' + str(len(agent_names)) + ' Agents; expires=' + summary['tokenExpiresAt'], flush=True)
    save(output / 'summary.json', summary)
    selected = scripts if args.validate_all else [path for path in scripts if path.stem == 'RoommateBoardListKeywordGetTest']
    for script in selected:
        marker = 'ui-validation-' + uuid.uuid4().hex
        content = validation_content(updates[script.name], marker)
        api_log = api('/script/api/validate', {'fileEntry': {'path': script.name, 'content': content},
                                             'hostString': 'host.docker.internal'})
        if not isinstance(api_log, str):
            api_log = json.dumps(api_log)
        username = os.getenv('NGRINDER_USERNAME', 'admin')
        if not re.fullmatch(r'[A-Za-z0-9_-]+', username):
            raise RuntimeError('Cannot safely locate the Controller validation log for this username')
        log, source = resolve_validation_log(api_log, marker, lambda: docker('exec', 'ngrinder-controller',
            'cat', '/opt/ngrinder-controller/script/' + username + '/validation-0.log'))
        api_log = re.sub(JWT_PATTERN, '[REDACTED_JWT]', api_log)
        log = re.sub(JWT_PATTERN, '[REDACTED_JWT]', log)
        (output / (script.stem + '.api.log')).write_text(api_log, encoding='utf-8')
        (output / (script.stem + '.log')).write_text(log, encoding='utf-8')
        row = classify_validation(script.name, log, source)
        summary['validations'].append(row)
        save(output / 'summary.json', summary)
        print(('PASS' if row['passed'] else row['outcome']) + ' ' + script.name + ': ' + row['message'], flush=True)
    if args.verify_agent and all(row['passed'] for row in summary['validations']):
        created = api('/perftest/api', {'testName': 'ui-readiness-authenticated-search-' + datetime.now().strftime('%Y%m%d-%H%M%S'),
            'description': 'UI input preparation check; one request; no load stage',
            'scriptName': 'RoommateBoardListKeywordGetTest.groovy', 'status': 'READY', 'threshold': 'R',
            'runCount': 1, 'agentCount': 1, 'processes': 1, 'threads': 1, 'vuserPerAgent': 1,
            'targetHosts': 'host.docker.internal', 'samplingInterval': 2, 'useRampUp': 'false',
            'connectionReset': 'false', 'ignoreTooManyError': 'false', 'ignoreSampleCount': 0}, form=True)
        test_id = created['id']
        print('Agent one-request search check test=' + str(test_id), flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            state = api('/perftest/api/' + str(test_id))
            if state.get('finishTime') and not state['status'].get('stoppable', True):
                break
            time.sleep(2)
        else:
            api('/perftest/api/' + str(test_id) + '?action=stop', method='PUT')
            raise RuntimeError('One-request Agent check timed out')
        save(output / 'agent-test.json', state)
        save(output / 'agent-basic-report.json', api('/perftest/api/' + str(test_id) + '/basic_report'))
        summary['agentCheck'] = {'testId': test_id, 'status': state['status']['name'],
                                 'successes': state.get('tests'), 'errors': state.get('errors'),
                                 'passed': state['status']['name'] == 'FINISHED' and state.get('tests') == 1 and state.get('errors') == 0}
        print('Agent check: ' + json.dumps(summary['agentCheck']), flush=True)
    summary['finishedAt'] = datetime.now().astimezone().isoformat()
    summary['passed'] = all(row['passed'] for row in summary['validations']) and summary.get('agentCheck', {}).get('passed', True)
    save(output / 'summary.json', summary)
    print('Summary: ' + str(output / 'summary.json'), flush=True)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
