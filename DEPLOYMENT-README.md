# Verified Debian MySQL deployment

The SQLite-to-MySQL migration and activation completed on 2026-10-13. MySQL 8.4.11,
FastAPI/Uvicorn, the www-data service account, the runtime grants and audit triggers,
and the TLS reverse proxy were checked on the server. The HTTPS health endpoint
returned 200 with {"status":"ok"}; administrator login displayed both imported jobs.
Local contract/mapping tests accompany the implementation. Customer-only browser
verification and scheduled MySQL backups remain follow-ups.

## Current deployment inventory

| Component | Verified location/configuration |
| --- | --- |
| Application | /opt/swollenhippo/mysql_portal.py; ASGI entry point mysql_portal:app |
| Virtual environment | /opt/swollenhippo/.venv; Python 3.13 |
| Frontend | /opt/swollenhippo/templates/index.html; deployed cookie-auth page |
| Protected configuration | /etc/swollenhippo.env; root:root, 0600 |
| Service | /etc/systemd/system/swollenhippo.service; www-data:www-data |
| MySQL override | /etc/systemd/system/swollenhippo.service.d/20-mysql.conf |
| Backend listener | 127.0.0.1:8000; two workers; only 127.0.0.1 trusted for proxy headers |
| Database | swollenhippo_db; MySQL 8.4; utf8mb4 / utf8mb4_0900_ai_ci |
| Runtime database account | hippo_api@localhost; restricted grants; max eight connections |
| MySQL settings | /etc/mysql/conf.d/zz-swollenhippo-project.cnf |
| Nginx site | /etc/nginx/sites-available/swollenhippo and its sites-enabled link |
| Proxy headers | /etc/nginx/snippets/swollenhippo-proxy.conf |
| TLS certificate | /etc/letsencrypt/live/swollenhippoindustries.duckdns.org/ |
| Preserved SQLite | /var/lib/swollenhippo/swollen_hippo.sqlite3 |
| Final SQLite backup | /var/backups/swollenhippo/sqlite-before-mysql-20261013T222158116832Z.sqlite3 |

The imported totals were eight users (seven customers plus the administrator),
two jobs and two import milestones. These are historical cutover totals, not a
permanent expectation as customers and jobs are added. The final backup SHA256 was
`6daf6c9241e28679831fbc64f2a389964f2e422f4672b4a76dabcdf88ae3f56c`.
No database contents, password hashes, root/runtime passwords or live environment
files belong in Git.

## Important repository limitation

Frontend synchronization was deferred. The repository's existing template and
production.js belong to the earlier main:app implementation. Obtain and compare
the complete deployed index.html before a fresh frontend deployment. Do not clone
this repository over the live application wholesale: the deployed SQLite main.py
used for rollback also differs from the retained repository main.py. The current
repository adds the verified MySQL backend without replacing those older files.

## Schema and configuration templates

Use mysql_migration/swollenhippo-mysql-schema.sql for a fresh target only. It
creates six tables, two routines and eight triggers and contains the final
service-label and budget-text columns. Use a privileged setup account for DDL,
not hippo_api. Do not reimport it or apply 001-preserve-form-text.sql on the
already configured server. See mysql_migration/README.md for each tool.

The root requirements.txt includes bcrypt and PyMySQL[rsa]. mysql_portal.py
requires MYSQL_DATABASE_URL and refuses root/SQLite connections. A placeholder
.env.mysql.example shows the EnvironmentFile keys but contains no usable secret;
the backend does not automatically load that example. Prepare the real private
file through the password-prompting helper, rather than placing credentials in
commands or committing .env files.

deployment/zz-swollenhippo-project.cnf preserves the tested 1 GB demonstration-VM
settings (64 MB InnoDB buffer, max_connections=20 and performance_schema disabled).
It does not cap all MySQL memory. Reassess capacity and observability before public
traffic. Both MySQL listeners were verified bound to 127.0.0.1.

