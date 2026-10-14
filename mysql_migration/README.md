# MySQL schema and migration tools

These files preserve the implementation used for the completed Debian SQLite-to-MySQL
migration. The deployed backend is the repository-root `mysql_portal.py`.
Frontend synchronization was explicitly deferred; see the root deployment guide.

| File | Purpose |
| --- | --- |
| `swollenhippo-mysql-schema.sql` | Fresh MySQL schema: six InnoDB tables, constraints/indexes, two routines and eight audit/role triggers. |
| `models.py`, `triggers.sql`, `build_schema.py` | SQLAlchemy 2.0 declarative schema, trigger source and deterministic DDL builder. |
| `001-preserve-form-text.sql` | One-time patch for the original installation that lacked service_label/budget_text. Already applied on the live server; not needed with the final schema. |
| `migration_preflight.py` | Read-only backup validation, target inventory and actual MySQL-collation email collision checks. |
| `provision_runtime.py` | Creates hippo_api@localhost with eight allowed connections and restricted table/column grants; prompts privately. |
| `prepare_mysql_environment.py` | Verifies the runtime login and exclusively creates root-only /etc/swollenhippo.env. |
| `verify_mysql_runtime.py` | Tests real grants, role assertions, audit triggers and actor reset; temporary records are rolled back. Auto-increment gaps may occur. |
| `verify_staged_portal.py` | Reads protected configuration, drops to www-data and tests the installed backend, frontend loading and cookie login/logout in-process. |
| `create_final_backup.py` | Requires an inactive service and creates a private, integrity-checked SQLite backup through the backup API. |
| `import_sqlite_backup.py` | Requires an inactive service and imports a final backup into an empty target containing only the expected administrator, with verification before a single commit. |

Tools are explicit commands, never automatic startup migrations. Linux deployment
paths and the administrator email are specific to the verified deployment and
must be reviewed for another server. Do not rerun fresh setup/import commands on
the populated live database. The importer refuses a populated target. The final
schema contains the form-text columns; do not also run the one-time patch.

From the repository root:

```bash
python -B -m unittest discover -s tests -v
python -B -m mysql_migration.build_schema
```

The focused new tests can be run with
`python -B -m unittest tests.test_mysql_portal tests.test_migration_preflight -v`.
All 18 pass. The full suite includes failing older tests that also fail in the
untouched committed baseline; see the root VERIFICATION.md for the comparison.

On Debian, server tools can be run as scripts, for example:

```bash
sudo /opt/swollenhippo/.venv/bin/python -B mysql_migration/migration_preflight.py --source /var/backups/swollenhippo/VERIFIED_BACKUP.sqlite3
```

Replace the example with an actual `sqlite-before-mysql-*.sqlite3` backup path.
The preflight's empty-target check means it is a pre-import tool, not a health
check for the already populated database. `verify_staged_portal.py` remains
usable for a controlled login check but creates/removes a normal session.

Migration preserved bcrypt hashes, original UUIDs in unique immutable legacy_id,
independent contact details, service labels, budget text, UTC job creation times
and estimated dates. Pending became intake/0%. Source accounts had no timestamps;
their new audit timestamps represent migration time. Import milestones record
import time, not historical job events. No historical inquiries, actual dates,
shipping details or expired/cookie sessions were invented or copied.

The old five-stage dashboard is supported through response aliases. Saving a
pending inquiry as an administrator converts it to a customer-owned job;
refresh the board after conversion. Other stages preserve progress unless an
administrator supplies a percentage. Completed sets 100%; Shipped/Completed
record the transition time when an actual date is absent. Advanced clients can
supply actual dates, carrier/tracking, notes and a version for stale-edit rejection.
Ownership-protected milestones are available as JSON. Archived jobs can be
queried with include_archived=true. Public intake uses POST /api/inquiries;
the original /api/inquiry route retains authentication. Assignment of a public
inquiry to a verified customer is a future extension. Combined manufacturing
labels remain other until printing versus CNC is clarified.

The backend reflects the schema without create_all, sets UTC and clears the
actor assertion on checkout. Each worker has a pool of two plus one overflow;
two workers fit the server's 20-connection ceiling. Runtime signup grants exclude
role/is_active, roles default to customer, and audit history cannot be changed.
@app_actor_id is a trusted-backend assertion, not SQL-client authentication;
private credentials and API authorization remain essential. Keep the definer
account/routine privileges intact.

Local tests exercise contract/mapping behavior using an independent SQLite
fixture and do not prove MySQL triggers. On the actual server, runtime/grant
tests, staged www-data checks, activation, HTTPS JSON health and administrator
login with both imported jobs were confirmed in this session. The manual
customer-only browser check and automated MySQL backup scheduling remain pending.
