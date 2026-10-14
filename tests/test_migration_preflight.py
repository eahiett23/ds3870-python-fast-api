import unittest
from datetime import datetime
from mysql_migration.migration_preflight import validate_source
from mysql_migration.import_sqlite_backup import job_values


class SourceMappingTests(unittest.TestCase):
    def setUp(self):
        self.users = [{"email": "customer@example.com", "first_name": "Test", "last_name": "Customer",
                       "is_admin": 0, "hashed_password": "$2b$12$" + "a" * 53}]
        self.jobs = [{"id": "12345678-1234-4234-8234-123456789abc",
                      "customer_email": "customer@example.com", "customer_name": "Different Contact",
                      "email": "contact@example.com", "company": "Company", "service": "Digital & Industrial Design",
                      "budget": "$2,500–$10,000", "project_details": "Build a prototype", "status": "Pending",
                      "created_at": "2026-10-13 01:02:03.123456", "estimated_completion_date": "2026-11-01",
                      "estimated_shipping_date": None}]

    def test_preserves_uuid_budget_service_and_dates(self):
        job = validate_source(self.users, self.jobs)["mapped_jobs"][0]
        self.assertEqual(job["legacy_id"], self.jobs[0]["id"])
        self.assertEqual(job["budget_text"], "$2,500–$10,000")
        self.assertEqual(job["service_label"], self.jobs[0]["service"])
        self.assertEqual(job["service_type"], "design")
        self.assertEqual(job["created_at"], datetime(2026, 10, 13, 1, 2, 3, 123456))
        self.assertEqual(job["target_completion_at"], datetime(2026, 11, 1))
        self.assertIsNone(job["estimated_ship_at"])

    def test_does_not_guess_manufacturing_process(self):
        self.jobs[0]["service"] = "Additive & Subtractive Manufacturing"
        self.assertEqual(validate_source(self.users, self.jobs)["mapped_jobs"][0]["service_type"], "other")

    def test_import_keeps_contact_separate_from_owner_and_no_invented_actual_dates(self):
        mapping = validate_source(self.users, self.jobs)["mapped_jobs"][0]
        values = job_values(self.jobs[0], mapping, customer_id=7, admin_id=1)
        self.assertEqual(values["customer_id"], 7)
        self.assertEqual(values["contact_email"], "contact@example.com")
        self.assertEqual(values["contact_name"], "Different Contact")
        self.assertEqual(values["budget_text"], "$2,500–$10,000")
        self.assertNotIn("actual_ship_at", values)
        self.assertNotIn("actual_completion_at", values)
        self.assertNotIn("inquiry_id", values)

    def test_unknown_service_stops(self):
        self.jobs[0]["service"] = "Unknown"
        with self.assertRaises(ValueError): validate_source(self.users, self.jobs)

    def test_missing_customer_stops(self):
        self.jobs[0]["customer_email"] = "orphan@example.com"
        with self.assertRaises(ValueError): validate_source(self.users, self.jobs)

    def test_non_pending_stops_instead_of_inventing_history(self):
        self.jobs[0]["status"] = "Completed"
        with self.assertRaises(ValueError): validate_source(self.users, self.jobs)

    def test_invalid_hash_stops(self):
        self.users[0]["hashed_password"] = "plaintext"
        with self.assertRaises(ValueError): validate_source(self.users, self.jobs)

    def test_duplicate_account_stops(self):
        with self.assertRaises(ValueError): validate_source(self.users * 2, self.jobs)

    def test_timestamp_timezone_requires_review(self):
        self.jobs[0]["created_at"] += "+01:00"
        with self.assertRaises(ValueError): validate_source(self.users, self.jobs)


if __name__ == "__main__":
    unittest.main()
