"""Swollen Hippo Industries rapid prototyping demo application."""

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
import os
from production import api as production_api

from database import initialize_database, tbl_inquiries, tbl_jobs

load_dotenv(Path(__file__).with_name(".env"), override=False)


@asynccontextmanager
async def app_lifespan(obj_app: FastAPI):
    """Initialize the schema at startup and release connections at shutdown."""
    obj_engine = initialize_database()
    obj_app.state.obj_engine = obj_engine
    obj_app.state.bool_production = os.environ.get('DATABASE_MODE', 'production' if obj_engine.dialect.name == 'mysql' else 'demo') == 'production'
    try:
        yield
    finally:
        obj_engine.dispose()


app = FastAPI(title="Swollen Hippo Industries", version="1.0.0", lifespan=app_lifespan)
app.include_router(production_api.obj_router)
_template_path = Path(__file__).parent / "templates" / "index.html"

_STAGES = ["Pending", "In Production", "Quality Check", "Shipped", "Completed"]


class Inquiry(BaseModel):
    customer_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    company: str = Field(min_length=2, max_length=120)
    service: str = Field(min_length=2, max_length=100)
    project_details: str = Field(min_length=10, max_length=4000)
    budget: str = Field(default="", max_length=80)


class JobUpdate(BaseModel):
    status: Literal["Pending", "In Production", "Quality Check", "Shipped", "Completed", 'intake', 'toolpathing_design', 'in_production', 'post_processing_qa', 'ready_to_ship', 'shipped', 'delivered', 'completed', 'cancelled']
    estimated_completion_date: date | None = None
    estimated_shipping_date: date | None = None
    progress_percentage: int | None = Field(default=None, ge=0, le=100)
    actual_completion_date: date | None = None
    actual_shipping_date: date | None = None
    carrier_name: str | None = Field(default=None, max_length=100)
    tracking_number: str | None = Field(default=None, max_length=128)
    tracking_url: str | None = Field(default=None, max_length=2048)
    version: int | None = Field(default=None, ge=1)


@app.get("/", response_class=HTMLResponse)
async def home() -> HTMLResponse:
    """Serve the single-page frontend."""
    if not _template_path.is_file():
        raise HTTPException(status_code=500, detail="Frontend template is missing")
    return HTMLResponse(_template_path.read_text(encoding="utf-8"))


@app.get('/production.js', include_in_schema=False)
def production_script():
    return FileResponse(Path(__file__).parent / 'templates' / 'production.js', media_type='application/javascript')


@app.post("/api/inquiry", status_code=201)
async def create_inquiry(payload: Inquiry, obj_request: Request) -> dict:
    """Save an inquiry and create its initial job record."""
    if obj_request.app.state.bool_production:
        return production_api.create_inquiry(payload, obj_request)
    str_id = str(uuid4())
    str_created = datetime.now(timezone.utc).isoformat()
    dict_inquiry = payload.model_dump(mode="json")
    dict_job = {
        "id": str_id,
        **dict_inquiry,
        "inquiry_id": str_id,
        "status": "Pending",
        "estimated_completion_date": None,
        "estimated_shipping_date": None,
        "created_at": str_created,
    }
    with obj_request.app.state.obj_engine.begin() as obj_connection:
        obj_connection.execute(tbl_inquiries.insert().values(id=str_id, **dict_inquiry))
        obj_connection.execute(tbl_jobs.insert().values(**dict_job))
    return {"message": "Inquiry received. Our team will be in touch soon.", "job": dict_job}


@app.get("/api/jobs")
async def list_jobs(
    obj_request: Request,
    role: Literal["customer", "admin"] = Query(default="customer"),
    x_user_role: str | None = Header(default=None),
) -> dict:
    """Return jobs visible to the selected demo role."""
    if obj_request.app.state.bool_production:
        return production_api.list_jobs(obj_request, role)
    if role == "admin" and x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    obj_query = select(tbl_jobs)
    if role != "admin":
        obj_query = obj_query.where(tbl_jobs.c.status != "Completed")
    lst_inquiries = []
    with obj_request.app.state.obj_engine.connect() as obj_connection:
        lst_jobs = [dict(obj_row) for obj_row in obj_connection.execute(obj_query).mappings()]
        if role == "admin":
            lst_inquiries = [dict(obj_row) for obj_row in
                             obj_connection.execute(select(tbl_inquiries)).mappings()]
    return {"jobs": lst_jobs, "inquiries": lst_inquiries}


@app.put("/api/jobs/{job_id}")
async def update_job(
    job_id: str,
    payload: JobUpdate,
    obj_request: Request,
    x_user_role: str | None = Header(default=None),
) -> dict:
    """Update job stage and schedule; the demo admin role is supplied by header."""
    if obj_request.app.state.bool_production:
        return production_api.update_job(job_id, payload, obj_request)
    if payload.status not in _STAGES:
        raise HTTPException(status_code=422, detail='Unsupported demo stage')
    if x_user_role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    with obj_request.app.state.obj_engine.begin() as obj_connection:
        obj_result = obj_connection.execute(
            tbl_jobs.update().where(tbl_jobs.c.id == job_id).values(**payload.model_dump(include={'status', 'estimated_completion_date', 'estimated_shipping_date'})))
        if obj_result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Job not found")
        dict_job = dict(obj_connection.execute(
            select(tbl_jobs).where(tbl_jobs.c.id == job_id)).mappings().one())
    return {"message": "Job updated", "job": dict_job}
