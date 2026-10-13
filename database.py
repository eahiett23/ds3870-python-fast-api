"""Database schema and startup initialization."""

import os
from uuid import uuid4

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, MetaData, String, Table, create_engine, event, false, inspect, text
from sqlalchemy.engine import Engine

obj_metadata = MetaData()
tbl_users = Table(
    "users",
    obj_metadata,
    Column("email", String(254), primary_key=True),
    Column("first_name", String(120), nullable=False),
    Column("last_name", String(120), nullable=False),
    Column("is_admin", Boolean, nullable=False, server_default=false()),
    Column("hashed_password", String(1024), nullable=False),
)

tbl_sessions = Table(
    "sessions", obj_metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_email", String(254), ForeignKey("users.email", ondelete="CASCADE"), nullable=False, index=True),
    Column("expires_at", DateTime, nullable=False),
)

tbl_inquiries = Table(
    "inquiries",
    obj_metadata,
    Column("id", String(36), primary_key=True, default=lambda: str(uuid4())),
    Column("customer_name", String(120), nullable=False),
    Column("email", String(254), nullable=False),
    Column("company", String(120), nullable=False),
    Column("service", String(100), nullable=False),
    Column("project_details", String(4000), nullable=False),
    Column("budget", String(80), nullable=False, server_default=""),
)


tbl_jobs = Table(
    "jobs",
    obj_metadata,
    Column("id", String(36), primary_key=True, default=lambda: str(uuid4())),
    Column("inquiry_id", String(36), ForeignKey("inquiries.id"), nullable=False, index=True),
    Column("customer_name", String(120), nullable=False),
    Column("email", String(254), nullable=False),
    Column("company", String(120), nullable=False),
    Column("service", String(100), nullable=False),
    Column("project_details", String(4000), nullable=False),
    Column("budget", String(80), nullable=False, server_default=""),
    Column("status", String(30), nullable=False, server_default="Pending"),
    Column("estimated_completion_date", Date, nullable=True),
    Column("estimated_shipping_date", Date, nullable=True),
    Column("created_at", String(40), nullable=False),
)


def enable_sqlite_foreign_keys(obj_connection, obj_connection_record):
    """SQLite requires foreign key enforcement to be enabled per connection."""
    obj_cursor = obj_connection.cursor()
    try:
        obj_cursor.execute("PRAGMA foreign_keys=ON")
    finally:
        obj_cursor.close()


def initialize_database() -> Engine:
    """Create missing tables without changing existing tables or records."""
    str_connection_string = os.environ.get("CONNECTIONSTRING")
    if not str_connection_string or not str_connection_string.strip():
        raise RuntimeError("CONNECTIONSTRING must be set before starting the app.")
    obj_engine = create_engine(str_connection_string, pool_pre_ping=True)
    str_mode = os.environ.get('DATABASE_MODE', 'production' if obj_engine.dialect.name == 'mysql' else 'demo')
    if str_mode not in {'production', 'demo'}:
        obj_engine.dispose()
        raise RuntimeError('DATABASE_MODE must be production or demo')
    if str_mode == 'production':
        if obj_engine.dialect.name != 'mysql':
            obj_engine.dispose()
            raise RuntimeError('Production mode requires MySQL 8.0.16+; import production/schema.sql first')
        event.listen(obj_engine, 'checkout', configure_mysql_connection)
        try:
            from production.models import Base
            obj_inspector = inspect(obj_engine)
            for str_table, obj_table in Base.metadata.tables.items():
                set_existing = {obj_column['name'] for obj_column in obj_inspector.get_columns(str_table)}
                if not set(obj_table.columns.keys()) <= set_existing:
                    raise RuntimeError('Production schema mismatch; use a fresh database loaded from production/schema.sql')
            with obj_engine.connect() as obj_connection:
                str_version = obj_connection.execute(text('SELECT VERSION()')).scalar_one()
                if 'MariaDB' in str_version or tuple(int(str_part) for str_part in str_version.split('-')[0].split('.')[:3]) < (8, 0, 16):
                    raise RuntimeError('MySQL 8.0.16+ required')
                # The definer routine allows readiness checks without granting
                # the runtime account permission to alter triggers.
                obj_cursor = obj_connection.connection.cursor()
                try:
                    obj_cursor.execute('CALL production_schema_ready()')
                    int_installed = obj_cursor.fetchone()[0]
                    while obj_cursor.nextset():
                        pass
                finally:
                    obj_cursor.close()
                if int_installed != 8:
                    raise RuntimeError('Production audit triggers missing; import production/schema.sql')
        except Exception:
            obj_engine.dispose()
            raise
        return obj_engine
    if obj_engine.dialect.name == "sqlite":
        event.listen(obj_engine, "connect", enable_sqlite_foreign_keys)
    try:
        obj_metadata.create_all(obj_engine, checkfirst=True)
    except Exception:
        obj_engine.dispose()
        raise
    return obj_engine


def configure_mysql_connection(obj_connection, obj_connection_record, obj_connection_proxy):
    """Pooled MySQL connections must never inherit another request's actor."""
    obj_cursor = obj_connection.cursor()
    try:
        obj_cursor.execute("SET time_zone = '+00:00'")
        obj_cursor.execute("SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'")
        obj_cursor.execute('SET @app_actor_id = NULL')
    finally:
        obj_cursor.close()

