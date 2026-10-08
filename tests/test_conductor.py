# SPDX-License-Identifier: AGPL-3.0-only
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor

storage = tempfile.TemporaryDirectory()
os.environ['CONDUCTOR_DATABASE_URL'] = 'sqlite:///' + storage.name + '/test.db'
os.environ['CONDUCTOR_ADMIN_TOKEN'] = 'test-admin-token'
os.environ['CONDUCTOR_REPORT_TOKEN'] = 'test-report-token'
from alembic.config import Config
from alembic import command
command.upgrade(Config('alembic.ini'), 'head')
import asyncio
import httpx

class TestClient:
    def __init__(self, app):
        self.app = app
    def request(self, method, path, **kwargs):
        async def run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.request(method, path, **kwargs)
        return asyncio.run(run())
    def get(self, path, **kwargs):
        return self.request("GET", path, **kwargs)
    def post(self, path, **kwargs):
        return self.request("POST", path, **kwargs)
    def put(self, path, **kwargs):
        return self.request("PUT", path, **kwargs)
    def close(self):
        pass
from app.main import app
from app.core.database import engine

class ConductorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.headers = {'Authorization': 'Bearer test-admin-token'}

    def test_workflow(self):
        c, h = self.client, self.headers
        self.assertEqual(c.get('/health').json(), {'status':'ok','service':'denops-conductor'})
        self.assertEqual(c.get('/api/overview').status_code, 401)
        self.assertEqual(c.get('/').status_code, 200)
        self.assertIn('GNU AFFERO GENERAL PUBLIC LICENSE',c.get('/license').text)
        source=c.get('/source')
        self.assertEqual(source.status_code,200)
        self.assertEqual(source.headers['content-type'],'application/gzip')
        payload = {'name':'Travel','slug':'travel','repository':'https://github.com/denops/travel'}
        p = c.post('/api/projects', headers=h, json=payload)
        self.assertEqual(p.status_code, 201, p.text)
        pid = p.json()['id']
        self.assertEqual(c.post('/api/projects', headers=h, json=payload).status_code, 409)
        self.assertEqual(c.put(f'/api/projects/{pid}', headers=h, json={**payload,'migration_directory':'../escape'}).status_code, 422)
        self.assertEqual(c.post('/api/builders', headers=h, json={'project_id':pid,'vm_id':101,'name':'Travel repair','node':'alpha'}).status_code, 201)
        low = {'project_id':pid,'severity':'low','title':'Failure','error_signature':'same'}
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: c.post('/api/repairs', headers=h, json=low), range(4)))
        self.assertTrue(all(r.status_code == 201 for r in results))
        ids = {r.json()['id'] for r in results}
        self.assertEqual(len(ids), 1)
        issued=c.post(f'/api/projects/{pid}/report-credentials',headers=h,json={'name':'Application reporter'})
        self.assertEqual(issued.status_code,201)
        token=issued.json()['token']
        reporting_headers={'Authorization':'Bearer '+token}
        self.assertEqual(c.post('/api/reports',headers={'Authorization':'Bearer test-report-token'},json=low).status_code,401)
        other=c.post('/api/projects',headers=h,json={**payload,'name':'Other','slug':'other'}).json()['id']
        self.assertEqual(c.post('/api/reports',headers=reporting_headers,json={**low,'project_id':other}).status_code,403)
        self.assertEqual(c.get('/api/overview',headers=reporting_headers).status_code,401)
        critical = c.post('/api/reports',headers=reporting_headers,json={**low,'severity':'critical','error_signature':'critical'}).json()
        self.assertNotIn('notes',critical)
        listed=c.get(f'/api/projects/{pid}/report-credentials',headers=h)
        self.assertNotIn(token,listed.text)
        self.assertNotIn('token_digest',listed.text)
        from app.models import ReportCredential
        from app.core.database import Session
        with Session() as db:
            credential=db.get(ReportCredential,issued.json()['id'])
            self.assertNotEqual(credential.token_digest,token)
        self.assertEqual(c.post(f"/api/report-credentials/{issued.json()['id']}/revoke",headers=h).status_code,200)
        self.assertEqual(c.post('/api/reports',headers=reporting_headers,json=low).status_code,401)
        self.assertEqual(c.get('/api/overview',headers={'Authorization':'Bearer test-report-token'}).status_code,401)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reservations=list(pool.map(lambda _: c.post('/api/queue/reserve',headers=h),range(2)))
        self.assertEqual(sorted(r.status_code for r in reservations),[200,409])
        reserved=next(r for r in reservations if r.status_code==200)
        self.assertEqual(reserved.json()['id'],critical['id'])
        overview=c.get('/api/overview',headers=h).json()
        dedup=next(r for r in overview['repairs'] if r['id'] in ids)
        self.assertEqual(dedup['occurrence_count'],4)
        self.assertEqual(overview['builders'][0]['power_state'],'unknown')
        self.assertFalse(overview['alpha']['infrastructure_verified'])
        detail=c.get(f"/api/repairs/{critical['id']}",headers=h).json()
        self.assertTrue(any(e['action']=='repair-reserved' for e in detail['events']))
        self.assertTrue(overview['audit'])
        self.assertEqual(c.get('/api/infrastructure').status_code,401)
        resource=c.post('/api/infrastructure/resources',headers=h,json={'name':'Test sandbox','kind':'proxmox-vm','node':'builder','vm_id':115,'expected_state':'on-demand'})
        self.assertEqual(resource.status_code,201,resource.text)
        rid=resource.json()['id']
        self.assertEqual(c.post('/api/infrastructure/resources',headers=h,json={'name':'Incomplete','kind':'proxmox-vm'}).status_code,422)
        check=c.post('/api/infrastructure/checks',headers=h,json={'resource_id':rid,'probe_kind':'proxmox-vm'})
        self.assertEqual(check.status_code,201,check.text)
        identity=check.json()['id']
        self.assertEqual(c.post('/api/infrastructure/checks',headers=h,json={'resource_id':rid,'probe_kind':'proxmox-vm'}).status_code,409)
        result=c.post(f'/api/infrastructure/checks/{identity}/run',headers=h)
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['status'],'unknown')
        infra=c.get('/api/infrastructure',headers=h).json()
        self.assertFalse(infra['automatic_recovery'])
        self.assertEqual(infra['checks'][0]['observation']['status'],'unknown')
        history=c.get(f'/api/infrastructure/checks/{identity}/history',headers=h).json()
        self.assertEqual(len(history),1)
        from app.core.database import Session
        from app.models import DomainEvent
        from sqlalchemy import select
        with Session() as db:
            events=list(db.scalars(select(DomainEvent)))
            self.assertEqual(sum(e.event_type=='repair.queued' for e in events),2)
            self.assertTrue(any(e.event_type=='monitor.observed' for e in events))

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        engine.dispose()
        storage.cleanup()
