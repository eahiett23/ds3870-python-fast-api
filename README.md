# Job Intake App

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
