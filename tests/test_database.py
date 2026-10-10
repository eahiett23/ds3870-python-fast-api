"""Exercise database creation through the application's actual lifespan."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from database import tbl_users
from main import app


class DatabaseStartupTests(unittest.TestCase):
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
