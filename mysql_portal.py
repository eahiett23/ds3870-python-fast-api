"""Staged MySQL backend compatible with the deployed cookie-based frontend.

Does not create schema or migrate data. Run as mysql_portal:app only after tests.
Requires a separate MYSQL_DATABASE_URL; never falls back to SQLite or root.
"""
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
import os
from pathlib import Path
import secrets
from uuid import uuid4

import bcrypt
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import MetaData, create_engine, delete, event, insert, select, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

COOKIE = "session_token"
STAGE_INPUT = {"Pending": "intake", "In Production": "in_production",
               "Quality Check": "post_processing_qa", "Shipped": "shipped", "Completed": "completed"}
STAGE_OUTPUT = {"intake": "Pending", "toolpathing_design": "Pending", "in_production": "In Production",
                "post_processing_qa": "Quality Check", "ready_to_ship": "Quality Check",
                "shipped": "Shipped", "delivered": "Shipped", "completed": "Completed", "cancelled": "Cancelled"}
SERVICES = {"Additive & Subtractive Manufacturing": "other", "Electronics Design & Development": "electronics",
            "Software Development": "software", "Digital & Industrial Design": "design", "Not sure yet": "other"}
DEFAULT_LABELS = {"3d_printing": "3D Printing", "cnc": "CNC Machining", "electronics": "Electronics Design & Development",
                  "software": "Software Development", "design": "Digital & Industrial Design", "other": "Not sure yet"}
DUMMY_HASH = bcrypt.hashpw(secrets.token_bytes(32), bcrypt.gensalt(rounds=12))


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def date_time(value):
    return datetime.combine(value, datetime.min.time()) if value else None


def date_string(value):
    return value.date().isoformat() if isinstance(value, datetime) else value.isoformat() if value else None


def user_json(row):
    return {"email": row["email"], "first_name": row["first_name"], "last_name": row["last_name"],
            "is_admin": row["role"] == "admin"}


def job_json(row, owner):
    return {
        "id": row["legacy_id"] or str(row["id"]), "customer_email": owner["email"],
        "customer_name": row["contact_name"] or (owner["first_name"] + " " + owner["last_name"]),
        "email": row["contact_email"] or owner["email"], "company": row["company_name"] or "",
        "service": row["service_label"] or DEFAULT_LABELS[row["service_type"]],
        "project_details": row["description"], "budget": row["budget_text"] or "",
        "status": STAGE_OUTPUT[row["status"]], "lifecycle_stage": row["status"],
        "progress_percentage": row["progress_percentage"],
        "estimated_completion_date": date_string(row["target_completion_at"]),
        "estimated_shipping_date": date_string(row["estimated_ship_at"]),
        "actual_completion_date": date_string(row["actual_completion_at"]),
        "actual_ship_date": date_string(row["actual_ship_at"]), "carrier": row["carrier_name"],
        "tracking_number": row["tracking_number"], "tracking_url": row["tracking_url"],
        "created_at": row["created_at"].isoformat(), "version": row["version"], "record_type": "job",
    }


def inquiry_json(row, owner):
    return {"id": "inq-" + str(row["id"]), "customer_email": owner["email"] if owner else row["contact_email"],
            "customer_name": row["contact_name"], "email": row["contact_email"], "company": row["company_name"] or "",
            "service": row["service_label"] or DEFAULT_LABELS[row["inquiry_type"]],
            "project_details": row["description"], "budget": row["budget_text"] or "",
            "status": "Pending", "lifecycle_stage": "intake", "progress_percentage": 0,
            "estimated_completion_date": date_string(row["target_completion_at"]),
            "estimated_shipping_date": None, "created_at": row["created_at"].isoformat(),
            "record_type": "inquiry", "review_status": row["status"]}


def initialize_database():
    raw = os.environ.get("MYSQL_DATABASE_URL")
    if not raw:
        raise RuntimeError("MYSQL_DATABASE_URL is required; no database changes made")
    url = make_url(raw)
    if url.drivername != "mysql+pymysql" or url.database != "swollenhippo_db" or url.username == "root":
        raise RuntimeError("Use mysql+pymysql with swollenhippo_db and a restricted application account")
    engine = create_engine(url, pool_pre_ping=True, pool_size=2, max_overflow=1,
                           pool_timeout=10, pool_recycle=900, hide_parameters=True)

    @event.listens_for(engine, "checkout")
    def reset_context(connection, record, proxy):
        with connection.cursor() as cursor:
            cursor.execute("SET time_zone = '+00:00'")
            cursor.execute("SET @app_actor_id = NULL")

    metadata = MetaData()
    try:
        metadata.reflect(engine, only=["users", "user_sessions", "inquiries", "jobs", "job_milestones", "job_attachments"])
        with engine.connect() as connection:
            count = connection.exec_driver_sql("CALL production_schema_ready()").scalar_one()
            if count != 8:
                raise RuntimeError("Required audit triggers are missing")
        for table in ("inquiries", "jobs"):
            if not {"service_label", "budget_text"} <= set(metadata.tables[table].c.keys()):
                raise RuntimeError("Compatibility columns are missing")
    except Exception:
        engine.dispose()
        raise
    return engine, metadata.tables


