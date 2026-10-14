# MySQL repository update verification

Checked on 2026-10-13 with Python and the installed local test dependencies.

| Check | Result |
| --- | --- |
| New backend contract and migration mapping tests | 18 tests passed in the actual repository. |
| Full repository suite | 37 tests ran; retained tests reported 18 failure events, including subtests, and one error. |
| Untouched committed baseline | The same failures reproduced with the 19 original tests from bcf4cbd275da8e313cd03bcdc7067bc0453245fc. |
| MySQL DDL builder | Passed: ORM relationships, six tables, two routines, eight triggers, legacy-ID uniqueness and form-text columns. |
| Generated DDL SHA256 | 54eb05d8bf0b5d7a31039817c628fc8b4c4d3d6e2d94706a07359898ae898838 |
| Added backend SHA256 | 38b67196dea3c46b58672aa4ad6757c9017eb371cf91b2b26dfbae6b912f3e70; matches the verified deployment artifact byte for byte. |

The committed application contains cookie authentication/security changes that
the earlier tests do not accommodate. Examples include an additional sessions
table, protected dashboard reads returning 401, and write requests without the
required Origin returning 403. These failures occurred in an isolated copy of
the committed source with no new backend or migration files. This update did
not edit main.py, database.py, auth.py, the existing frontend or the older tests.
Repairing the retained implementation/tests is a separate follow-up, not a reason
to relax authorization checks or skip existing tests.

Focused new checks:

```bash
python -B -m unittest tests.test_mysql_portal tests.test_migration_preflight -v
python -B -m mysql_migration.build_schema
```

Full suite, including the known baseline failures:

```bash
python -B -m unittest discover -s tests -v
```

The new API tests use independent SQLite fixtures, so they do not prove MySQL
triggers. During the deployment session the user ran the actual MySQL runtime
tests and confirmed denied customer edits, administrator audit creation,
immutable history, rolled-back temporary records and cleared actor context.
The staged installed app then passed www-data startup, frontend loading,
administrator bcrypt login, secure cookie/session lookup, dashboard JSON and logout.

The final stopped-service backup contained seven customers and two jobs. The
import committed eight users including the administrator, two jobs and two
import audit records. The live systemd command changed to mysql_portal:app;
HTTPS /healthz returned 200 with JSON and administrator login showed both jobs.
These server results are based on the user's pasted execution output; the
assistant did not directly execute SSH commands.

Remaining verification: manual customer-only browser access, frontend alignment
with the repository (explicitly deferred), and backup scheduling/restoration tests.
The repository frontend is still not the complete deployed frontend snapshot.
Database files and bytecode were untracked without deleting local copies.
