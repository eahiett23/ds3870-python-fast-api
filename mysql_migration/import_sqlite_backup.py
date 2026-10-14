"""Atomic import of a final SQLite backup into the prepared MySQL destination.

Requires swollenhippo.service to be inactive. Refuses nonempty targets except
for Ellis's expected administrator. Do not run until cutover instructions say so.
No schema changes or source changes; imported data/audit writes are transactional.
"""
import argparse
from getpass import getpass
from pathlib import Path
import subprocess
from uuid import UUID

import pymysql
if __package__:
    from .migration_preflight import ADMIN_EMAIL, check_mysql, read_backup, require, validate_source
else:
    from migration_preflight import ADMIN_EMAIL, check_mysql, read_backup, require, validate_source


def job_values(original, mapped, customer_id, admin_id):
    return {
        "job_number": UUID(original["id"]).hex, "legacy_id": original["id"],
        "customer_id": customer_id, "title": original["customer_name"] + " prototype",
        "description": original["project_details"], "service_type": mapped["service_type"],
        "service_label": original["service"], "budget_text": original["budget"],
        "contact_name": original["customer_name"], "contact_email": original["email"],
        "company_name": original["company"], "status": "intake", "progress_percentage": 0,
        "created_at": mapped["created_at"], "target_completion_at": mapped["target_completion_at"],
        "estimated_ship_at": mapped["estimated_ship_at"], "updated_by_admin_id": admin_id,
    }


def insert_row(cursor, table, values):
    # All identifiers originate from fixed application dictionaries, never input.
    names = list(values)
    sql = "INSERT INTO `" + table + "` (" + ",".join("`" + name + "`" for name in names) + ") VALUES ("
    cursor.execute(sql + ",".join(["%s"] * len(names)) + ")", tuple(values[name] for name in names))
    return cursor.lastrowid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    require(args.source.parent == Path("/var/backups/swollenhippo") and
            args.source.name.startswith("sqlite-before-mysql-"), "Use a verified final backup path")
    result = subprocess.run(["systemctl", "is-active", "swollenhippo.service"], capture_output=True, text=True, check=False)
    require(result.stdout.strip() == "inactive", "swollenhippo.service must be stopped before final import")
    users, jobs, sessions, digest = read_backup(args.source)
    source = validate_source(users, jobs)
    print("Final backup integrity: ok; SHA256:", digest)
    print("Import source:", {"users": len(users), "jobs": len(jobs), "sessions_to_invalidate": sessions})
    socket = next((str(path) for path in (Path("/run/mysqld/mysqld.sock"), Path("/var/run/mysqld/mysqld.sock"))
                   if path.is_socket()), None)
    require(socket is not None, "MySQL socket not found")
    db = pymysql.connect(unix_socket=socket, user="root", password=getpass("MySQL root password: "),
                         database="swollenhippo_db", charset="utf8mb4", autocommit=False)
    commit_started = False
    try:
        db.begin()
        check_mysql(db, source)
        with db.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute("SELECT id FROM users WHERE email=%s AND role='admin' AND is_active=1", (ADMIN_EMAIL,))
            admin_id = cursor.fetchone()[0]
            cursor.execute("SET @app_actor_id=%s", (admin_id,))
            customer_ids = {}
            for user in users:
                values = dict(email=user["email"], first_name=user["first_name"], last_name=user["last_name"],
                              password_hash=user["hashed_password"], role="customer", is_active=1)
                identifier = insert_row(cursor, "users", values)
                customer_ids[user["email"]] = identifier
                cursor.execute("SELECT email,first_name,last_name,password_hash,role,is_active FROM users WHERE id=%s", (identifier,))
                require(cursor.fetchone() == tuple(values[name] for name in ("email", "first_name", "last_name", "password_hash", "role", "is_active")),
                        "Imported account verification failed; transaction will roll back")
            for original, mapped in zip(jobs, source["mapped_jobs"]):
                values = job_values(original, mapped, customer_ids[original["customer_email"]], admin_id)
                identifier = insert_row(cursor, "jobs", values)
                cursor.execute("SELECT " + ",".join("`" + key + "`" for key in values) + " FROM jobs WHERE id=%s", (identifier,))
                require(cursor.fetchone() == tuple(values.values()), "Imported job verification failed; transaction will roll back")
                cursor.execute("SELECT admin_id,stage,progress_percentage,note,event_type FROM job_milestones WHERE job_id=%s", (identifier,))
                records = cursor.fetchall()
                require(len(records) == 1 and records[0][:3] == (admin_id, "intake", 0) and
                        original["id"] in records[0][3] and "imported from SQLite" in records[0][3] and records[0][4] == "created",
                        "Import audit verification failed; transaction will roll back")
            for table, count in (("users", len(users) + 1), ("jobs", len(jobs)), ("job_milestones", len(jobs)),
                                 ("inquiries", 0), ("user_sessions", 0), ("job_attachments", 0)):
                cursor.execute("SELECT COUNT(*) FROM `" + table + "`")
                require(cursor.fetchone()[0] == count, "Unexpected target count; transaction will roll back: " + table)
        commit_started = True
        db.commit()
        print("COMMITTED: customer accounts, jobs and import audit records verified.")
        print("Totals:", {"users": len(users) + 1, "jobs": len(jobs), "job_milestones": len(jobs), "user_sessions": 0})
        print("Original bcrypt hashes, UUIDs, contacts, budget text, created times and estimates preserved.")
        print("SQLite source unchanged. Website service remains stopped; continue controlled cutover.")
    except Exception:
        try:
            db.rollback()
        finally:
            if commit_started:
                print("STOP: inspect target records before retrying; the commit may have succeeded.")
            else:
                print("STOP: import failed before commit. Verify target counts before retrying.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
