"""Database schema and startup initialization."""

import os
from uuid import uuid4

from sqlalchemy import Boolean, Column, MetaData, String, Table, create_engine, false
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


def initialize_database() -> Engine:
    """Create missing tables without changing existing tables or records."""
    str_connection_string = os.environ.get("CONNECTIONSTRING")
    if not str_connection_string or not str_connection_string.strip():
        raise RuntimeError("CONNECTIONSTRING must be set before starting the app.")
    obj_engine = create_engine(str_connection_string)
    try:
        obj_metadata.create_all(obj_engine, checkfirst=True)
    except Exception:
        obj_engine.dispose()
        raise
    return obj_engine
