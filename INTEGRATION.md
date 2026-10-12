# Production database integration

The existing FastAPI entry point (`main:app`) and HTML page now support the supplied six-table MySQL schema. SQLite retains the original demo behavior; MySQL defaults to production mode. Set `DATABASE_MODE=demo` only for the old demonstration schema. The demo role header grants access in demo mode and must not be used for a public deployment.

## Use the production database

1. Install the project's `requirements.txt` in your Python virtualenv.
2. With a migration/provisioning database account, import `production/schema.sql` into **a fresh MySQL 8.0.16+ database**. Optionally import `production/seed.sql` for development.
3. Create a restricted runtime database account; see the grants below. The definer of the stored routines/triggers must remain present and retain its privileges.
4. Use the provisioning account's CONNECTIONSTRING to run the credential command below. Seeded accounts cannot log in until their credentials are reset.
5. Copy `.env.production.example` to `.env`, replace the URL credentials with the runtime account, then run `uvicorn main:app` from this project directory.
6. Open the existing homepage. Production mode shows **Sign in** rather than the role-preview selector. Public inquiry submission remains available.

Provision or reset accounts with the privileged provisioning connection, not the runtime connection:

```sh
python -m production.provision_user --email admin@swollenhippo.example --role admin --first-name Hippo --last-name Admin
python -m production.provision_user --email customer@example.test --role customer --first-name Alex --last-name Rivera
```

Passwords are prompted and never placed in command-line arguments. The command prints the numeric account ID, needed when assigning public inquiries to customers. Verify the contact's identity before assigning an anonymous inquiry; matching email alone is not proof of ownership. Password resets revoke existing sessions. Reset/provision commands also explicitly assign the requested role, so protect provisioning credentials.

Example runtime grants after creating `hippo_app` with a strong password, under your deployment's appropriate host restriction:

```sql
GRANT SELECT ON swollenhippo_industries.users TO 'hippo_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON swollenhippo_industries.user_sessions TO 'hippo_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON swollenhippo_industries.inquiries TO 'hippo_app'@'localhost';
GRANT SELECT, INSERT, UPDATE ON swollenhippo_industries.jobs TO 'hippo_app'@'localhost';
GRANT SELECT, INSERT ON swollenhippo_industries.job_milestones TO 'hippo_app'@'localhost';
GRANT SELECT, UPDATE ON swollenhippo_industries.job_attachments TO 'hippo_app'@'localhost';
GRANT EXECUTE ON PROCEDURE swollenhippo_industries.production_schema_ready TO 'hippo_app'@'localhost';
```

The runtime account cannot create accounts, change roles/passwords, delete history or alter triggers. The current UI does not upload files; attachment references in the seed are examples. A future upload endpoint needs separately reviewed storage and INSERT privileges. Existing table/column names are checked at startup; missing schema, routines or audit triggers fail startup instead of silently creating an incomplete production database. Connections reset the admin actor, use UTC and strict SQL mode.

## Application behavior

- Existing `/api/inquiry` form fields are translated into production inquiry fields. Budget ranges are retained in the description, while exact numeric amounts populate `target_budget`. Production exposes separate 3D-printing/CNC choices.
- Public submission creates an inquiry, not an automatically approved job. The admin board converts it into a job associated with an active customer account.
- Login returns a random eight-hour bearer session token; only its SHA-256 digest is stored. The browser keeps the token in memory, so page refresh requires signing in again. Logout revokes it. This implementation uses opaque sessions, not JWT/refresh-token rotation.
- `/api/jobs?role=customer` returns only the authenticated user's active and archived jobs. Admin access requires the role stored on the authenticated account; `X-User-Role` cannot grant production privileges.
- Admin updates translate the existing date fields to the new schema, validate progress/shipping/completion and require the current job version. Concurrent stale updates return HTTP 409.
- MySQL automatically adds audit snapshots; customers can view their timelines. Admins can POST a note to `/api/jobs/{id}/milestones` with `{"note":"..."}`.
- `/api/config` tells the page which mode/stages to use. The production page adds progress, actual dates and tracking fields. The existing styling and demo behavior remain available.

The board currently returns at most 200 jobs/inquiries and a timeline at most 500 updates. Pagination, upload UI and self-service registration are future features. Configure TLS, login/intake rate limiting and service supervision before a public deployment. Never publish demo mode or expose SQL credentials.

## Existing data

No existing database or `.env` was modified. Old UUID IDs, email primary keys and text budgets do not match the new numeric IDs, account ownership and decimal budgets. Importing `schema.sql` over old tables is unsupported. Existing records need an explicit migration with ID mapping and verified customer assignment; they are not migrated automatically.

## Verification

Run `python -m unittest discover -s tests -v`, `python production/validate.py`, and `node --check templates/production.js`.

The existing ten demo tests and nine production API tests passed during integration. Production API tests use copied SQLite-compatible tables to verify API logic; they do not exercise MySQL triggers. No MySQL server/client was available on this machine, so live MySQL installation, trigger execution and production startup remain unverified. Load the schema into a disposable MySQL instance and test those before deployment.
