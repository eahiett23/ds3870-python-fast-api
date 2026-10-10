"""Verify inquiry persistence and the related job endpoints."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from database import tbl_inquiries
from main import app


class InquiryTests(unittest.TestCase):
    def setUp(self):
        obj_directory = self.enterContext(tempfile.TemporaryDirectory())
        str_url = "sqlite:///" + (Path(obj_directory) / "inquiries.db").as_posix()
        self.enterContext(patch.dict(os.environ, {"CONNECTIONSTRING": str_url}))
        self.lst_jobs = []
        self.enterContext(patch("main._jobs", self.lst_jobs))
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
                                          json={"status": "Completed"})
            self.assertEqual(obj_response.status_code, 200)
            self.assertEqual(len(obj_client.get("/api/jobs").json()["jobs"]), 1)
        self.lst_jobs.clear()
        with TestClient(app) as obj_client:
            obj_response = obj_client.get("/api/jobs?role=admin", headers={"x-user-role": "admin"})
            self.assertEqual(obj_response.status_code, 200)
            self.assertEqual({dict_row["id"] for dict_row in obj_response.json()["inquiries"]},
                             set(lst_ids))

    def test_invalid_submission_does_not_write(self):
        with TestClient(app) as obj_client:
            obj_response = obj_client.post("/api/inquiry", json={**self.dict_payload, "email": "invalid"})
            self.assertEqual(obj_response.status_code, 422)
            with app.state.obj_engine.connect() as obj_connection:
                self.assertEqual(obj_connection.execute(select(tbl_inquiries)).all(), [])
            self.assertEqual(self.lst_jobs, [])

    def test_failed_database_write_does_not_create_job(self):
        with TestClient(app, raise_server_exceptions=False) as obj_client:
            with patch.object(app.state.obj_engine, "begin", side_effect=SQLAlchemyError("Write failed")):
                obj_response = obj_client.post("/api/inquiry", json=self.dict_payload)
            self.assertEqual(obj_response.status_code, 500)
            self.assertEqual(self.lst_jobs, [])
            with app.state.obj_engine.connect() as obj_connection:
                self.assertEqual(obj_connection.execute(select(tbl_inquiries)).all(), [])