deployment/swollenhippo-mysql.conf is a drop-in for an existing hardened service,
not a complete service unit. It retains that unit's www-data identity,
WorkingDirectory=/opt/swollenhippo, EnvironmentFile=/etc/swollenhippo.env,
NoNewPrivileges, ProtectSystem=strict, ProtectHome, PrivateTmp and
ReadWritePaths=/var/lib/swollenhippo. Only install/activate it after verified
final import. Service activation requires daemon-reload and start; never switch
the live database URL alone because the old tables and auth contracts differ.

## Completed migration sequence

1. Audited the application, virtualenv, SQLite schema, permissions and services.
2. Verified Nginx's duplicate domain issue was fixed and HTTP redirects to HTTPS.
3. Installed official MySQL 8.4 LTS on Debian 13 after repository signature checks
   and applied the demonstration-VM configuration.
4. Created the empty schema and separate administrator, then provisioned hippo_api.
5. Ran backup/data preflight, actual grant/trigger tests with rolled-back records,
   and installed/configured backend checks as www-data.
6. Stopped swollenhippo.service, created a fresh final SQLite backup and verified it.
7. Imported and verified all customer/job data plus audit records in one transaction.
8. Installed the systemd drop-in, reloaded units, started the service and verified
   the actual mysql_portal entry point, HTTPS JSON health, and administrator board.

Do not rerun this migration sequence on the populated live target. Preflight/import
tools intentionally refuse it. A future migration requires a new reviewed plan.

## Read-only service checks

```bash
systemctl show swollenhippo.service --no-pager -p ActiveState -p SubState -p ExecStart
systemctl show mysql.service --no-pager -p ActiveState -p MemoryCurrent
sudo -n /usr/sbin/nginx -t
hippo_domain=swollenhippoindustries.duckdns.org
/usr/bin/curl -q -sS -i --output - --resolve "$hippo_domain:443:127.0.0.1" "https://$hippo_domain/healthz"
```

Healthz is a liveness check, not an ongoing SELECT probe. Startup verifies the
schema and eight triggers; functional login/dashboard checks exercise database
connectivity. Do not print /etc/swollenhippo.env or full process environments.

## MySQL backups after cutover

The preserved SQLite backups do not include new MySQL changes. Create a private
MySQL logical backup with a privileged backup/operator account, then verify and
test restoration in an isolated MySQL instance before relying on it. For a manual
snapshot on the verified server:

```bash
sudo sh -c 'umask 077; set -C; mysqldump --user=root --password --single-transaction --routines --triggers --events --no-tablespaces --databases swollenhippo_db > /var/backups/swollenhippo/mysql-$(date -u +%Y%m%dT%H%M%S).sql'
```

This prompts privately for the MySQL root password and writes a new protected
backup. Stop on any dump error; an empty/partial file is not a verified backup.
For scheduled backups, use reviewed backup credentials, retention, off-VM storage,
monitoring and periodic isolated restore tests. Scheduling was not added to the
server in this session. Keep old SQLite files until verification is complete.

## Rollback on the existing VM only

If activation fails, first stop the service. Disable only the newly added
20-mysql.conf drop-in, run systemctl daemon-reload and start the existing main:app
service against its untouched SQLite file. Preserve the MySQL data and final
backup. The original base unit/SQLite main.py must still be present; repository
main.py is not a substitute for that deployed rollback version.

Once MySQL has accepted new writes, SQLite is stale. Reconcile those writes before
rollback or a later migration; merely switching services back can lose access to
new accounts or updates. Do not delete/import over audit history to retry.

## Local automated checks

```bash
python -B -m unittest discover -s tests -v
python -B -m mysql_migration.build_schema
```

The 18 added tests pass independently. The full 37-test suite also reports 18
failure events (including subtests) and one error from retained older tests.
The untouched committed baseline reproduces those same failures; see VERIFICATION.md.
Neither the existing entry point nor its tests were changed to hide them.

The builder configures ORM relationships, compiles MySQL DDL and checks six tables,
two routines, eight triggers, legacy-ID uniqueness and compatibility fields. API
tests use SQLite fixtures; actual grant/trigger/staged-server checks were run on
the Debian VM, not by the local test suite. The deferred customer browser check
and frontend repository alignment are still outstanding.
