"""Test real MySQL runtime permissions and audit triggers, then roll back.

Run beside mysql_portal.py with the deployed virtual environment. Never starts
an HTTP server or changes service files. Temporary inserts may consume AUTO_INCREMENT
values even though every application-data change is rolled back.
"""
from datetime import timedelta
from getpass import getpass
import hashlib
import os
from pathlib import Path
from uuid import uuid4

import bcrypt
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import URL
from sqlalchemy.exc import DBAPIError
import sys

# Support both a cloned repository and the original uploaded sibling files.
obj_backend_directory = Path(__file__).resolve().parents[1]
if (obj_backend_directory / 'mysql_portal.py').is_file():
    sys.path.insert(0, str(obj_backend_directory))
import mysql_portal as portal


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def denied(connection, statement, codes, label):
    try:
        connection.execute(statement)
    except DBAPIError as error:
        code = error.orig.args[0] if error.orig.args else None
        if code not in codes:
            raise RuntimeError(label + ": unexpected database error code " + str(code)) from error
        print("PASS:", label)
    else:
        raise RuntimeError(label + ": operation unexpectedly succeeded")


def main():
    socket = next((str(path) for path in (Path("/run/mysqld/mysqld.sock"), Path("/var/run/mysqld/mysqld.sock"))
                   if path.is_socket()), None)
    require(socket is not None, "MySQL socket not found")
    password = getpass("hippo_api DATABASE password: ")
    url = URL.create("mysql+pymysql", username="hippo_api", password=password,
                     database="swollenhippo_db", query={"unix_socket": socket, "charset": "utf8mb4"})
    previous = os.environ.get("MYSQL_DATABASE_URL")
    os.environ["MYSQL_DATABASE_URL"] = url.render_as_string(hide_password=False)
    engine = None
    try:
        engine, tables = portal.initialize_database()
        print("PASS: candidate backend startup, schema reflection and readiness procedure")
        users, jobs, logs = tables["users"], tables["jobs"], tables["job_milestones"]
        sessions = tables["user_sessions"]
        identifier = uuid4().hex
        email = "mysql-smoke-" + identifier + "@example.invalid"
        number = identifier
        digest = hashlib.sha256(identifier.encode()).digest()
        password_hash = bcrypt.hashpw(b"temporary-smoke-password", bcrypt.gensalt(rounds=12)).decode()
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                actor = connection.execute(select(users.c.id).where(users.c.email == "eahiett42@tntech.edu",
                                            users.c.role == "admin", users.c.is_active == 1)).scalar_one()
                customer = connection.execute(insert(users).values(email=email, password_hash=password_hash,
                                              first_name="Temporary", last_name="Smoke Test")).inserted_primary_key[0]
                row = connection.execute(select(users).where(users.c.id == customer)).mappings().one()
                require(row["role"] == "customer" and row["is_active"] == 1, "Signup defaults differ")
                print("PASS: signup column grants create an active customer")
                denied(connection, insert(users).values(email="admin-" + email, password_hash=password_hash,
                       first_name="Temporary", last_name="Smoke Test", role="admin"), {1142, 1143},
                       "runtime cannot choose an administrator role at signup")
                denied(connection, update(users).where(users.c.id == customer).values(role="admin"), {1142, 1143},
                       "runtime cannot promote a customer")
                timestamp = portal.now()
                connection.execute(insert(sessions).values(user_id=customer, token_digest=digest,
                                   created_at=timestamp, expires_at=timestamp + timedelta(hours=8)))
                require(connection.execute(select(sessions.c.user_id).where(sessions.c.token_digest == digest)).scalar_one() == customer,
                        "Session digest storage failed")
                connection.execute(delete(sessions).where(sessions.c.token_digest == digest))
                print("PASS: session digest storage and logout deletion")
                job_values = dict(job_number=number, customer_id=customer, title="Temporary MySQL smoke test",
                                  description="Rollback-only permission and audit verification", service_type="other",
                                  service_label="Not sure yet", budget_text="Need guidance", updated_by_admin_id=actor)
                connection.exec_driver_sql("SET @app_actor_id = %s", (customer,))
                denied(connection, insert(jobs).values(**job_values), {1644}, "customer actor cannot create a job")
                connection.exec_driver_sql("SET @app_actor_id = %s", (actor,))
                job_id = connection.execute(insert(jobs).values(**job_values)).inserted_primary_key[0]
                history = connection.execute(select(logs).where(logs.c.job_id == job_id)).mappings().all()
                require(len(history) == 1 and history[0]["admin_id"] == actor and history[0]["event_type"] == "created",
                        "Job creation audit trigger did not append the expected record")
                print("PASS: administrator job creation appends its audit record")
                denied(connection, update(jobs).where(jobs.c.id == job_id).values(progress_percentage=10,
                       updated_by_admin_id=actor), {1644}, "job edits must increment the version")
                connection.exec_driver_sql("SET @app_actor_id = %s", (customer,))
                denied(connection, update(jobs).where(jobs.c.id == job_id).values(status="shipped", progress_percentage=90,
                       actual_ship_at=timestamp, version=2, updated_by_admin_id=customer), {1644},
                       "customer actor cannot change progress, stage or shipping")
                denied(connection, insert(logs).values(job_id=job_id, admin_id=customer, stage="intake", progress_percentage=0,
                       note="Must be refused", event_type="note"), {1644}, "customer actor cannot append a milestone")
                connection.exec_driver_sql("SET @app_actor_id = %s", (actor,))
                connection.execute(update(jobs).where(jobs.c.id == job_id).values(status="in_production", progress_percentage=10,
                                   version=2, updated_by_admin_id=actor))
                history = connection.execute(select(logs).where(logs.c.job_id == job_id).order_by(logs.c.id)).mappings().all()
                require(len(history) == 2 and history[-1]["progress_percentage"] == 10 and history[-1]["stage"] == "in_production",
                        "Administrator update audit trigger did not append the expected snapshot")
                print("PASS: administrator update appends a progress snapshot")
                denied(connection, update(logs).where(logs.c.job_id == job_id).values(note="Must be refused"),
                       {1142, 1143, 1644}, "runtime cannot edit audit history")
                denied(connection, delete(logs).where(logs.c.job_id == job_id), {1142, 1644}, "runtime cannot delete audit history")
                denied(connection, delete(jobs).where(jobs.c.id == job_id), {1142, 1644}, "runtime cannot delete jobs")
            finally:
                transaction.rollback()
                print("Temporary application-data changes rolled back")
        with engine.connect() as connection:
            require(connection.execute(select(users.c.id).where(users.c.email == email)).first() is None,
                    "Temporary customer remains after rollback")
            require(connection.execute(select(jobs.c.id).where(jobs.c.job_number == number)).first() is None,
                    "Temporary job remains after rollback")
            require(connection.execute(select(sessions.c.id).where(sessions.c.token_digest == digest)).first() is None,
                    "Temporary session remains after rollback")
            require(connection.exec_driver_sql("SELECT @app_actor_id").scalar_one() is None,
                    "Database actor context did not clear on connection checkout")
        print("PASS: no temporary customer, job or session remains; pooled actor context cleared")
        print("PASS: MySQL smoke test complete. Website and service configuration are unchanged.")
    finally:
        if engine is not None:
            engine.dispose()
        if previous is None:
            os.environ.pop("MYSQL_DATABASE_URL", None)
        else:
            os.environ["MYSQL_DATABASE_URL"] = previous


if __name__ == "__main__":
    main()
