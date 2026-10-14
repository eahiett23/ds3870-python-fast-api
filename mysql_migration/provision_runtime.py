"""Create the local hippo_api MySQL account with bounded runtime privileges.

Passwords are requested through the terminal. Does not write an environment file
or alter the existing service. Refuses to overwrite any existing hippo_api account.
"""
from getpass import getpass
from pathlib import Path
import pymysql


def main():
    socket = next((str(path) for path in (Path("/run/mysqld/mysqld.sock"), Path("/var/run/mysqld/mysqld.sock"))
                   if path.is_socket()), None)
    if socket is None:
        raise SystemExit("MySQL socket not found")
    root_password = getpass("MySQL root password: ")
    password = getpass("New hippo_api DATABASE password (different from your website password): ")
    confirmation = getpass("Confirm database password: ")
    if password != confirmation or len(password) < 16:
        raise SystemExit("Passwords must match and have at least 16 characters. Nothing created.")
    db = pymysql.connect(unix_socket=socket, user="root", password=root_password, charset="utf8mb4", autocommit=True)
    try:
        with db.cursor() as cursor:
            cursor.execute("SELECT Host FROM mysql.user WHERE User='hippo_api'")
            if cursor.fetchall():
                raise SystemExit("hippo_api already exists. Stop for a grant review; no account changes made.")
            cursor.execute("CREATE USER 'hippo_api'@'localhost' IDENTIFIED BY %s WITH MAX_USER_CONNECTIONS 8", (password,))
            # Signup cannot assign role/is_active or update user credentials/roles.
            cursor.execute("GRANT SELECT ON swollenhippo_db.users TO 'hippo_api'@'localhost'")
            cursor.execute("GRANT INSERT (email, password_hash, first_name, last_name) ON swollenhippo_db.users TO 'hippo_api'@'localhost'")
            cursor.execute("GRANT SELECT, INSERT, DELETE ON swollenhippo_db.user_sessions TO 'hippo_api'@'localhost'")
            for table in ("inquiries", "jobs", "job_attachments"):
                cursor.execute("GRANT SELECT, INSERT, UPDATE ON swollenhippo_db." + table + " TO 'hippo_api'@'localhost'")
            cursor.execute("GRANT SELECT, INSERT ON swollenhippo_db.job_milestones TO 'hippo_api'@'localhost'")
            cursor.execute("GRANT EXECUTE ON PROCEDURE swollenhippo_db.production_schema_ready TO 'hippo_api'@'localhost'")
            cursor.execute("SHOW GRANTS FOR 'hippo_api'@'localhost'")
            for row in cursor.fetchall():
                print(row[0])
        print("Runtime account provisioned. Application/service settings are unchanged.")
    except Exception:
        print("STOP: MySQL account/grant DDL commits immediately. Inspect existing grants before retrying.")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
