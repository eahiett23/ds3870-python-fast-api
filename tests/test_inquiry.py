"""Verify inquiry persistence and the related job endpoints."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from database import tbl_inquiries, tbl_jobs
from main import app


class InquiryTests(unittest.TestCase):
    def setUp(self):
        obj_directory = self.enterContext(tempfile.TemporaryDirectory())
        str_url = "sqlite:///" + (Path(obj_directory) / "inquiries.db").as_posix()
        self.enterContext(patch.dict(os.environ, {"CONNECTIONSTRING": str_url}))
        self.dict_payload = {
            "customer_name": "Test Customer", "email": "test@example.com",
            "company": "Test Company", "service": "Prototyping",
            "project_details": "Build a prototype for testing.",
        }

    def test_submission_persists_and_job_endpoints_still_work(self):
        with TestClient(app) as obj_client:
            lst_ids = []
            for str_budget in ["", "$500"]:
                dict_payload = dict(self.dict_payload)
                if str_budget:
                    dict_payload["budget"] = str_budget
                obj_response = obj_client.post("/api/inquiry", json=dict_payload)
                self.assertEqual(obj_response.status_code, 201)
                dict_job = obj_response.json()["job"]
                lst_ids.append(dict_job["id"])
                self.assertEqual(dict_job["inquiry_id"], dict_job["id"])
                with app.state.obj_engine.connect() as obj_connection:
                    self.assertEqual(dict(obj_connection.execute(select(tbl_jobs).where(
                        tbl_jobs.c.id == dict_job["id"])).mappings().one()), dict_job)
                self.assertEqual(dict_job["status"], "Pending")
                self.assertIsNone(dict_job["estimated_completion_date"])
                self.assertIsNone(dict_job["estimated_shipping_date"])
                self.assertIn("created_at", dict_job)
                with app.state.obj_engine.connect() as obj_connection:
                    dict_record = dict(obj_connection.execute(select(tbl_inquiries).where(
                        tbl_inquiries.c.id == dict_job["id"])).mappings().one())
                self.assertEqual(dict_record, {**self.dict_payload, "budget": str_budget,
                                               "id": dict_job["id"]})
            self.assertNotEqual(*lst_ids)
            self.assertEqual(len(obj_client.get("/api/jobs").json()["jobs"]), 2)
            self.assertEqual(obj_client.get("/api/jobs").json()["inquiries"], [])
            self.assertEqual(obj_client.get("/api/jobs?role=admin").status_code, 403)
            obj_response = obj_client.put("/api/jobs/" + lst_ids[0],
                                          headers={"x-user-role": "admin"},
                                          json={"status": "Completed", "estimated_completion_date": "2026-11-01",
                                                "estimated_shipping_date": "2026-11-02"})
            self.assertEqual(obj_response.status_code, 200)
            self.assertEqual(len(obj_client.get("/api/jobs").json()["jobs"]), 1)
        with TestClient(app) as obj_client:
            obj_response = obj_client.get("/api/jobs?role=admin", headers={"x-user-role": "admin"})
            self.assertEqual(obj_response.status_code, 200)
            dict_saved = {dict_row["id"]: dict_row for dict_row in obj_response.json()["jobs"]}
            self.assertEqual(set(dict_saved), set(lst_ids))
            self.assertEqual(dict_saved[lst_ids[0]]["status"], "Completed")
            self.assertEqual(dict_saved[lst_ids[0]]["estimated_completion_date"], "2026-11-01")
            self.assertEqual(dict_saved[lst_ids[0]]["estimated_shipping_date"], "2026-11-02")
            self.assertEqual(len(obj_client.get("/api/jobs").json()["jobs"]), 1)
            self.assertEqual({dict_row["id"] for dict_row in obj_response.json()["inquiries"]},
                             set(lst_ids))

    def test_invalid_submission_does_not_write(self):
        with TestClient(app) as obj_client:
            obj_response = obj_client.post("/api/inquiry", json={**self.dict_payload, "email": "invalid"})
            self.assertEqual(obj_response.status_code, 422)
            with app.state.obj_engine.connect() as obj_connection:
                self.assertEqual(obj_connection.execute(select(tbl_inquiries)).all(), [])
            self.assertEqual(obj_client.get("/api/jobs").json()["jobs"], [])

    def test_failed_database_write_does_not_create_job(self):
        with TestClient(app, raise_server_exceptions=False) as obj_client:
            with patch.object(app.state.obj_engine, "begin", side_effect=SQLAlchemyError("Write failed")):
                obj_response = obj_client.post("/api/inquiry", json=self.dict_payload)
            self.assertEqual(obj_response.status_code, 500)
            self.assertEqual(obj_client.get("/api/jobs").json()["jobs"], [])
            with app.state.obj_engine.connect() as obj_connection:
                self.assertEqual(obj_connection.execute(select(tbl_inquiries)).all(), [])

    def test_failed_job_insert_rolls_back_inquiry(self):
        def fail_job_insert(obj_connection, obj_cursor, str_statement, obj_parameters,
                            obj_context, bool_executemany):
            if str_statement.startswith("INSERT INTO jobs"):
                raise SQLAlchemyError("Job insert failed")

        with TestClient(app, raise_server_exceptions=False) as obj_client:
            event.listen(app.state.obj_engine, "before_cursor_execute", fail_job_insert)
            try:
                self.assertEqual(obj_client.post("/api/inquiry", json=self.dict_payload).status_code, 500)
            finally:
                event.remove(app.state.obj_engine, "before_cursor_execute", fail_job_insert)
            with app.state.obj_engine.connect() as obj_connection:
                self.assertEqual(obj_connection.execute(select(tbl_inquiries)).all(), [])
                self.assertEqual(obj_connection.execute(select(tbl_jobs)).all(), [])

    def test_job_requires_existing_inquiry(self):
        with TestClient(app) as obj_client:
            dict_job = obj_client.post("/api/inquiry", json=self.dict_payload).json()["job"]
            for str_inquiry_id in [None, "missing-inquiry"]:
                with self.subTest(inquiry_id=str_inquiry_id), self.assertRaises(IntegrityError):
                    with app.state.obj_engine.begin() as obj_connection:
                        obj_connection.execute(tbl_jobs.insert().values(
                            **{**dict_job, "id": "orphan-job", "inquiry_id": str_inquiry_id}))

    def test_update_authorization_missing_job_and_validation(self):
        with TestClient(app) as obj_client:
            self.assertEqual(obj_client.put("/api/jobs/missing", json={"status": "Pending"}).status_code, 403)
            self.assertEqual(obj_client.put("/api/jobs/missing", headers={"x-user-role": "admin"},
                                            json={"status": "Pending"}).status_code, 404)
            dict_job = obj_client.post("/api/inquiry", json=self.dict_payload).json()["job"]
            self.assertEqual(obj_client.put("/api/jobs/" + dict_job["id"],
                                            headers={"x-user-role": "admin"},
                                            json={"status": "Invalid"}).status_code, 422)
            self.assertEqual(obj_client.get("/api/jobs").json()["jobs"][0]["status"], "Pending")
