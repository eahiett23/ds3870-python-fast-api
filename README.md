# Swollen Hippo Industries

## Verified deployed MySQL backend

The Debian service now runs `uvicorn mysql_portal:app` against MySQL 8.4 and
`swollenhippo_db`. The backend preserves bcrypt passwords, secure cookie login,
string job IDs, customer ownership, and administrator-only job updates.

See [DEPLOYMENT-README.md](DEPLOYMENT-README.md) for the verified deployment,
backups, and rollback, and [mysql_migration/README.md](mysql_migration/README.md)
for the schema and migration tools. Install the root `requirements.txt`.

**Frontend synchronization is deferred.** The deployed page uses cookie auth
and inline JavaScript. This repository's `templates/index.html` still belongs
to the earlier implementation and loads `production.js`; it has not been
replaced. For the new backend, use the verified deployed template through
`APP_TEMPLATE_PATH`. This repository is not yet a complete frontend snapshot
for a fresh deployment. Do not deploy its current template over the live page.

The existing `main.py`, `database.py`, `auth.py`, and `production/` implementation
are preserved. Their `CONNECTIONSTRING` setup and `production/` schema are separate
from the deployed `MYSQL_DATABASE_URL` implementation. Do not mix their schemas.

Run all local tests with `python -B -m unittest discover -s tests -v`.
Rebuild the current schema with `python -B -m mysql_migration.build_schema`.

The 18 new backend/migration tests pass. The retained application's earlier
tests currently fail in the committed baseline as well as this working tree;
see [VERIFICATION.md](VERIFICATION.md). They have not been weakened or removed.

## Earlier implementation documentation

## Production MySQL integration

The app now supports the six-table production schema in `production/`. See
[INTEGRATION.md](INTEGRATION.md) for installation, account provisioning, privileges
and the differences from the demo. MySQL defaults to production mode; SQLite
defaults to demo mode. The setup below describes the original demo schema.

## Quick Start

Set the `CONNECTIONSTRING` environment variable to your SQLAlchemy database URL
before starting the app. Install the database driver required by that URL.
At startup, the app creates the `users` table if it does not exist, preserving
existing data. The database itself must already exist and the connection must
have permission to create tables. Changes to an existing schema require a migration.

The table contains `email` (primary key), `first_name`, `last_name`, `is_admin`
(defaults to false), and `hashed_password`. All columns are required. Store only
password hashes in `hashed_password`; this table does not perform password hashing.

To start the application, you use the VSCode debug launcher and select "Debug App."
Alternatively, you can start the app using command line:

    uvicorn main:app

This runs the web UI on port 8000. The UI can be reached in the following URL:
[http://127.0.0.1:8000/](http://127.0.0.1:8000/)

Run automated tests with `python -m unittest discover -s tests -v`.
Tests use a temporary SQLite database, independent of your configured database.

Startup also creates the `inquiries` table with the `Inquiry` model's fields:
`customer_name`, `email`, `company`, `service`, `project_details`, and `budget`.
All fields are non-nullable, and `budget` defaults to an empty string. An additional
`id` UUID string is the primary key, generated on SQLAlchemy inserts, allowing
multiple inquiries per email. The inquiry API saves submissions using SQLAlchemy,
and the admin inquiry list reads them from the database. The `jobs` table stores all job fields, including the inquiry fields, status,
estimated completion and shipping dates, and creation timestamp. Its required
`inquiry_id` foreign key references `inquiries.id`. Inquiry submission saves both
records in one transaction; job lists and updates persist across restarts.
Startup creates the table automatically without backfilling existing inquiries. Input validation
(such as minimum lengths and email format) remains in the Pydantic model.
