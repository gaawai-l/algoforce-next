"""Verify test ingress isolation and a real analysis task without printing credentials."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

parser=argparse.ArgumentParser()
parser.add_argument('url')
parser.add_argument('--session-file', type=Path, help='Private JSON containing session_cookie; omit for anonymous checks')
args=parser.parse_args()
values=json.loads(args.session_file.read_text()) if args.session_file else None
base=args.url.rstrip('/')
with httpx.Client(timeout=30,follow_redirects=False) as client:
    page = client.get(base + '/')
    if page.status_code == 302 and page.headers.get('location') == '/market-intelligence?method=td':
        page = client.get(base + page.headers['location'])
    assert page.status_code == 302 and page.headers['location'].startswith('/login/'), page.status_code
    assert 'www-authenticate' not in page.headers
    assert client.get(base + '/login/').status_code == 200
    for endpoint in ('/api/v1/settings', '/api/wheelhouse/v1/status'):
        response = client.get(base + endpoint)
        assert response.status_code == 401 and 'www-authenticate' not in response.headers, endpoint
    assert client.post(base + '/api/wheelhouse/v1/portfolio/sync', json={}).status_code == 403
    assert client.post(base + '/auth/challenge', json={}, headers={'Origin': 'https://unrelated.example'}).status_code == 403
    if values is None:
        print(json.dumps({'wallet_login_page': 'passed', 'anonymous_api': 'blocked', 'basic_auth': 'removed', 'broker_sync': 'blocked'}))
        raise SystemExit(0)
    client.headers['Cookie'] = values['session_cookie']
    for endpoint in ('/market-intelligence?method=td','/api/v1/healthz','/api/wheelhouse/v1/status'):
        response=client.get(base+endpoint)
        assert response.status_code==200,(endpoint,response.status_code)
    assert client.post(base+'/api/wheelhouse/v1/portfolio/sync',json={}).status_code==403
    assert client.post(base+'/api/wheelhouse/v1/jobs',json={},headers={'Origin':'https://unrelated.example'}).status_code==403
    response=client.post(base+'/api/wheelhouse/v1/jobs',json={
        'kind':'refresh','stream':{'source':'fixture','symbol':'BTCUSDT','timeframe':'1h'},
        'rules':{'demark':{}}},headers={'Idempotency-Key':uuid4().hex,'Origin':base})
    response.raise_for_status()
    identifier=response.json()['job_id']
    deadline=time.monotonic()+40
    while time.monotonic()<deadline:
        job=client.get(base+'/api/wheelhouse/v1/jobs/'+identifier).json()
        if job['state'] in ('failed','succeeded'):break
        time.sleep(.5)
    assert job['state']=='succeeded',job.get('error_code')
    result=client.get(base+'/api/wheelhouse/v1/snapshots/'+job['snapshot_id']).json()
    assert result.get('demark') and result['data_state']=='simulated'
    context=client.get(base+'/api/wheelhouse/v1/market-context',params={'source':'fixture','symbol':'BTCUSDT'})
    assert context.status_code==200,context.status_code
    hour=next(t for t in context.json()['timeframes'] if t['timeframe']=='1h')
    assert hour['status']=='simulated' and context.json()['intraday']['value']!='unavailable'
    print(json.dumps({'ingress_auth':'passed','cross_origin':'blocked','broker_sync':'blocked',
                      'demark':'passed','closed_bars':len(result['bars']),'market_context':'passed'}))
