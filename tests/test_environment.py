"""Verify optional environment loading before database startup."""

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class EnvironmentLoadingTests(unittest.TestCase):
    def test_optional_dotenv_and_existing_environment_precedence(self):
        str_source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
        for bool_file_exists, bool_existing_value in [(True, False), (True, True), (False, True)]:
            with self.subTest(file_exists=bool_file_exists, existing_value=bool_existing_value):
                with tempfile.TemporaryDirectory() as str_directory:
                    obj_main_path = Path(str_directory) / "main.py"
                    obj_main_path.write_text(str_source, encoding="utf-8")
                    if bool_file_exists:
                        (Path(str_directory) / ".env").write_text(
                            'CONNECTIONSTRING="sqlite:///:memory:"\nSTR_TEST_SETTING="from file"\n',
                            encoding="utf-8",
                        )
                    with patch.dict(os.environ):
                        os.environ.pop("CONNECTIONSTRING", None)
                        os.environ.pop("STR_TEST_SETTING", None)
                        os.environ.pop("PYTHON_DOTENV_DISABLED", None)
                        if bool_existing_value:
                            os.environ["CONNECTIONSTRING"] = "sqlite://"
                        # Execute a temporary copy to avoid touching the developer's .env.
                        dict_module = runpy.run_path(str(obj_main_path))
                        self.assertEqual(os.environ["CONNECTIONSTRING"],
                                         "sqlite://" if bool_existing_value else "sqlite:///:memory:")
                        self.assertEqual(os.environ.get("STR_TEST_SETTING"),
                                         "from file" if bool_file_exists else None)
                        with TestClient(dict_module["app"]) as obj_client:
                            self.assertEqual(obj_client.get("/api/jobs").status_code, 200)