@asynccontextmanager
async def lifespan(application):
    application.state.engine, application.state.tables = initialize_database()
    try:
        yield
    finally:
        application.state.engine.dispose()


app = FastAPI(title="Swollen Hippo Industries", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def same_origin(request: Request, call_next):
    # Cookie-authenticated writes must originate from our own site.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != str(request.base_url).rstrip("/")):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "Cross-origin write refused"}, status_code=403)
    return await call_next(request)


def current_user(request, optional=False):
    token = request.cookies.get(COOKIE)
    if not token and optional:
        return None
    if not token:
        raise HTTPException(401, "Not logged in")
    users, sessions = request.app.state.tables["users"], request.app.state.tables["user_sessions"]
    query = select(users).join(sessions, sessions.c.user_id == users.c.id).where(
        sessions.c.token_digest == hashlib.sha256(token.encode()).digest(), sessions.c.expires_at > now(),
        sessions.c.revoked_at.is_(None), users.c.is_active == 1)
    with request.app.state.engine.connect() as connection:
        row = connection.execute(query).mappings().first()
    if row is None:
        raise HTTPException(401, "Not logged in")
    return dict(row)


def admin_user(request):
    user = current_user(request)
    if user["role"] != "admin":
        raise HTTPException(403, "Admin role required")
    return user


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)


class LoginBody(BaseModel):
    email: str
    password: str


class InquiryBody(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str = Field(min_length=2, max_length=120)
    service: str = Field(min_length=2, max_length=100)
    project_details: str = Field(min_length=10, max_length=4000)
    budget: str = Field(default="", max_length=80)


class JobUpdate(BaseModel):
    status: str
    estimated_completion_date: date | None = None
    estimated_shipping_date: date | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    actual_completion_date: date | None = None
    actual_ship_date: date | None = None
    carrier: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=128)
    tracking_url: str | None = Field(default=None, max_length=2048)
    public_note: str | None = Field(default=None, min_length=1, max_length=4000)
    version: int | None = Field(default=None, ge=1)


@app.get("/")
def home():
    path = Path(os.environ.get("APP_TEMPLATE_PATH", str(Path(__file__).parent / "templates" / "index.html")))
    if not path.is_file():
        raise HTTPException(500, "Frontend template is missing")
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/healthz")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: RegisterBody, request: Request):
    if len(body.password) < 10 or len(body.password.encode()) > 72:
        raise HTTPException(400, "Password must have at least 10 characters and at most 72 UTF-8 bytes")
    if not body.first_name.strip() or not body.last_name.strip():
        raise HTTPException(400, "Enter your first and last name")
    try:
        with request.app.state.engine.begin() as connection:
            # Column-level grants exclude role/is_active. Server defaults create a customer.
            connection.execute(insert(request.app.state.tables["users"]).values(
                email=str(body.email).lower(), first_name=body.first_name.strip(), last_name=body.last_name.strip(),
                password_hash=bcrypt.hashpw(body.password.encode(), bcrypt.gensalt(rounds=12)).decode()))
    except IntegrityError:
        raise HTTPException(400, "Could not create account")
    return {"message": "Account created"}


