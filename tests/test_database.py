"""Exercise database creation through the application's actual lifespan."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError

from database import tbl_inquiries, tbl_users
from main import Inquiry, app


class DatabaseStartupTests(unittest.TestCase):
    def test_startup_adds_inquiries_to_existing_database_and_preserves_records(self):
        with tempfile.TemporaryDirectory() as str_directory:
            str_url = "sqlite:///" + (Path(str_directory) / "test.db").as_posix()
            obj_engine = create_engine(str_url)
            try:
                tbl_users.create(obj_engine)
            finally:
                obj_engine.dispose()
            obj_inquiry = Inquiry(customer_name="Test Customer", email="test@example.com",
                                  company="Test Company", service="Prototyping",
                                  project_details="Build a prototype for testing.")
            dict_inquiry = obj_inquiry.model_dump(mode="json", exclude_unset=True)
            with patch.dict(os.environ, {"CONNECTIONSTRING": str_url}):
                with TestClient(app):
                    obj_engine = app.state.obj_engine
                    obj_inspector = inspect(obj_engine)
                    self.assertEqual(set(obj_inspector.get_table_names()), {"users", "inquiries", "jobs"})
                    self.assertEqual(obj_inspector.get_pk_constraint("inquiries")["constrained_columns"], ["id"])
                    dict_foreign_key = obj_inspector.get_foreign_keys("jobs")[0]
                    self.assertEqual(dict_foreign_key["constrained_columns"], ["inquiry_id"])
                    self.assertEqual(dict_foreign_key["referred_table"], "inquiries")
                    self.assertEqual(dict_foreign_key["referred_columns"], ["id"])
                    lst_columns = obj_inspector.get_columns("inquiries")
                    self.assertEqual({obj_column["name"] for obj_column in lst_columns},
                                     set(Inquiry.model_fields) | {"id"})
                    self.assertTrue(all(not obj_column["nullable"] for obj_column in lst_columns))
                    dict_lengths = {obj_column["name"]: obj_column["type"].length for obj_column in lst_columns}
                    self.assertEqual(dict_lengths, {"id": 36, "customer_name": 120, "email": 254,
                                                    "company": 120, "service": 100,
                                                    "project_details": 4000, "budget": 80})
                    with obj_engine.begin() as obj_connection:
                        # Repeat emails are allowed; each inquiry gets its own identifier.
                        obj_connection.execute(tbl_inquiries.insert().values(**dict_inquiry))
                        obj_connection.execute(tbl_inquiries.insert().values(**dict_inquiry))
                    with self.assertRaises(IntegrityError):
                        with obj_engine.begin() as obj_connection:
                            obj_connection.execute(tbl_inquiries.insert().values(
                                **{**dict_inquiry, "project_details": None}))
                with TestClient(app):
                    with app.state.obj_engine.connect() as obj_connection:
                        lst_inquiries = obj_connection.execute(select(tbl_inquiries)).mappings().all()
                    self.assertEqual(len(lst_inquiries), 2)
                    self.assertNotEqual(lst_inquiries[0]["id"], lst_inquiries[1]["id"])
                    for dict_record in lst_inquiries:
                        self.assertEqual({str_key: dict_record[str_key] for str_key in Inquiry.model_fields},
                                         obj_inquiry.model_dump(mode="json"))

    def test_startup_creates_schema_and_preserves_users_on_restart(self):
        with tempfile.TemporaryDirectory() as str_directory:
            str_url = "sqlite:///" + (Path(str_directory) / "test.db").as_posix()
            with patch.dict(os.environ, {"CONNECTIONSTRING": str_url}):
                with TestClient(app) as obj_client:
                    obj_engine = app.state.obj_engine
                    obj_inspector = inspect(obj_engine)
                    self.assertEqual(obj_inspector.get_pk_constraint("users")["constrained_columns"], ["email"])
                    lst_columns = obj_inspector.get_columns("users")
                    self.assertEqual({obj_column["name"] for obj_column in lst_columns},
                                     {"email", "first_name", "last_name", "is_admin", "hashed_password"})
                    self.assertTrue(all(not obj_column["nullable"] for obj_column in lst_columns))
                    dict_user = {"email": "test@example.com", "first_name": "Test",
                                 "last_name": "User", "hashed_password": "test-only-hash"}
                    with obj_engine.begin() as obj_connection:
                        obj_connection.execute(tbl_users.insert().values(**dict_user))
                    with self.assertRaises(IntegrityError):
                        with obj_engine.begin() as obj_connection:
                            obj_connection.execute(tbl_users.insert().values(**dict_user))
                    with self.assertRaises(IntegrityError):
                        with obj_engine.begin() as obj_connection:
                            obj_connection.execute(tbl_users.insert().values(
                                **{**dict_user, "email": "missing@example.com", "hashed_password": None}))
                    self.assertEqual(obj_client.get("/").status_code, 200)
                    self.assertEqual(obj_client.get("/api/jobs").status_code, 200)
                    self.assertEqual(obj_client.get("/api/jobs?role=admin").status_code, 403)
                with TestClient(app):
                    with app.state.obj_engine.connect() as obj_connection:
                        lst_users = obj_connection.execute(select(tbl_users)).mappings().all()
                    self.assertEqual(len(lst_users), 1)
                    self.assertEqual(lst_users[0]["email"], dict_user["email"])
                    self.assertEqual(lst_users[0]["hashed_password"], dict_user["hashed_password"])
                    self.assertFalse(lst_users[0]["is_admin"])

    def test_missing_connection_string_fails_startup(self):
        with patch.dict(os.environ, {"CONNECTIONSTRING": ""}):
            with self.assertRaisesRegex(RuntimeError, "CONNECTIONSTRING must be set"):
                with TestClient(app):
                    pass


if __name__ == "__main__":
    unittest.main()
