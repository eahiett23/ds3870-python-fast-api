"""Prepare /etc/swollenhippo.env without restarting or editing services.

Run as root. Refuses to overwrite an existing environment file, verifies the
restricted database login, and writes credentials into a root-only file.
"""
from getpass import getpass
import json
import os
from pathlib import Path

import pymysql
from sqlalchemy.engine import URL


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this configuration preparation script with sudo")
    target = Path("/etc/swollenhippo.env")
    if target.exists() or target.is_symlink():
        raise SystemExit("/etc/swollenhippo.env already exists. Stop for review; it was not changed.")
    socket = next((str(path) for path in (Path("/run/mysqld/mysqld.sock"), Path("/var/run/mysqld/mysqld.sock"))
                   if path.is_socket()), None)
    if socket is None:
        raise SystemExit("MySQL socket not found")
    password = getpass("Existing hippo_api DATABASE password: ")
    connection = pymysql.connect(unix_socket=socket, user="hippo_api", password=password,
                                 database="swollenhippo_db", charset="utf8mb4", autocommit=False)
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
        connection.begin()
        with connection.cursor() as cursor:
            cursor.execute("SELECT CURRENT_USER(), DATABASE()")
            if cursor.fetchone() != ("hippo_api@localhost", "swollenhippo_db"):
                raise RuntimeError("Unexpected database identity; nothing written")
    finally:
        connection.rollback()
        connection.close()
    url = URL.create("mysql+pymysql", username="hippo_api", password=password,
                     database="swollenhippo_db", query={"unix_socket": socket, "charset": "utf8mb4"})
    values = {
        "MYSQL_DATABASE_URL": url.render_as_string(hide_password=False),
        "APP_ENV": "production", "COOKIE_SECURE": "true",
        "APP_DATA_DIR": "/var/lib/swollenhippo",
        "APP_TEMPLATE_PATH": "/opt/swollenhippo/templates/index.html",
    }
    # EnvironmentFile accepts double-quoted values. URL rendering encodes password
    # punctuation; JSON quotes/backslash escaping protects the remaining values.
    content = "".join(key + "=" + json.dumps(value) + "\n" for key, value in values.items())
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())
    print("Verified hippo_api login and created /etc/swollenhippo.env with root-only permissions.")
    print("No service restarted and no database records changed. Keep file contents private.")


if __name__ == "__main__":
    main()
