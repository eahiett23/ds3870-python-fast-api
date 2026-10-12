# Debian deployment README

These instructions install MySQL and connect the existing FastAPI application to its production schema. Run the command blocks **in order**, in the same Bash terminal, and continue only when each block succeeds.

Do not paste the entire document at once: installation and password prompts require responses. The first block enables Bash error handling so failed commands stop the session instead of allowing later steps to continue. If a command fails and closes the shell, reconnect, investigate the error, and resume the appropriate step; do not restart schema installation blindly.

Prerequisites:

- A fresh Debian 12 (bookworm) or Debian 13 (trixie) server with internet access and a user with `sudo` access. Confirm the repository offers MySQL 8.4 for your release and architecture.
- The updated `ds3870-python-fast-api` project copied or cloned onto the Debian server, including `production/`, `templates/` and `tests/`.
- No existing MySQL/MariaDB installation to replace, and no existing `swollenhippo_db` or `hippo_api` account. These commands are for a fresh installation, not an upgrade or migration.

Windows paths do not apply on Debian. Enter the Linux path of the project when prompted.

## 1. Install MySQL

In the repository configuration menu, select **MySQL 8.4 LTS**, then **OK**. Set a MySQL root password during installation and retain it for subsequent commands. The schema requires MySQL 8.0.16 or newer.

```bash
set -euo pipefail
trap 'unset HIPPO_ROOT_PASSWORD CONNECTIONSTRING' EXIT

cat /etc/os-release
dpkg --print-architecture

sudo apt-get update
sudo apt-get install -y ca-certificates curl gnupg lsb-release

mkdir -p "$HOME/mysql-install"
cd "$HOME/mysql-install"

curl --fail --location \
  https://dev.mysql.com/get/mysql-apt-config_0.8.40-1_all.deb \
  --output mysql-apt-config.deb

sudo dpkg -i mysql-apt-config.deb

sudo apt-get update
apt-cache policy mysql-server mysql-community-server
HIPPO_MYSQL_CANDIDATE="$(apt-cache policy mysql-community-server | awk '/Candidate:/ {print $2}')"
case "$HIPPO_MYSQL_CANDIDATE" in
  8.4.*|*:8.4.*) ;;
  *) printf '%s\n' 'Stopped: MySQL 8.4 is not the installation candidate. Reconfigure mysql-apt-config for your supported Debian release.' >&2; exit 1 ;;
esac
unset HIPPO_MYSQL_CANDIDATE
sudo apt-get install mysql-server

sudo systemctl enable --now mysql

mysql --version
sudo systemctl status mysql --no-pager
```