@app.post("/api/auth/login")
def login(body: LoginBody, request: Request, response: Response):
    users, sessions = request.app.state.tables["users"], request.app.state.tables["user_sessions"]
    with request.app.state.engine.connect() as connection:
        user = connection.execute(select(users).where(users.c.email == body.email.strip().lower())).mappings().first()
    valid = False
    if len(body.password.encode()) <= 72:
        try:
            saved_hash = user["password_hash"].encode() if user and user["is_active"] else DUMMY_HASH
            valid = bcrypt.checkpw(body.password.encode(), saved_hash) and bool(user and user["is_active"])
        except ValueError:
            pass
    if not valid:
        raise HTTPException(401, "Invalid email or password")
    token = secrets.token_urlsafe(32)
    timestamp = now()
    with request.app.state.engine.begin() as connection:
        connection.execute(delete(sessions).where(sessions.c.expires_at <= timestamp))
        connection.execute(insert(sessions).values(user_id=user["id"], token_digest=hashlib.sha256(token.encode()).digest(),
                                                  created_at=timestamp, expires_at=timestamp + timedelta(hours=8)))
    response.set_cookie(COOKIE, token, httponly=True, secure=os.environ.get("COOKIE_SECURE", "true").lower() == "true",
                        samesite="lax", max_age=8 * 3600)
    return user_json(user)


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        sessions = request.app.state.tables["user_sessions"]
        with request.app.state.engine.begin() as connection:
            connection.execute(delete(sessions).where(sessions.c.token_digest == hashlib.sha256(token.encode()).digest()))
    response.delete_cookie(COOKIE, secure=os.environ.get("COOKIE_SECURE", "true").lower() == "true", httponly=True, samesite="lax")
    return {"message": "Logged out"}


@app.get("/api/auth/me")
def me(request: Request):
    return user_json(current_user(request))


def submit(body, request, public=False):
    user = current_user(request, optional=public)
    if user and str(body.email).lower() != user["email"].lower():
        raise HTTPException(400, "Use the email address on your account")
    if body.service not in SERVICES:
        raise HTTPException(422, "Unknown service category")
    inquiries = request.app.state.tables["inquiries"]
    with request.app.state.engine.begin() as connection:
        result = connection.execute(insert(inquiries).values(
            customer_id=user["id"] if user else None, contact_name=body.customer_name,
            contact_email=str(body.email).lower(), company_name=body.company, inquiry_type=SERVICES[body.service],
            service_label=body.service, description=body.project_details, budget_text=body.budget))
        row = connection.execute(select(inquiries).where(inquiries.c.id == result.inserted_primary_key[0])).mappings().one()
    return {"message": "Inquiry received. Our team will be in touch soon.", "job": inquiry_json(row, user)}


@app.post("/api/inquiry", status_code=201)
def create_inquiry(body: InquiryBody, request: Request):
    return submit(body, request)


@app.post("/api/inquiries", status_code=201)
def public_inquiry(body: InquiryBody, request: Request):
    return submit(body, request, public=True)


@app.get("/api/jobs")
def list_jobs(request: Request, include_archived: bool = False):
    user = current_user(request)
    tables = request.app.state.tables
    jobs, inquiries, users = tables["jobs"], tables["inquiries"], tables["users"]
    query = select(jobs)
    if not include_archived:
        query = query.where(jobs.c.archived_at.is_(None))
    pending = select(inquiries).where(inquiries.c.status.in_(["pending", "reviewed", "quoted"]))
    if user["role"] != "admin":
        query = query.where(jobs.c.customer_id == user["id"])
        pending = pending.where(inquiries.c.customer_id == user["id"])
    with request.app.state.engine.connect() as connection:
        rows = connection.execute(query).mappings().all()
        intake = connection.execute(pending).mappings().all()
        ids = {row["customer_id"] for row in rows + intake if row["customer_id"] is not None}
        owners = {row["id"]: row for row in connection.execute(select(users).where(users.c.id.in_(ids))).mappings()} if ids else {}
    result = [job_json(row, owners[row["customer_id"]]) for row in rows]
    intake_result = [inquiry_json(row, owners.get(row["customer_id"])) for row in intake]
    result.extend(intake_result)
    result.sort(key=lambda row: row["created_at"], reverse=True)
    return {"jobs": result, "inquiries": intake_result if user["role"] == "admin" else []}


def resolve_job(connection, jobs, identifier):
    if identifier.isdecimal():
        query = select(jobs).where(jobs.c.id == int(identifier))
    else:
        query = select(jobs).where(jobs.c.legacy_id == identifier)
    return connection.execute(query.with_for_update()).mappings().first()


