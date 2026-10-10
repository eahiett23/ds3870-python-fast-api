"""Swollen Hippo Industries rapid prototyping demo application."""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

from database import initialize_database


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
# In-memory storage is intentionally used for this prototype; restarting clears data.
_jobs: list[dict] = []
_inquiries: list[dict] = []


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
async def create_inquiry(payload: Inquiry) -> dict:
    """Save an inquiry and create its initial job record."""
    str_id = str(uuid4())
    str_created = datetime.now(timezone.utc).isoformat()
    dict_inquiry = payload.model_dump(mode="json")
    dict_inquiry.update({"id": str_id, "created_at": str_created})
    dict_job = {
        "id": str_id,
        **dict_inquiry,
        "status": "Pending",
        "estimated_completion_date": None,
        "estimated_shipping_date": None,
        "created_at": str_created,
    }
    _inquiries.append(dict_inquiry)
    _jobs.append(dict_job)
    return {"message": "Inquiry received. Our team will be in touch soon.", "job": dict_job}


@app.get("/api/jobs")
async def list_jobs(
    role: Literal["customer", "admin"] = Query(default="customer"),
    x_user_role: str | None = Header(default=None),
) -> dict:
    """Return jobs visible to the selected demo role."""
    if role == "admin" and x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    lst_jobs = _jobs if role == "admin" else [
        dict_job for dict_job in _jobs if dict_job["status"] != "Completed"
    ]
    return {"jobs": lst_jobs, "inquiries": _inquiries if role == "admin" else []}


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