Official references: [MySQL APT installation guide](https://dev.mysql.com/doc/mysql-apt-repo-quick-guide/en/), [repository configuration downloads](https://dev.mysql.com/downloads/repo/apt/) and [Debian repository releases](https://repo.mysql.com/apt/debian/dists/). Confirm the APT candidate comes from Oracle's MySQL repository and is version 8.4 before accepting installation. If the configuration package is no longer available, use the version listed on the official download page. Do not bypass APT signature verification or select an unsupported Debian release.

## 2. Secure the installation

Enter your MySQL root password when prompted. Remove anonymous accounts, disable remote root login, remove the test database and reload privileges when asked.

```bash
sudo mysql_secure_installation
```

These instructions assume you configured root password authentication. If you selected socket-only root authentication instead, the root-password commands below need adaptation.

## 3. Open the project and install Python dependencies

Enter the full Debian project path, for example `/home/ellis/ds3870-python-fast-api`.

```bash
sudo apt-get install -y python3 python3-venv python3-pip

read -r -e -p "Full path to ds3870-python-fast-api: " HIPPO_PROJECT_DIR
cd "$HIPPO_PROJECT_DIR"

test -f production/schema.sql
test -f production/api.py
test -f requirements.txt

python3 --version
python3 -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11+ is required"'
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt "PyMySQL[rsa]"

# Subsequent commands must read the project's configuration, not inherited URLs.
unset DATABASE_MODE CONNECTIONSTRING
```

Python must be version 3.11 or newer. The verified application uses synchronous SQLAlchemy/PyMySQL; installing aiomysql alone would not convert it to an asynchronous application.

## 4. Generate the deployment schema and application configuration

This creates a root-level `schema.sql` using the verified `production/schema.sql`, changes the database name to `swollenhippo_db`, adds the `hippo_api` runtime account and generates its random database password. It also creates `.env` configured for production mode.

It refuses to overwrite an existing root-level `schema.sql` or `.env`. Preserve and review any existing configuration rather than deleting it to bypass that check.

The generated `schema.sql` contains a database password. Exclude it from Git before generating it; `.env` is already ignored by this project.

```bash
printf '\n# Generated deployment SQL contains credentials\n/schema.sql\n' >> .gitignore

python <<'PY'
from pathlib import Path
import secrets
from sqlalchemy.engine import URL

schema_path = Path("schema.sql")
env_path = Path(".env")

if schema_path.exists() or env_path.exists():
    raise SystemExit(
        "Stopped: schema.sql or .env already exists. "
        "Review and preserve your existing configuration before continuing."
    )

source = Path("production/schema.sql").read_text(encoding="utf-8")

expected_database_statement = (
    "CREATE DATABASE swollenhippo_industries "
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
)

if expected_database_statement not in source:
    raise SystemExit(
        "Stopped: production/schema.sql differs from the verified schema."
    )

schema = source.replace(
    expected_database_statement,
    "CREATE DATABASE IF NOT EXISTS swollenhippo_db "
    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;",
    1,
).replace(
    "USE swollenhippo_industries;",
    "USE swollenhippo_db;",
    1,
)

# Retain 256 bits of randomness and satisfy common MySQL MEDIUM policy classes.
password = "Hh7!" + secrets.token_hex(32)

schema += f"""
-- Role lookup index.
CREATE INDEX ix_users_role ON users (role, is_active);

-- Runtime database account for a fresh installation.
CREATE USER 'hippo_api'@'localhost'
    IDENTIFIED BY '{password}';

GRANT SELECT
    ON swollenhippo_db.users
    TO 'hippo_api'@'localhost';

GRANT SELECT, INSERT, UPDATE
    ON swollenhippo_db.user_sessions
    TO 'hippo_api'@'localhost';

GRANT SELECT, INSERT, UPDATE
    ON swollenhippo_db.inquiries
    TO 'hippo_api'@'localhost';

GRANT SELECT, INSERT, UPDATE
    ON swollenhippo_db.jobs
    TO 'hippo_api'@'localhost';

GRANT SELECT, INSERT
    ON swollenhippo_db.job_milestones
    TO 'hippo_api'@'localhost';

GRANT SELECT, UPDATE
    ON swollenhippo_db.job_attachments
    TO 'hippo_api'@'localhost';

GRANT EXECUTE
    ON PROCEDURE swollenhippo_db.production_schema_ready
    TO 'hippo_api'@'localhost';
"""

url = URL.create(
    "mysql+pymysql",
    username="hippo_api",
    password=password,
    host="localhost",
    database="swollenhippo_db",
    query={
        "charset": "utf8mb4",
        "unix_socket": "/var/run/mysqld/mysqld.sock",
    },
).render_as_string(hide_password=False)

for path, content in (
    (schema_path, schema),
    (env_path, f'DATABASE_MODE=production\nCONNECTIONSTRING="{url}"\n'),
):
    with path.open("x", encoding="utf-8") as file:
        path.chmod(0o600)
        file.write(content)

print("Created schema.sql and .env with owner-only permissions.")
print("Database password generated securely; it was not printed.")
PY
```

The schema includes all six tables needed by the verified application, including `user_sessions`, plus administrator checks and audit triggers. Table-specific grants give the runtime account the permissions required by existing routes without granting account provisioning, table creation, trigger modification or history deletion rights. The runtime connection uses the local MySQL socket so it matches the `'hippo_api'@'localhost'` account without depending on hostname resolution. If your server uses a nonstandard socket path, adjust it in both the generator above and the provisioning URL below.

## 5. Import and verify the schema

First confirm the target database and API account do not already exist. Enter the MySQL root password. A nonzero result stops the commands; inspect the existing installation rather than resetting its credentials or importing over its tables. The generated script deliberately uses CREATE USER without IF NOT EXISTS so an account collision cannot silently leave `.env` with the wrong password.

```bash
HIPPO_EXISTING="$(mysql --user=root --password --batch --skip-column-names \
  --execute="SELECT (SELECT COUNT(*) FROM information_schema.SCHEMATA WHERE SCHEMA_NAME = 'swollenhippo_db') + (SELECT COUNT(*) FROM mysql.user WHERE User = 'hippo_api');")"

if [ "$HIPPO_EXISTING" != "0" ]; then
  printf '%s\n' 'Stopped: swollenhippo_db or hippo_api already exists. Review the installation before continuing.' >&2
  exit 1
fi
unset HIPPO_EXISTING
```

Now import once. Enter the MySQL root password again. MySQL DDL implicitly commits, so a failed import can leave a partially installed schema and must be inspected before retrying.

```bash
mysql --default-character-set=utf8mb4 \
  --user=root \
  --password \
  < schema.sql
```

Verify the installation:

```bash
mysql --user=root --password swollenhippo_db <<'SQL'
SELECT VERSION();

SHOW TABLES;

CALL production_schema_ready();

SHOW GRANTS FOR 'hippo_api'@'localhost';
SQL
```

Expected tables: `users`, `user_sessions`, `inquiries`, `jobs`, `job_milestones`, `job_attachments`. The readiness procedure should report **8** installed triggers. The root account is the definer of the installed routines/triggers; retain that account and its required privileges.

Do not import `production/seed.sql` unchanged: it targets the original `swollenhippo_industries` database name. Demo data is optional and is not part of this deployment sequence.

## 6. Provision the application administrator and customer

Replace the example email addresses and names as appropriate. The first prompt requests the MySQL root password. Each provisioning command then asks for a separate application password of at least 12 characters and confirmation.

The root connection below uses the standard Debian MySQL socket path. Adjust it if your installation uses a different path.

```bash
read -r -s -p "MySQL root password: " HIPPO_ROOT_PASSWORD
printf '\n'
export HIPPO_ROOT_PASSWORD

CONNECTIONSTRING="$(
python <<'PY'
import os
from sqlalchemy.engine import URL

print(URL.create(
    "mysql+pymysql",
    username="root",
    password=os.environ["HIPPO_ROOT_PASSWORD"],
    host="localhost",
    database="swollenhippo_db",
    query={
        "charset": "utf8mb4",
        "unix_socket": "/var/run/mysqld/mysqld.sock",
        "init_command": "SET time_zone = '+00:00'",
    },
).render_as_string(hide_password=False))
PY
)"
export CONNECTIONSTRING

python -m production.provision_user \
  --email admin@swollenhippo.example \
  --role admin \
  --first-name Hippo \
  --last-name Admin

python -m production.provision_user \
  --email customer@example.test \
  --role customer \
  --first-name Alex \
  --last-name Rivera

unset HIPPO_ROOT_PASSWORD
unset CONNECTIONSTRING
```

Provisioning prints each numeric account ID. Administrators use the customer ID when converting a public inquiry into an assigned job. The command also resets credentials and role if the email already exists, and revokes existing sessions. Do not run it with the restricted runtime account.

Unsetting `CONNECTIONSTRING` is necessary so subsequent startup loads the runtime account from `.env` rather than retaining root credentials.

## 7. Verify the application

Run each command and check that it succeeds. Keep the virtualenv active and stay in the project directory.

```bash
DATABASE_MODE=demo python -m unittest discover -s tests -v
```

```bash
python production/validate.py
```

```bash
python <<'PY'
from dotenv import load_dotenv
from database import initialize_database

load_dotenv(".env", override=False)
import os
assert os.environ.get("DATABASE_MODE") == "production", "Expected production mode"
engine = initialize_database()
engine.dispose()

print("Production MySQL connection and startup checks passed.")
PY
```

The test command forces demo mode for the existing SQLite tests; production API tests explicitly select production mode within their fixtures. The existing ten demo tests and nine production API tests passed during development. Production API tests use SQLite-adapted copies of the tables and do not exercise MySQL triggers. The schema validator checks the checked-in `production/schema.sql` against the ORM; it does not validate credentials or grants in the generated root-level deployment file. The last command loads `.env` and performs actual production connection and startup checks on your server.

## 8. Start the application for a local smoke test

```bash
python -m uvicorn main:app \
  --host 127.0.0.1 \
  --port 8000
```

FastAPI listens at `127.0.0.1:8000` **on the Debian server**. Use a second server terminal to check:

```bash
curl --fail http://127.0.0.1:8000/api/config
```

The configuration response should report production mode. Press `Ctrl+C` in the application terminal to stop this foreground smoke-test process.

## Public deployment boundary

These commands install the database and prepare the application for a local smoke test. They do **not** configure Nginx, TLS or a persistent systemd application service. For a public deployment, supervise the ASGI service, proxy Nginx to `127.0.0.1:8000`, terminate HTTPS, configure login/intake rate limits, and keep MySQL restricted to local/private connections. Do not run demo mode publicly.

The current frontend supports login, inquiry submission, administrator conversion and job updates, shipping fields, and customer timeline viewing. It does not provide file uploads, self-service registration or a full pagination interface. Existing data in the original demo schema requires a separate reviewed migration.

Keep `.env` and the generated root-level `schema.sql` private and out of Git. The checked-in `production/schema.sql` contains no runtime password and remains the schema source. Backups must protect both business data and credentials.

Verification in the Windows development environment covers Bash syntax, execution of the embedded configuration generator, URL/password consistency, overwrite refusal, generated table/trigger definitions, and application tests with a generated production `.env`. It does not cover Debian package installation, real MySQL authentication, grants or trigger execution. No Debian/WSL instance or MySQL server is available in that environment. Run the verification steps above and exercise administrator/customer workflows on the Debian instance before making it public. See [INTEGRATION.md](INTEGRATION.md) for application behavior and [production/README.md](production/README.md) for database design details.
