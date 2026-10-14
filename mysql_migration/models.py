"""MySQL 8.0.16+ schema. Apply schema.sql/Alembic, not create_all, in production.

All DATETIME values are naive UTC; set every database connection to +00:00.
Database triggers live in schema.sql and must also be installed by migrations.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from sqlalchemy import CheckConstraint, ForeignKey, Index, MetaData, Numeric, String, Text, text
from sqlalchemy.dialects.mysql import BIGINT, BINARY, DATETIME, ENUM, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

STAGES = ('intake', 'toolpathing_design', 'in_production', 'post_processing_qa',
          'ready_to_ship', 'shipped', 'delivered', 'completed', 'cancelled')
SERVICES = ('3d_printing', 'cnc', 'electronics', 'software', 'design', 'other')
OPTIONS = dict(mysql_engine='InnoDB', mysql_charset='utf8mb4', mysql_collate='utf8mb4_0900_ai_ci')


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention={'fk': 'fk_%(table_name)s_%(column_0_name)s', 'uq': 'uq_%(table_name)s_%(column_0_name)s', 'pk': 'pk_%(table_name)s'})


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=text('CURRENT_TIMESTAMP(6)'))
    updated_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6), server_default=text('CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6)'), server_onupdate=text('CURRENT_TIMESTAMP(6)'))


class User(Timestamps, Base):
    __tablename__ = 'users'
    __table_args__ = (CheckConstraint('is_active IN (0, 1)', name='ck_user_active'), Index('ix_users_role', 'role', 'is_active'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(ENUM('customer', 'admin'), server_default=text("'customer'"))
    first_name: Mapped[str] = mapped_column(String(120))
    last_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(32))
    company_name: Mapped[str | None] = mapped_column(String(200))
    company_address: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int] = mapped_column(TINYINT(unsigned=True), server_default=text('1'))
    sessions: Mapped[list[UserSession]] = relationship(back_populates='user', cascade='all, delete-orphan', passive_deletes=True)
    inquiries: Mapped[list[Inquiry]] = relationship(back_populates='customer', passive_deletes='all')
    jobs: Mapped[list[Job]] = relationship(back_populates='customer', foreign_keys='Job.customer_id', passive_deletes='all')
    edited_jobs: Mapped[list[Job]] = relationship(back_populates='updated_by', foreign_keys='Job.updated_by_admin_id', passive_deletes='all')
    milestones: Mapped[list[JobMilestone]] = relationship(back_populates='admin', passive_deletes='all')
    attachments: Mapped[list[JobAttachment]] = relationship(back_populates='uploader', passive_deletes='all')


class UserSession(Timestamps, Base):
    __tablename__ = 'user_sessions'
    __table_args__ = (CheckConstraint('expires_at > created_at', name='ck_session_expiry'), Index('ix_sessions_user_expiry', 'user_id', 'expires_at'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE', onupdate='RESTRICT'))
    token_digest: Mapped[bytes] = mapped_column(BINARY(32), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DATETIME(fsp=6))
    revoked_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    last_used_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(512))
    user: Mapped[User] = relationship(back_populates='sessions')


class Inquiry(Timestamps, Base):
    __tablename__ = 'inquiries'
    __table_args__ = (CheckConstraint('target_budget IS NULL OR target_budget >= 0', name='ck_inquiry_budget'), Index('ix_inquiries_status_created', 'status', 'created_at'), Index('ix_inquiries_customer_created', 'customer_id', 'created_at'), Index('ix_inquiries_email', 'contact_email'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL', onupdate='RESTRICT'))
    contact_name: Mapped[str] = mapped_column(String(240))
    contact_email: Mapped[str] = mapped_column(String(254))
    contact_phone: Mapped[str | None] = mapped_column(String(32))
    company_name: Mapped[str | None] = mapped_column(String(200))
    inquiry_type: Mapped[str] = mapped_column(ENUM(*SERVICES))
    service_label: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    budget_text: Mapped[str | None] = mapped_column(String(80))
    target_budget: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'USD'"))
    target_completion_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    status: Mapped[str] = mapped_column(ENUM('pending', 'reviewed', 'quoted', 'converted', 'rejected'), server_default=text("'pending'"))
    customer: Mapped[User | None] = relationship(back_populates='inquiries')
    job: Mapped[Job | None] = relationship(back_populates='inquiry', passive_deletes='all')
    attachments: Mapped[list[JobAttachment]] = relationship(back_populates='inquiry', passive_deletes='all')


class Job(Timestamps, Base):
    __tablename__ = 'jobs'
    __table_args__ = (
        CheckConstraint('progress_percentage BETWEEN 0 AND 100', name='ck_job_progress'),
        CheckConstraint("status <> 'completed' OR (progress_percentage = 100 AND actual_completion_at IS NOT NULL)", name='ck_job_completed'),
        CheckConstraint("status NOT IN ('shipped', 'delivered') OR actual_ship_at IS NOT NULL", name='ck_job_shipping'),
        Index('ix_jobs_customer_created', 'customer_id', 'created_at'), Index('ix_jobs_status_created', 'status', 'created_at'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    job_number: Mapped[str] = mapped_column(String(32), unique=True)
    legacy_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    inquiry_id: Mapped[int | None] = mapped_column(ForeignKey('inquiries.id', ondelete='RESTRICT', onupdate='RESTRICT'), unique=True)
    title: Mapped[str] = mapped_column(String(240))
    description: Mapped[str] = mapped_column(Text)
    service_type: Mapped[str] = mapped_column(ENUM(*SERVICES))
    service_label: Mapped[str | None] = mapped_column(String(100))
    budget_text: Mapped[str | None] = mapped_column(String(80))
    contact_name: Mapped[str | None] = mapped_column(String(240))
    contact_email: Mapped[str | None] = mapped_column(String(254))
    company_name: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(ENUM(*STAGES), server_default=text("'intake'"))
    progress_percentage: Mapped[int] = mapped_column(TINYINT(unsigned=True), server_default=text('0'))
    target_completion_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    actual_completion_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    estimated_ship_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    actual_ship_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    carrier_name: Mapped[str | None] = mapped_column(String(100))
    tracking_number: Mapped[str | None] = mapped_column(String(128))
    tracking_url: Mapped[str | None] = mapped_column(String(2048))
    archived_at: Mapped[datetime | None] = mapped_column(DATETIME(fsp=6))
    version: Mapped[int] = mapped_column(BIGINT(unsigned=True), server_default=text('1'), default=1)
    updated_by_admin_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    __mapper_args__ = {'version_id_col': version}
    customer: Mapped[User] = relationship(back_populates='jobs', foreign_keys=[customer_id])
    updated_by: Mapped[User] = relationship(back_populates='edited_jobs', foreign_keys=[updated_by_admin_id])
    inquiry: Mapped[Inquiry | None] = relationship(back_populates='job')
    milestones: Mapped[list[JobMilestone]] = relationship(back_populates='job', order_by='(JobMilestone.created_at, JobMilestone.id)', passive_deletes='all')
    attachments: Mapped[list[JobAttachment]] = relationship(back_populates='job', passive_deletes='all')


class JobMilestone(Timestamps, Base):
    """Immutable chronological notes and status snapshots; trigger appends on job writes."""
    __tablename__ = 'job_milestones'
    __table_args__ = (CheckConstraint('progress_percentage BETWEEN 0 AND 100', name='ck_milestone_progress'), Index('ix_milestones_job_created', 'job_id', 'created_at', 'id'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey('jobs.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    admin_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    stage: Mapped[str] = mapped_column(ENUM(*STAGES))
    progress_percentage: Mapped[int] = mapped_column(TINYINT(unsigned=True))
    note: Mapped[str] = mapped_column(Text)
    event_type: Mapped[str] = mapped_column(ENUM('created', 'updated', 'note'), server_default=text("'note'"))
    job: Mapped[Job] = relationship(back_populates='milestones')
    admin: Mapped[User] = relationship(back_populates='milestones')


class JobAttachment(Timestamps, Base):
    """Exactly one parent: intake inquiry or converted job. Move on conversion."""
    __tablename__ = 'job_attachments'
    __table_args__ = (CheckConstraint('(job_id IS NOT NULL) + (inquiry_id IS NOT NULL) = 1', name='ck_attachment_parent'), CheckConstraint('size_bytes >= 0', name='ck_attachment_size'), Index('ix_attachments_job_created', 'job_id', 'created_at'), Index('ix_attachments_inquiry_created', 'inquiry_id', 'created_at'), OPTIONS)
    id: Mapped[int] = mapped_column(BIGINT(unsigned=True), primary_key=True, autoincrement=True)
    job_id: Mapped[int | None] = mapped_column(ForeignKey('jobs.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    inquiry_id: Mapped[int | None] = mapped_column(ForeignKey('inquiries.id', ondelete='RESTRICT', onupdate='RESTRICT'))
    uploaded_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL', onupdate='RESTRICT'))
    kind: Mapped[str] = mapped_column(ENUM('cad', 'schematic', 'drawing', 'qc_photo', 'other'))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_reference: Mapped[str] = mapped_column(String(2048))
    content_type: Mapped[str] = mapped_column(String(127))
    size_bytes: Mapped[int] = mapped_column(BIGINT(unsigned=True))
    sha256_digest: Mapped[bytes | None] = mapped_column(BINARY(32))
    job: Mapped[Job | None] = relationship(back_populates='attachments')
    inquiry: Mapped[Inquiry | None] = relationship(back_populates='attachments')
    uploader: Mapped[User | None] = relationship(back_populates='attachments')
