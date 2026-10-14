"""Read-only checks for the verified SQLite backup and empty MySQL destination.

No DDL, INSERT, UPDATE, DELETE, credential files, or application changes.
This is a preflight, not an importer or a cutover tool.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from getpass import getpass
import hashlib
from itertools import combinations
from pathlib import Path
import re
import sqlite3
from uuid import UUID

ADMIN_EMAIL = "eahiett42@tntech.edu"
SERVICE_MAP = {
    "Digital & Industrial Design": "design",
    "Not sure yet": "other",
    "Electronics Design & Development": "electronics",
    "Software Development": "software",
    # The combined label does not identify printing versus CNC.
    "Additive & Subtractive Manufacturing": "other",
}
TABLES = ("users", "jobs", "sessions")
TRIGGERS = {
    "jobs_before_insert", "jobs_before_update", "jobs_before_delete",
    "milestones_before_insert", "milestones_before_update",
    "milestones_before_delete", "jobs_after_insert", "jobs_after_update",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def utc_datetime(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    require(result.tzinfo is None, "Source timestamp requires timezone review")
    # Deployed main.py explicitly wrote naive UTC timestamps.
    return result


def optional_date(value: str | None) -> datetime | None:
    return datetime.combine(date.fromisoformat(value), datetime.min.time()) if value else None


def validate_source(users: list[dict], jobs: list[dict]) -> dict:
    emails = set()
    for user in users:
        email = user["email"]
        require(isinstance(email, str) and email == email.strip().lower(),
                "Source email normalization requires review")
        require(email not in emails, "Duplicate source account email")
        require(0 < len(email) <= 254, "Source account email length invalid")
        emails.add(email)
        require(user["is_admin"] == 0, "Source administrator mapping requires review")
        require(re.fullmatch(r"\$2[aby]\$\d{2}\$[./A-Za-z0-9]{53}", user["hashed_password"]) is not None,
                "Source password hash is not the expected bcrypt format")
        for key in ("first_name", "last_name"):
            require(isinstance(user[key], str) and 0 < len(user[key]) <= 120,
                    "Source account name invalid")
    ids = set()
    mapped = []
    for job in jobs:
        require(str(UUID(job["id"])) == job["id"], "Source job ID is not a canonical UUID")
        require(job["id"] not in ids, "Duplicate source job UUID")
        ids.add(job["id"])
        require(job["customer_email"] in emails, "Source job has no matching customer")
        require(job["status"] == "Pending", "Non-Pending job needs an explicit historical mapping")
        require(job["service"] in SERVICE_MAP, "Unrecognized source service needs mapping review")
        for key, limit in (("customer_name", 120), ("email", 254), ("company", 120),
                           ("service", 100), ("budget", 80)):
            require(isinstance(job[key], str) and len(job[key]) <= limit,
                    "Source job text length/type invalid: " + key)
        require(isinstance(job["project_details"], str), "Source description is not text")
        require(len(job["project_details"].encode("utf-8")) <= 65535,
                "Source description exceeds MySQL TEXT capacity")
        mapped.append({
            "legacy_id": job["id"], "service_type": SERVICE_MAP[job["service"]],
            "service_label": job["service"], "budget_text": job["budget"],
            "status": "intake", "progress_percentage": 0,
            "created_at": utc_datetime(job["created_at"]),
            "target_completion_at": optional_date(job["estimated_completion_date"]),
            "estimated_ship_at": optional_date(job["estimated_shipping_date"]),
        })
    return {"emails": sorted(emails), "mapped_jobs": mapped}


def read_backup(path: Path) -> tuple[list[dict], list[dict], int, str]:
    require(path.is_file(), "Backup file does not exist")
    with path.open("rb") as stream:
        header = stream.read(20)
        require(header[:16] == b"SQLite format 3\x00" and header[18:20] == b"\x01\x01",
                "Expected a rollback-journal SQLite backup; stop for review")
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        require([row[0] for row in db.execute("PRAGMA integrity_check")] == ["ok"],
                "Backup integrity check failed")
        names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
                 if not row[0].startswith("sqlite_")}
        require(names == set(TABLES), "Unexpected SQLite tables; stop for review")
        require(not db.execute("PRAGMA foreign_key_check").fetchall(), "Source foreign-key violations")
        users = [dict(row) for row in db.execute("SELECT * FROM users ORDER BY email")]
        jobs = [dict(row) for row in db.execute("SELECT * FROM jobs ORDER BY id")]
        sessions = db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        db.close()
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return users, jobs, sessions, digest


def check_mysql(db, source: dict) -> None:
    with db.cursor() as cursor:
        cursor.execute("SELECT @@character_set_database, @@collation_database")
        require(cursor.fetchone() == ("utf8mb4", "utf8mb4_0900_ai_ci"),
                "Target database character set or collation differs")
        cursor.execute("SELECT id, email, role, is_active FROM users")
        rows = cursor.fetchall()
        require(len(rows) == 1 and rows[0][1:] == (ADMIN_EMAIL, "admin", 1),
                "Destination must contain only the expected active administrator")
        for table in ("jobs", "inquiries", "job_milestones", "user_sessions", "job_attachments"):
            cursor.execute("SELECT COUNT(*) FROM `" + table + "`")
            require(cursor.fetchone()[0] == 0, "Destination is no longer empty: " + table)
        for table in ("jobs", "inquiries"):
            cursor.execute("SHOW COLUMNS FROM `" + table + "`")
            require({"service_label", "budget_text"} <= {row[0] for row in cursor.fetchall()},
                    "Compatibility columns missing: " + table)
        cursor.execute("SELECT TRIGGER_NAME FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE()")
        require(TRIGGERS == {row[0] for row in cursor.fetchall()}, "Target trigger inventory differs")
        # Use the real MySQL collation: Python lowercase checks do not detect
        # accent-insensitive or other database-specific equality collisions.
        for left, right in combinations(source["emails"] + [ADMIN_EMAIL], 2):
            cursor.execute(
                "SELECT CONVERT(%s USING utf8mb4) COLLATE utf8mb4_0900_ai_ci = "
                "CONVERT(%s USING utf8mb4) COLLATE utf8mb4_0900_ai_ci",
                (left, right),
            )
            require(cursor.fetchone()[0] == 0, "Account emails collide under the target MySQL collation")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    require(args.source.parent == Path("/var/backups/swollenhippo") and
            args.source.name.startswith("sqlite-before-mysql-"),
            "Use the verified backup path, not the live application database")
    users, jobs, sessions, digest = read_backup(args.source)
    source = validate_source(users, jobs)
    print("Backup integrity: ok")
    print("Backup SHA256:", digest)
    print("Source counts:", {"users": len(users), "jobs": len(jobs), "sessions": sessions})
    print("Password hashes: bcrypt; will be preserved without rehashing")
    socket = next((str(path) for path in (Path("/run/mysqld/mysqld.sock"),
                  Path("/var/run/mysqld/mysqld.sock")) if path.is_socket()), None)
    require(socket is not None, "MySQL socket not found")
    import pymysql
    db = pymysql.connect(unix_socket=socket, user="root", password=getpass("MySQL root password: "),
                         database="swollenhippo_db", charset="utf8mb4", autocommit=False)
    try:
        with db.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        db.begin()
        check_mysql(db, source)
    finally:
        db.rollback()
        db.close()
    print("Target: expected administrator, empty destination, compatibility columns and eight triggers verified")
    print("Account collision check: passed using actual MySQL collation")
    for job in source["mapped_jobs"]:
        print("Job mapping:", job["legacy_id"], job["service_type"], "intake", "0%")
    print("PASS: preflight only. No records imported and no application settings changed.")
    print("Final cutover still requires a fresh backup after application writes are stopped.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, sqlite3.Error) as error:
        raise SystemExit("STOP: " + str(error))
