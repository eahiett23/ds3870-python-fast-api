"""Swollen Hippo Industries rapid prototyping demo application."""

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, EmailStr, Field

import auth
from database import initialize_database

app = FastAPI(title="Swollen Hippo Industries", version="1.0.0")
app.state.obj_engine = initialize_database()
app.include_router(auth.obj_router)
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
    obj_request: Request,
) -> dict:
    """Return all jobs to staff or only this customer's active jobs."""
    dict_user = auth.get_current_user(obj_request)
    if dict_user["is_admin"]:
        return {"jobs": _jobs, "inquiries": _inquiries}
    lst_jobs = [
        dict_job for dict_job in _jobs
        if dict_job["email"].lower() == dict_user["email"].lower()
        and dict_job["status"] != "Completed"
    ]
    return {"jobs": lst_jobs, "inquiries": []}


@app.put("/api/jobs/{job_id}")
async def update_job(
    job_id: str,
    payload: JobUpdate,
    obj_request: Request,
) -> dict:
    """Update job stage and dates; only a staff session may write updates."""
    auth.require_admin(obj_request)
    dict_job = next((job for job in _jobs if job["id"] == job_id), None)
    if dict_job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    dict_job.update(payload.model_dump(mode="json"))
    return {"message": "Job updated", "job": dict_job}
