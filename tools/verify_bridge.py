"""Bounded real-device API acceptance. Prints no authentication key."""
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

root = Path(__file__).resolve().parents[1]
config = json.loads((root / 'deploy/config/bridge.json').read_text())
evidence = []
def call(path, method='GET', body=None, auth=True):
    headers = {'Content-Type': 'application/json'}
    if auth: headers['Authorization'] = 'Bearer ' + config['key']
    request = Request(config['esp32_url'] + path, headers=headers, method=method,
                      data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None)
    try:
        with urlopen(request, timeout=6) as response:
            return response.status, json.load(response)
    except HTTPError as error:
        return error.code, json.load(error)

def check(name, condition):
    evidence.append(dict(check=name, passed=bool(condition)))
    print(name, 'PASS' if condition else 'FAIL')
    assert condition, name

try:
    check('unauthenticated access rejected', call('/health', auth=False)[0] == 401)
    ready_deadline = time.monotonic() + 40
    status, health = call('/health')
    while not (health.get('ready') and health.get('idle')) and time.monotonic() < ready_deadline:
        time.sleep(2)
        status, health = call('/health')
    check('Muse ready on physical ESP32', status == 200 and health['ready'] and health['idle'])
    check('invalid request rejected', call('/requests', 'POST', {'request_id': '../bad', 'text': 'hello'})[0] == 400)
    request_id = str(uuid4())
    text = '请只用一句简短的中文说：这是小爱连接Muse的测试。'
    status, job = call('/requests', 'POST', {'request_id': request_id, 'text': text})
    check('remote text accepted', status == 202)
    try:
        status, repeated = call('/requests', 'POST', {'request_id': request_id, 'text': text})
        check('duplicate ID returns same job', status == 200 and repeated['request_id'] == request_id)
        check('ID payload conflict rejected', call('/requests', 'POST', {'request_id': request_id, 'text': 'different'})[0] == 409)
        check('competing cloud turn rejected', call('/requests', 'POST', {'request_id': str(uuid4()), 'text': 'second'})[0] == 503)
        deadline = time.monotonic() + 100
        while job['status'] in ('queued', 'running') and time.monotonic() < deadline:
            time.sleep(1)
            _, job = call('/requests/' + request_id)
        check('real Muse cloud reply received', job['status'] == 'completed' and bool(job.get('reply')))
        print('Reply:', job['reply'])
        evidence.append(dict(reply=job['reply'], request_id=request_id, boot=health['boot']))
    finally:
        call('/requests/' + request_id + '/cancel', 'POST')
    time.sleep(1)
    cancel_id = str(uuid4())
    check('cancellation test submitted', call('/requests', 'POST', {'request_id': cancel_id, 'text': '请写一个非常详细的长篇故事'})[0] == 202)
    _, active_job = call('/requests/' + cancel_id)
    started_deadline = time.monotonic() + 10
    while active_job['status'] == 'queued' and time.monotonic() < started_deadline:
        time.sleep(0.1)
        _, active_job = call('/requests/' + cancel_id)
    check('cancellation applies to a running request', active_job['status'] == 'running')
    status, cancelled = call('/requests/' + cancel_id + '/cancel', 'POST')
    check('cancellation accepted', status == 200 and cancelled['status'] == 'cancelled')
    time.sleep(2)
    check('cancelled result remains cancelled', call('/requests/' + cancel_id)[1]['status'] == 'cancelled')
    idle_deadline = time.monotonic() + 10
    _, after_cancel = call('/health')
    while not after_cancel['idle'] and time.monotonic() < idle_deadline:
        time.sleep(1)
        _, after_cancel = call('/health')
    check('worker available after cancel', after_cancel['idle'])
finally:
    (root / 'artifacts/2026-10-06/api-acceptance.json').write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding='utf-8')
