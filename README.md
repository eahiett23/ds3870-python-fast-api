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