@app.put("/api/jobs/{job_id}")
def update_job(job_id: str, body: JobUpdate, request: Request):
    actor = admin_user(request)
    if body.status not in STAGE_INPUT:
        raise HTTPException(422, "Unknown dashboard stage")
    stage = STAGE_INPUT[body.status]
    tables = request.app.state.tables
    jobs, users, inquiries = tables["jobs"], tables["users"], tables["inquiries"]
    with request.app.state.engine.begin() as connection:
        connection.exec_driver_sql("SET @app_actor_id = %s", (actor["id"],))
        if job_id.startswith("inq-"):
            if not job_id[4:].isdecimal():
                raise HTTPException(404, "Inquiry not found")
            inquiry = connection.execute(select(inquiries).where(inquiries.c.id == int(job_id[4:])).with_for_update()).mappings().first()
            if inquiry is None:
                raise HTTPException(404, "Inquiry not found")
            if inquiry["status"] not in {"pending", "reviewed", "quoted"}:
                raise HTTPException(409, "Inquiry is already converted or rejected; refresh the board")
            owner = connection.execute(select(users).where(users.c.id == inquiry["customer_id"])).mappings().first()
            if owner is None or owner["role"] != "customer" or not owner["is_active"]:
                raise HTTPException(409, "Assign an active customer before converting this inquiry")
            result = connection.execute(insert(jobs).values(
                job_number=uuid4().hex, customer_id=owner["id"], inquiry_id=inquiry["id"], title=inquiry["contact_name"] + " prototype",
                description=inquiry["description"], service_type=inquiry["inquiry_type"], service_label=inquiry["service_label"],
                budget_text=inquiry["budget_text"], contact_name=inquiry["contact_name"], contact_email=inquiry["contact_email"],
                company_name=inquiry["company_name"], updated_by_admin_id=actor["id"]))
            connection.execute(update(inquiries).where(inquiries.c.id == inquiry["id"]).values(status="converted"))
            # Carry over inquiry attachments atomically during conversion.
            attachments = tables["job_attachments"]
            connection.execute(update(attachments).where(attachments.c.inquiry_id == inquiry["id"]).values(
                inquiry_id=None, job_id=result.inserted_primary_key[0]))
            row = connection.execute(select(jobs).where(jobs.c.id == result.inserted_primary_key[0])).mappings().one()
        else:
            row = resolve_job(connection, jobs, job_id)
            if row is None:
                raise HTTPException(404, "Job not found")
            owner = connection.execute(select(users).where(users.c.id == row["customer_id"])).mappings().one()
        if body.version is not None and body.version != row["version"]:
            raise HTTPException(409, "Job changed; refresh before saving")
        values = {"status": stage, "target_completion_at": date_time(body.estimated_completion_date),
                  "estimated_ship_at": date_time(body.estimated_shipping_date), "version": row["version"] + 1,
                  "updated_by_admin_id": actor["id"]}
        if body.progress_percentage is not None:
            values["progress_percentage"] = body.progress_percentage
        for input_key, column in (("actual_completion_date", "actual_completion_at"), ("actual_ship_date", "actual_ship_at")):
            if input_key in body.model_fields_set:
                values[column] = date_time(getattr(body, input_key))
        for input_key, column in (("carrier", "carrier_name"), ("tracking_number", "tracking_number"), ("tracking_url", "tracking_url")):
            if input_key in body.model_fields_set:
                values[column] = getattr(body, input_key)
        if body.tracking_url and not body.tracking_url.startswith("https://"):
            raise HTTPException(422, "Tracking URL must use HTTPS")
        if stage == "shipped" and not values.get("actual_ship_at", row["actual_ship_at"]):
            values["actual_ship_at"] = now()
        if stage == "completed":
            if body.progress_percentage not in {None, 100}:
                raise HTTPException(422, "Completed jobs require 100 percent progress")
            values["progress_percentage"] = 100
            if not values.get("actual_completion_at", row["actual_completion_at"]):
                values["actual_completion_at"] = now()
        connection.execute(update(jobs).where(jobs.c.id == row["id"]).values(**values))
        if body.public_note:
            connection.execute(insert(tables["job_milestones"]).values(job_id=row["id"], admin_id=actor["id"],
                stage=stage, progress_percentage=values.get("progress_percentage", row["progress_percentage"]),
                note=body.public_note, event_type="note"))
        final = connection.execute(select(jobs).where(jobs.c.id == row["id"])).mappings().one()
    return {"message": "Job updated", "job": job_json(final, owner)}


@app.get("/api/jobs/{job_id}/milestones")
def milestones(job_id: str, request: Request):
    user = current_user(request)
    jobs, logs = request.app.state.tables["jobs"], request.app.state.tables["job_milestones"]
    condition = jobs.c.id == int(job_id) if job_id.isdecimal() else jobs.c.legacy_id == job_id
    query = select(jobs).where(condition)
    if user["role"] != "admin":
        query = query.where(jobs.c.customer_id == user["id"])
    with request.app.state.engine.connect() as connection:
        job = connection.execute(query).mappings().first()
        if job is None:
            raise HTTPException(404, "Job not found")
        rows = connection.execute(select(logs).where(logs.c.job_id == job["id"]).order_by(logs.c.created_at, logs.c.id)).mappings().all()
    return {"milestones": [dict(row) for row in rows]}
