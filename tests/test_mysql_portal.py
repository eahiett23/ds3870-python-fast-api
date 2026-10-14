"""API contract tests using an independent SQLite fixture.

These test backend authorization/serialization; they do not prove MySQL triggers.
"""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch

import bcrypt
from fastapi.testclient import TestClient
from sqlalchemy import (Column, MetaData, Table, Integer, String, DateTime, LargeBinary,
                        Text, create_engine, event, insert, select)
from sqlalchemy.pool import StaticPool
import mysql_portal as portal


def fixture_schema():
    metadata = MetaData()
    timestamps = lambda: [Column("created_at", DateTime, default=portal.now), Column("updated_at", DateTime, default=portal.now)]
    Table("users", metadata, Column("id", Integer, primary_key=True), Column("email", String, unique=True),
          Column("password_hash", String), Column("first_name", String), Column("last_name", String),
          Column("role", String, server_default="customer"), Column("is_active", Integer, server_default="1"), *timestamps())
    Table("user_sessions", metadata, Column("id", Integer, primary_key=True), Column("user_id", Integer),
          Column("token_digest", LargeBinary, unique=True), Column("expires_at", DateTime), Column("revoked_at", DateTime), *timestamps())
    Table("inquiries", metadata, Column("id", Integer, primary_key=True), Column("customer_id", Integer),
          Column("contact_name", String), Column("contact_email", String), Column("company_name", String),
          Column("inquiry_type", String), Column("service_label", String), Column("description", Text),
          Column("budget_text", String), Column("status", String, server_default="pending"),
          Column("target_completion_at", DateTime), *timestamps())
    Table("jobs", metadata, Column("id", Integer, primary_key=True), Column("legacy_id", String, unique=True),
          Column("job_number", String, unique=True), Column("customer_id", Integer), Column("inquiry_id", Integer, unique=True),
          Column("title", String), Column("description", Text), Column("service_type", String), Column("service_label", String),
          Column("budget_text", String), Column("contact_name", String), Column("contact_email", String), Column("company_name", String),
          Column("status", String, server_default="intake"), Column("progress_percentage", Integer, server_default="0"),
          Column("target_completion_at", DateTime), Column("estimated_ship_at", DateTime), Column("actual_completion_at", DateTime),
          Column("actual_ship_at", DateTime), Column("carrier_name", String), Column("tracking_number", String), Column("tracking_url", String),
          Column("archived_at", DateTime), Column("version", Integer, server_default="1"), Column("updated_by_admin_id", Integer), *timestamps())
    Table("job_milestones", metadata, Column("id", Integer, primary_key=True), Column("job_id", Integer), Column("admin_id", Integer),
          Column("stage", String), Column("progress_percentage", Integer), Column("note", Text), Column("event_type", String), *timestamps())
    Table("job_attachments", metadata, Column("id", Integer, primary_key=True), Column("job_id", Integer), Column("inquiry_id", Integer))
    return metadata


class PortalContractTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"COOKIE_SECURE": "false"})
        self.env.start()
        self.engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
        self.metadata = fixture_schema()
        self.metadata.create_all(self.engine)
        portal.app.state.engine, portal.app.state.tables = self.engine, self.metadata.tables
        # SQLite has no MySQL user variables; capture the actor assignment without
        # pretending to enforce database triggers. Actual MySQL tests are separate.
        self.actors = []
        @event.listens_for(self.engine, "before_cursor_execute", retval=True)
        def actor_assignment(connection, cursor, statement, parameters, context, executemany):
            if statement == "SET @app_actor_id = %s":
                self.actors.append(parameters[0])
                return "SELECT ?", parameters
            return statement, parameters
        self.hash = bcrypt.hashpw(b"existing-password", bcrypt.gensalt(rounds=4)).decode()
        with self.engine.begin() as connection:
            for identifier, email, role in ((1, "admin@example.com", "admin"), (2, "customer@example.com", "customer"),
                                            (3, "other@example.com", "customer")):
                connection.execute(insert(self.metadata.tables["users"]).values(
                    id=identifier, email=email, role=role, first_name="Test", last_name="User", password_hash=self.hash))
            for identifier, owner in ((1, 2), (2, 3)):
                connection.execute(insert(self.metadata.tables["jobs"]).values(
                    id=identifier, legacy_id=f"12345678-1234-4234-8234-{identifier:012d}", job_number=str(identifier), customer_id=owner,
                    title="Prototype", description="Prototype description", service_type="design", service_label="Digital & Industrial Design",
                    budget_text="$2,500–$10,000", contact_name="Separate Contact", contact_email="contact@example.com",
                    company_name="Company", updated_by_admin_id=1))
        # No context manager: fixture engine replaces the MySQL-only lifespan.
        self.client = TestClient(portal.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.env.stop()

    def login(self, email="customer@example.com"):
        response = self.client.post("/api/auth/login", json={"email": email, "password": "existing-password"})
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_legacy_login_preserves_hash_and_cookie_contract(self):
        response = self.login()
        self.assertIn("session_token=", response.headers["set-cookie"])
        self.assertIn("HttpOnly", response.headers["set-cookie"])
        self.assertEqual(response.json(), {"email": "customer@example.com", "first_name": "Test", "last_name": "User", "is_admin": False})
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(select(self.metadata.tables["users"].c.password_hash).where(
                self.metadata.tables["users"].c.id == 2)).scalar_one(), self.hash)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 200)
        self.assertEqual(self.client.post("/api/auth/logout").status_code, 200)
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_registration_cannot_choose_admin_role(self):
        response = self.client.post("/api/auth/register", json={"email": "new@example.com", "password": "new-password-123",
                                      "first_name": "New", "last_name": "Customer", "role": "admin", "is_admin": True})
        self.assertEqual(response.status_code, 201, response.text)
        with self.engine.connect() as connection:
            row = connection.execute(select(self.metadata.tables["users"]).where(
                self.metadata.tables["users"].c.email == "new@example.com")).mappings().one()
            self.assertEqual(row["role"], "customer")
            self.assertTrue(bcrypt.checkpw(b"new-password-123", row["password_hash"].encode()))

    def test_customer_sees_only_owned_job_with_original_fields(self):
        self.login()
        jobs = self.client.get("/api/jobs").json()["jobs"]
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0]["id"], "12345678-1234-4234-8234-000000000001")
        self.assertEqual(jobs[0]["email"], "contact@example.com")
        self.assertEqual(jobs[0]["customer_email"], "customer@example.com")
        self.assertEqual(jobs[0]["budget"], "$2,500–$10,000")
        self.assertEqual(jobs[0]["status"], "Pending")

    def test_customer_cannot_update_job_or_read_other_timeline(self):
        self.login()
        self.assertEqual(self.client.put("/api/jobs/1", json={"status": "Completed"}).status_code, 403)
        self.assertEqual(self.client.get("/api/jobs/2/milestones").status_code, 404)
        self.assertEqual(self.actors, [])

    def test_inquiry_is_not_a_job_until_admin_saves(self):
        self.login()
        payload = {"customer_name": "Test Customer", "email": "customer@example.com", "company": "Company",
                   "service": "Not sure yet", "project_details": "Prototype description", "budget": "Need guidance"}
        response = self.client.post("/api/inquiry", json=payload)
        self.assertEqual(response.status_code, 201, response.text)
        inquiry_id = response.json()["job"]["id"]
        self.assertEqual(inquiry_id, "inq-1")
        self.assertEqual(len(self.client.get("/api/jobs").json()["jobs"]), 2)
        self.login("admin@example.com")
        converted = self.client.put("/api/jobs/" + inquiry_id, json={"status": "In Production"})
        self.assertEqual(converted.status_code, 200, converted.text)
        self.assertIsInstance(converted.json()["job"]["id"], str)
        self.assertEqual(converted.json()["job"]["status"], "In Production")
        self.assertEqual(self.client.put("/api/jobs/" + inquiry_id, json={"status": "In Production"}).status_code, 409)
        self.assertEqual(self.actors, [1, 1])

    def test_admin_completed_update_and_stale_version(self):
        self.login("admin@example.com")
        response = self.client.put("/api/jobs/1", json={"status": "Completed", "version": 1,
                                                        "estimated_completion_date": "2026-11-01", "public_note": "QC passed"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["job"]["progress_percentage"], 100)
        self.assertEqual(response.json()["job"]["estimated_completion_date"], "2026-11-01")
        self.assertIsNotNone(response.json()["job"]["actual_completion_date"])
        self.assertEqual(self.client.put("/api/jobs/1", json={"status": "Pending", "version": 1}).status_code, 409)
        self.assertEqual(self.client.get("/api/jobs/1/milestones").json()["milestones"][0]["note"], "QC passed")

    def test_expired_and_inactive_sessions_rejected(self):
        self.login()
        with self.engine.begin() as connection:
            connection.execute(self.metadata.tables["user_sessions"].update().values(expires_at=portal.now() - timedelta(seconds=1)))
        self.assertEqual(self.client.get("/api/jobs").status_code, 401)
        self.login()
        with self.engine.begin() as connection:
            connection.execute(self.metadata.tables["users"].update().where(self.metadata.tables["users"].c.id == 2).values(is_active=0))
        self.assertEqual(self.client.get("/api/auth/me").status_code, 401)

    def test_cross_origin_write_rejected(self):
        self.assertEqual(self.client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_public_intake_and_authenticated_email_check(self):
        payload = {"customer_name": "Visitor", "email": "visitor@example.com", "company": "Company",
                   "service": "Not sure yet", "project_details": "Prototype description"}
        self.assertEqual(self.client.post("/api/inquiries", json=payload).status_code, 201)
        self.assertEqual(self.client.post("/api/inquiry", json=payload).status_code, 401)
        self.login()
        self.assertEqual(self.client.post("/api/inquiry", json=payload).status_code, 400)


if __name__ == "__main__":
    unittest.main()
