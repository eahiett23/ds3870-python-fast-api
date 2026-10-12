"""Database tables and engine setup for accounts and login sessions."""

import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    create_engine,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

load_dotenv(Path(__file__).with_name(".env"), override=False)

obj_metadata = MetaData()
tbl_users = Table(
    "users",
    obj_metadata,
    Column("email", String(254), primary_key=True),
    Column("first_name", String(120), nullable=False),
    Column("last_name", String(120), nullable=False),
    Column("is_admin", Boolean, nullable=False, default=False),
    Column("hashed_password", String(255), nullable=False),
)
tbl_sessions = Table(
    "sessions",
    obj_metadata,
    Column("token_hash", String(64), primary_key=True),
    Column("user_email", String(254), ForeignKey("users.email", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime, nullable=False),
    Index("ix_sessions_user_email", "user_email"),
)


def initialize_database(str_database_url: str | None = None) -> Engine:
    """Create the auth tables and return an engine for demo SQLite or configured production DB."""
    str_database_mode = os.getenv("DATABASE_MODE", "demo").strip().lower()
    if str_database_url is None:
        if str_database_mode == "production":
            str_database_url = os.getenv("CONNECTIONSTRING")
            if not str_database_url:
                raise RuntimeError("Set CONNECTIONSTRING when DATABASE_MODE=production")
        else:
            str_database_url = os.getenv("DEMO_DATABASE_URL", "sqlite:///./swollen_hippo.db")

    dict_engine_options: dict = {"pool_pre_ping": True}
    if str_database_url.startswith("sqlite:"):
        dict_engine_options["connect_args"] = {"check_same_thread": False}
        if str_database_url in {"sqlite://", "sqlite:///:memory:"}:
            dict_engine_options["poolclass"] = StaticPool

    obj_engine = create_engine(str_database_url, **dict_engine_options)
    obj_metadata.create_all(obj_engine)
    return obj_engine
