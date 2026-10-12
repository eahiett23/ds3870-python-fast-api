# SwollenHippo Industries database

Deliverables: `schema.sql`, `models.py`, `seed.sql`. This is a new MySQL schema, not a migration of the original demo users table. The project now includes a production API adapter; see `../INTEGRATION.md` for its installation and behavior.

## Installation

Use MySQL **8.0.16 or newer**, InnoDB, strict SQL mode, utf8mb4/utf8mb4_0900_ai_ci, and UTC connections. MySQL versions before 8.0.16 do not enforce CHECK constraints. On Debian, install the MySQL client and run against a new database:

```sh
mysql --default-character-set=utf8mb4 -u migration_user -p < schema.sql
# Development only:
mysql --default-character-set=utf8mb4 -u migration_user -p < seed.sql
```

DDL commits implicitly; a failed import requires inspection before retry. The migration principal needs CREATE DATABASE, CREATE, INDEX, REFERENCES, CREATE ROUTINE and TRIGGER privileges. Do not use it as the application principal. Run `schema.sql` once; `triggers.sql` is already embedded in it.

The demo seed creates an admin and a customer, two converted inquiries, an active 55% job and a completed archived job with sample shipment data. Attachment references and tracking values are illustrative, not live files or shipments. Both passwords are valid random Argon2id hashes whose plaintext was discarded. Provision/reset credentials securely before login; there is no shared default password. Never load the demo seed into production.

## Relationships and retention

`users` has many sessions, inquiries, jobs and authored milestones. Each inquiry converts to at most one job (`jobs.inquiry_id` is unique). Each job has many immutable milestones and attachments. Each attachment references exactly one inquiry or job, supporting multiple intake files including anonymous uploads. Conversion should update inquiry status and move attachments to the job in the same transaction; verify any authenticated inquiry owner matches the job customer.

Jobs use `status` as their lifecycle stage, separate from inquiry review status. `archived_at` filters dashboard history independently of stage. Completion requires 100% and an actual completion timestamp; software/design jobs can complete without shipping. Stage transitions may skip stages; enforce service-specific transitions in FastAPI. Shipping carrier is free text to support local couriers; tracking number is not globally unique.

Sessions delete with their user (`delete-orphan` / ON DELETE CASCADE). Job owners and audit authors cannot be deleted while referenced; deactivate them and anonymize personal fields according to retention policy. Anonymous inquiry contact data survives account deletion. Jobs are archived instead of deleted. All other history relationships intentionally omit destructive ORM cascades. Milestones reject UPDATE and DELETE. Timestamps are UTC DATETIME(6), with automatic created/updated values; timeline order uses timestamp plus ID.

Customer/status + created_at composite indexes support dashboard and review queue paging; unique email/job number/token digest indexes support identity lookups. Use keyset pagination with IDs as tie-breakers. The timeline has a matching `(job_id, created_at, id)` index.

## Authentication and privilege boundary

Use Argon2id (the seed uses 64 MiB, 3 iterations, 4 lanes); benchmark and tune on deployment hardware. Normalize email by trimming/lowercasing before storage and login. The chosen case/accent-insensitive collation also treats accent variants as equal; do not silently merge identities. Validate email, phone, currency and URLs in API request schemas.

Generate cryptographically random refresh tokens (at least 256 bits); store SHA-256 digests in `token_digest`, never plaintext. Validate expiry/revocation and active user on each refresh. Lock the session row, revoke the old token and create its replacement atomically to prevent concurrent replay; expire old records periodically. JWTs should carry short expirations and validated issuer/audience. Check current role/active status for every privileged request rather than trusting stale role claims. Enforce rate limits and, for cookie sessions, Secure/HttpOnly/SameSite and CSRF protections.

For every privileged transaction, set the actor from the **authenticated user**, never a request-body field:

```python
with obj_session.begin():
    obj_session.execute(text('SET @app_actor_id = :actor'), {'actor': authenticated_user.id})
    # UPDATE jobs must set updated_by_admin_id to that actor.
    # ORM versioning increments version and rejects stale concurrent writes.
    # Explicit SQL writers must use WHERE id=:id AND version=:expected,
    # increment version and require rowcount == 1.
    obj_session.flush()
```

Configure a SQLAlchemy pool checkout hook that executes both `SET time_zone = '+00:00'` and `SET @app_actor_id = NULL`; also clear the actor in a `finally` block before returning a connection. Session variables survive rollback. Keep actor setting and writes on the same connection. Triggers require an active admin actor, match the recorded author, reject ownership changes and append an audit snapshot for every job update. Standalone milestone notes require the same actor check.

**A MySQL session variable is not authentication.** Anyone holding the application SQL credentials can assert an admin ID. This design enforces role checks for trusted backend operations, not against a compromised backend or database owner. Never expose SQL credentials to customers. Use parameterized SQL, restricted network access and separate database principals for public intake, customer reads, admin writes and account provisioning. Do not grant application accounts role/password update columns, DDL, TRIGGER, or routine modification privileges. Public registration must force `customer`; only the provisioning principal may assign `admin`. Use column-level grants for account profile changes. Keep database backups and logs protected.

Customer API reads **must** filter `jobs.customer_id = authenticated_user.id`; access to milestones/attachments must join through the job owner. MySQL has no native per-row customer policy here. Public intake may INSERT inquiries/attachments but cannot SELECT other submissions, change review status, or modify jobs. Never bind writable ORM objects directly to arbitrary JSON. Admin routes must validate roles before touching the database.

## Files, migrations and deployment

Keep blobs in private object storage or outside Nginx's public directory. Store relative opaque object keys or approved HTTPS CDN URLs, original filenames, MIME type, byte size and optional SHA-256. Validate actual content, size and extensions, reject traversal/absolute local paths and scan archives/uploads. Serve authorized short-lived signed URLs. Use per-inquiry upload tickets for anonymous uploads; NULL uploader is not proof of ownership. Final QC photo upload routes require admin authorization. No credentials or public access tokens belong in stored URLs.

Alembic: set `target_metadata = Base.metadata`; review every generated migration. Autogenerate does not manage these procedures/triggers. Install `triggers.sql` explicitly through individual statements in the initial revision (`DELIMITER` is a client command, not server SQL), and version later trigger changes. `create_all()` only creates tables and would omit privilege/audit behavior. Adopt the supplied SQL as a reviewed baseline before stamping it; never stamp an unverified database. Back up and test upgrades/restores before deployment.

Debian/Nginx: use a virtualenv with Python 3.11+, install `requirements.txt`, run FastAPI under a supervised ASGI service, and terminate TLS at Nginx. Keep the database on localhost/private networking, secrets outside source control, and configure connection pool limits, request/upload limits and health checks. Hosting settings do not belong in the relational schema.

MySQL references: [trigger semantics](https://dev.mysql.com/doc/refman/8.0/en/trigger-syntax.html), [stored-program restrictions](https://dev.mysql.com/doc/mysql-reslimits-excerpt/8.0/en/stored-program-restrictions.html). History FKs use RESTRICT because cascaded FK actions bypass triggers.

## Validation

`python validate.py` configures all ORM relationships, compiles MySQL DDL, compares it to schema.sql, verifies the seed hashes, and checks required constraints/triggers. It does not replace execution against MySQL. No MySQL server/client was available in the creation environment, so live DDL/trigger execution remains unverified. Before deploying, load both scripts into disposable MySQL, exercise customer/admin writes, invalid progress, stale versions, history edits/deletes, and ownership-filtered reads.
