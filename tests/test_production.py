"""API integration using SQLite-adapted tables; MySQL triggers require live tests."""
import os
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, Integer, String, DateTime, MetaData, DefaultClause, text, select, event
from sqlalchemy.dialects.mysql import BIGINT, ENUM, DATETIME, TINYINT
from database import enable_sqlite_foreign_keys
from sqlalchemy.orm import Session
from main import app
from production.models import Base, User, UserSession, Inquiry, Job, JobMilestone
from production.api import obj_hasher, utc_now


class ProductionTests(unittest.TestCase):
    def setUp(self):
        obj_directory = self.enterContext(tempfile.TemporaryDirectory())
        self.obj_engine = create_engine('sqlite:///' + (Path(obj_directory) / 'production.db').as_posix())
        event.listen(self.obj_engine, 'connect', enable_sqlite_foreign_keys)
        self.addCleanup(self.obj_engine.dispose)
        # Copy, rather than mutate, production metadata. This tests API behavior,
        # not MySQL DDL or database triggers.
        obj_metadata = MetaData()
        for obj_source in Base.metadata.sorted_tables:
            obj_table = obj_source.to_metadata(obj_metadata)
            for obj_column in obj_table.columns:
                if isinstance(obj_column.type, (BIGINT, TINYINT)):
                    obj_column.type = Integer()
                elif isinstance(obj_column.type, ENUM):
                    obj_column.type = String(64)
                elif isinstance(obj_column.type, DATETIME):
                    obj_column.type = DateTime()
                if obj_column.name in {'created_at', 'updated_at'}:
                    obj_column.server_default = DefaultClause(text('CURRENT_TIMESTAMP'))
        obj_metadata.create_all(self.obj_engine)
        with Session(self.obj_engine) as obj_session, obj_session.begin():
            for int_id, str_role in [(1, 'admin'), (2, 'customer'), (3, 'customer')]:
                obj_session.add(User(id=int_id, email=f'user{int_id}@example.com', password_hash=obj_hasher.hash('Correct-password-123'), role=str_role, first_name='Test', last_name=str(int_id)))
            obj_session.flush()
            obj_session.add_all([
                Job(id=1, job_number='TEST-1', customer_id=2, title='Owned', description='Owned job', service_type='cnc', updated_by_admin_id=1),
                Job(id=2, job_number='TEST-2', customer_id=3, title='Other', description='Other job', service_type='software', updated_by_admin_id=1)])
        self.enterContext(patch.dict(os.environ, {'DATABASE_MODE': 'production'}))
        self.enterContext(patch('main.initialize_database', return_value=self.obj_engine))
        self.obj_client = self.enterContext(TestClient(app))

    def login(self, int_user):
        obj_response = self.obj_client.post('/api/auth/login', json={'email': f'user{int_user}@example.com', 'password': 'Correct-password-123'})
        self.assertEqual(obj_response.status_code, 200)
        return {'Authorization': 'Bearer ' + obj_response.json()['access_token']}

    def test_role_headers_cannot_grant_access(self):
        self.assertEqual(self.obj_client.get('/api/jobs?role=admin', headers={'X-User-Role':'admin'}).status_code, 401)
        dict_headers = self.login(2)
        self.assertEqual(self.obj_client.get('/api/jobs?role=admin', headers=dict_headers).status_code, 403)
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'in_production', 'version':1}).status_code, 403)

    def test_customer_can_only_read_own_jobs_and_timeline(self):
        dict_headers = self.login(2)
        obj_response = self.obj_client.get('/api/jobs', headers=dict_headers)
        self.assertEqual([obj_job['id'] for obj_job in obj_response.json()['jobs']], ['1'])
        self.assertEqual(self.obj_client.get('/api/jobs/2/milestones', headers=dict_headers).status_code, 404)
        self.assertEqual(self.obj_client.get('/api/jobs/1/milestones', headers=dict_headers).status_code, 200)

    def test_login_failure_logout_expiry_and_disabled_user(self):
        self.assertEqual(self.obj_client.post('/api/auth/login', json={'email':'user2@example.com','password':'wrong'}).status_code, 401)
        dict_headers = self.login(2)
        self.assertEqual(self.obj_client.post('/api/auth/logout', headers=dict_headers).status_code, 200)
        self.assertEqual(self.obj_client.get('/api/jobs', headers=dict_headers).status_code, 401)
        dict_headers = self.login(2)
        with Session(self.obj_engine) as obj_session, obj_session.begin():
            for obj_record in obj_session.scalars(select(UserSession).where(UserSession.user_id == 2)):
                obj_record.expires_at = utc_now() - timedelta(seconds=1)
                obj_record.created_at = utc_now() - timedelta(days=1)
        self.assertEqual(self.obj_client.get('/api/jobs', headers=dict_headers).status_code, 401)
        with Session(self.obj_engine) as obj_session, obj_session.begin():
            obj_session.get(User, 2).is_active = 0
        self.assertEqual(self.obj_client.post('/api/auth/login', json={'email':'user2@example.com','password':'Correct-password-123'}).status_code, 401)

    def test_public_inquiry_does_not_create_job_and_keeps_budget_range(self):
        obj_response = self.obj_client.post('/api/inquiry', json={'customer_name':'Public Customer','email':'public@example.com','company':'Example Company','service':'CNC Machining','project_details':'Build two sensor brackets.','budget':'$2,500–$10,000'})
        self.assertEqual(obj_response.status_code, 201)
        self.assertNotIn('job', obj_response.json())
        with Session(self.obj_engine) as obj_session:
            obj_record = obj_session.get(Inquiry, int(obj_response.json()['inquiry_id']))
            self.assertIsNone(obj_record.customer_id)
            self.assertIsNone(obj_record.target_budget)
            self.assertIn('$2,500–$10,000', obj_record.description)
            self.assertEqual(len(obj_session.scalars(select(Job)).all()), 2)

    def test_authenticated_inquiry_conversion_and_owner_mismatch(self):
        dict_customer_headers = self.login(2)
        obj_response = self.obj_client.post('/api/inquiry', headers=dict_customer_headers, json={'customer_name':'Test Customer','email':'user2@example.com','company':'Example Company','service':'3D Printing','project_details':'Print a nylon enclosure.','budget':'1250.00'})
        self.assertEqual(obj_response.status_code, 201)
        str_id = obj_response.json()['inquiry_id']
        dict_admin_headers = self.login(1)
        self.assertEqual(self.obj_client.post(f'/api/inquiries/{str_id}/convert', headers=dict_admin_headers, json={'customer_id':3,'title':'Enclosure'}).status_code, 422)
        obj_response = self.obj_client.post(f'/api/inquiries/{str_id}/convert', headers=dict_admin_headers, json={'customer_id':2,'title':'Enclosure'})
        self.assertEqual(obj_response.status_code, 201)
        self.assertEqual(obj_response.json()['job']['status'], 'intake')
        self.assertEqual(self.obj_client.post(f'/api/inquiries/{str_id}/convert', headers=dict_admin_headers, json={'customer_id':2,'title':'Enclosure'}).status_code, 409)

    def test_admin_progress_shipping_and_stale_version(self):
        dict_headers = self.login(1)
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'in_production'}).status_code, 422)
        obj_response = self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'in_production','progress_percentage':55,'version':1})
        self.assertEqual(obj_response.status_code, 200)
        self.assertEqual(obj_response.json()['job']['version'], 2)
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'shipped','version':1}).status_code, 409)
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'shipped','version':2}).status_code, 422)
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'completed','version':2,'progress_percentage':100}).status_code, 422)
        obj_response = self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'shipped','version':2,'actual_shipping_date':'2026-10-10','carrier_name':'UPS','tracking_number':'TEST','tracking_url':'https://www.ups.com/track'})
        self.assertEqual(obj_response.status_code, 200)
        self.assertEqual(obj_response.json()['job']['tracking_number'], 'TEST')
        self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={'status':'completed','version':3,'progress_percentage':100,'actual_completion_date':'2026-10-11'}).status_code, 200)

    def test_invalid_values_do_not_change_job(self):
        dict_headers = self.login(1)
        for dict_payload in [{'status':'in_production','progress_percentage':101}, {'status':'in_production','progress_percentage':None}, {'status':'in_production','tracking_url':'javascript:alert(1)'}, {'status':'Pending'}]:
            with self.subTest(payload=dict_payload):
                self.assertEqual(self.obj_client.put('/api/jobs/1', headers=dict_headers, json={**dict_payload,'version':1}).status_code, 422)
        with Session(self.obj_engine) as obj_session:
            self.assertEqual(obj_session.get(Job, 1).status, 'intake')

    def test_configuration_and_frontend_assets(self):
        self.assertEqual(self.obj_client.get('/api/config').json()['mode'], 'production')
        self.assertIn('/production.js', self.obj_client.get('/').text)
        self.assertEqual(self.obj_client.get('/production.js').status_code, 200)

    def test_notes_require_admin_and_show_in_customer_timeline(self):
        dict_customer = self.login(2)
        self.assertEqual(self.obj_client.post('/api/jobs/1/milestones', headers=dict_customer, json={'note':'Unauthorized'}).status_code, 403)
        dict_admin = self.login(1)
        self.assertEqual(self.obj_client.post('/api/jobs/1/milestones', headers=dict_admin, json={'note':'Dimensions verified.'}).status_code, 201)
        obj_response = self.obj_client.get('/api/jobs/1/milestones', headers=dict_customer)
        self.assertEqual(obj_response.json()['milestones'][0]['note'], 'Dimensions verified.')


if __name__ == '__main__':
    unittest.main()
