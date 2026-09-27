"""Verify test ingress isolation and a real analysis task without printing credentials."""
import argparse
import json
import time
from pathlib import Path
from uuid import uuid4

import httpx

parser=argparse.ArgumentParser()
parser.add_argument('url')
parser.add_argument('--credentials',type=Path,required=True)
args=parser.parse_args()
values=json.loads(args.credentials.read_text())
base=args.url.rstrip('/')
with httpx.Client(timeout=30,follow_redirects=False) as client:
    for endpoint in ('/','/api/v1/settings','/api/wheelhouse/v1/status'):
        assert client.get(base+endpoint).status_code==401,endpoint
    client.auth=(values['TEST_AUTH_USER'],values['password'])
    for endpoint in ('/','/api/v1/healthz','/api/wheelhouse/v1/status'):
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
    print(json.dumps({'ingress_auth':'passed','cross_origin':'blocked','broker_sync':'blocked',
                      'demark':'passed','closed_bars':len(result['bars'])}))
