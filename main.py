"""Swollen Hippo Industries rapid prototyping demo application."""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select

from database import initialize_database, tbl_inquiries

load_dotenv(Path(__file__).with_name(".env"), override=False)


@asynccontextmanager
async def app_lifespan(obj_app: FastAPI):
    """Initialize the schema at startup and release connections at shutdown."""
    obj_engine = initialize_database()
    obj_app.state.obj_engine = obj_engine
    try:
        yield
    finally:
        obj_engine.dispose()


app = FastAPI(title="Swollen Hippo Industries", version="1.0.0", lifespan=app_lifespan)
_template_path = Path(__file__).parent / "templates" / "index.html"

_STAGES = ["Pending", "In Production", "Quality Check", "Shipped", "Completed"]
# Job tracking remains in memory; inquiry submissions are persisted in the database.
_jobs: list[dict] = []


class Inquiry(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str = Field(min_length=2, max_length=120)
    service: str = Field(min_length=2, max_length=100)
    project_details: str = Field(min_length=10, max_length=4000)
    budget: str = Field(default="", max_length=80)


class JobUpdate(BaseModel):
    status: Literal["Pending", "In Production", "Quality Check", "Shipped", "Completed"]
    estimated_completion_date: date | None = None
    estimated_shipping_date: date | None = None


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    """Serve the single-page frontend."""
    if not _template_path.is_file():
        raise HTTPException(status_code=500, detail="Frontend template is missing")
    return HTMLResponse(_template_path.read_text(encoding="utf-8"))


@app.post("/api/inquiry", status_code=201)
async def create_inquiry(payload: Inquiry, obj_request: Request) -> dict:
    """Save an inquiry and create its initial job record."""
    str_id = str(uuid4())
    str_created = datetime.now(timezone.utc).isoformat()
    dict_inquiry = payload.model_dump(mode="json")
    with obj_request.app.state.obj_engine.begin() as obj_connection:
        obj_connection.execute(tbl_inquiries.insert().values(id=str_id, **dict_inquiry))
    dict_inquiry.update({"id": str_id, "created_at": str_created})
    dict_job = {
        "id": str_id,
        **dict_inquiry,
        "status": "Pending",
        "estimated_completion_date": None,
        "estimated_shipping_date": None,
        "created_at": str_created,
    }
    _jobs.append(dict_job)
    return {"message": "Inquiry received. Our team will be in touch soon.", "job": dict_job}


@app.get("/api/jobs")
async def list_jobs(
    obj_request: Request,
    role: Literal["customer", "admin"] = Query(default="customer"),
    x_user_role: str | None = Header(default=None),
) -> dict:
    """Return jobs visible to the selected demo role."""
    if role == "admin" and x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    lst_jobs = _jobs if role == "admin" else [
        dict_job for dict_job in _jobs if dict_job["status"] != "Completed"
    ]
    lst_inquiries = []
    if role == "admin":
        with obj_request.app.state.obj_engine.connect() as obj_connection:
            lst_inquiries = [dict(obj_row) for obj_row in
                             obj_connection.execute(select(tbl_inquiries)).mappings()]
    return {"jobs": lst_jobs, "inquiries": lst_inquiries}


@app.put("/api/jobs/{job_id}")
async def update_job(
    job_id: str,
    payload: JobUpdate,
    x_user_role: str | None = Header(default=None),
) -> dict:
    """Update job stage and schedule; the demo admin role is supplied by header."""
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    dict_job = next((job for job in _jobs if job["id"] == job_id), None)
    if dict_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    dict_job.update(payload.model_dump(mode="json"))
    return {"message": "Job updated", "job": dict_job}
