"""Adapter between the existing JSON UI contract and the production schema."""
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.exc import StaleDataError
from .models import User, UserSession, Inquiry, Job, JobMilestone, STAGES

obj_router = APIRouter()
obj_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
str_dummy_hash = obj_hasher.hash(secrets.token_urlsafe(24))
dict_services = {
    '3D Printing': '3d_printing', 'CNC Machining': 'cnc',
    'Additive & Subtractive Manufacturing': '3d_printing',
    'Electronics Design & Development': 'electronics',
    'Software Development': 'software', 'Digital & Industrial Design': 'design',
    **{str_service: str_service for str_service in ('3d_printing', 'cnc', 'electronics', 'software', 'design')},
}
dict_labels = {'3d_printing': '3D Printing', 'cnc': 'CNC Machining', 'electronics': 'Electronics Design & Development', 'software': 'Software Development', 'design': 'Digital & Industrial Design'}


def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def require_production(obj_request):
    if not obj_request.app.state.bool_production:
        raise HTTPException(404, 'This endpoint requires production mode')


def authenticate(obj_request, obj_session, bool_optional=False):
    str_token = obj_request.cookies.get('session_token')
    if not str_token and bool_optional:
        return None
    if not str_token or len(str_token) != 43:
        raise HTTPException(401, 'Sign in required')
    obj_digest = hashlib.sha256(str_token.encode()).digest()
    obj_user = obj_session.scalar(select(User).join(UserSession).where(
        UserSession.token_digest == obj_digest, UserSession.revoked_at.is_(None),
        UserSession.expires_at > utc_now(), User.is_active == 1))
    if obj_user is None:
        raise HTTPException(401, 'Session invalid or expired')
    return obj_user


def require_admin(obj_user):
    if obj_user.role != 'admin':
        raise HTTPException(403, 'Admin role required')


@contextmanager
def admin_actor(obj_session, int_actor):
    # Test adapters use SQLite without pretending that MySQL triggers were tested.
    bool_mysql = obj_session.bind.dialect.name == 'mysql'
    if bool_mysql:
        obj_session.execute(text('SET @app_actor_id = :actor'), {'actor': int_actor})
    try:
        yield
        obj_session.flush()
    finally:
        if bool_mysql:
            # A failed flush requires rollback before clearing the pooled connection.
            if not obj_session.is_active:
                obj_session.rollback()
            obj_session.execute(text('SET @app_actor_id = NULL'))


def serialize_job(obj_job):
    obj_customer = obj_job.customer
    return {
        'id': str(obj_job.id), 'inquiry_id': str(obj_job.inquiry_id) if obj_job.inquiry_id else None,
        'job_number': obj_job.job_number, 'title': obj_job.title,
        'customer_name': f'{obj_customer.first_name} {obj_customer.last_name}',
        'email': obj_customer.email, 'company': obj_customer.company_name or '',
        'service': dict_labels[obj_job.service_type], 'project_details': obj_job.description,
        'status': obj_job.status, 'progress_percentage': obj_job.progress_percentage,
        'estimated_completion_date': obj_job.target_completion_at.date().isoformat() if obj_job.target_completion_at else None,
        'estimated_shipping_date': obj_job.estimated_ship_at.date().isoformat() if obj_job.estimated_ship_at else None,
        'actual_completion_date': obj_job.actual_completion_at.date().isoformat() if obj_job.actual_completion_at else None,
        'actual_shipping_date': obj_job.actual_ship_at.date().isoformat() if obj_job.actual_ship_at else None,
        'carrier_name': obj_job.carrier_name, 'tracking_number': obj_job.tracking_number,
        'tracking_url': obj_job.tracking_url, 'version': obj_job.version,
        'created_at': obj_job.created_at.isoformat(),
        'archived_at': obj_job.archived_at.isoformat() if obj_job.archived_at else None,
    }


class Login(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=1024)


@obj_router.get('/api/config')
def configuration(obj_request: Request):
    return {'mode': 'production' if obj_request.app.state.bool_production else 'demo', 'stages': list(STAGES) if obj_request.app.state.bool_production else ['Pending', 'In Production', 'Quality Check', 'Shipped', 'Completed']}


def login(payload: Login, obj_request: Request, obj_response: Response):
    require_production(obj_request)
    with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
        obj_user = obj_session.scalar(select(User).where(User.email == str(payload.email).strip().lower()))
        try:
            bool_valid = obj_hasher.verify(obj_user.password_hash if obj_user else str_dummy_hash, payload.password)
        except (VerificationError, InvalidHashError):
            bool_valid = False
        if not bool_valid or obj_user is None or not obj_user.is_active:
            raise HTTPException(401, 'Invalid email or password')
        str_token = secrets.token_urlsafe(32)
        obj_session.add(UserSession(user_id=obj_user.id, token_digest=hashlib.sha256(str_token.encode()).digest(), expires_at=utc_now()+timedelta(hours=8)))
        from auth import bool_cookie_secure
        str_old_token = obj_request.cookies.get('session_token')
        if str_old_token:
            obj_old = obj_session.scalar(select(UserSession).where(UserSession.token_digest == hashlib.sha256(str_old_token.encode()).digest()))
            if obj_old:
                obj_old.revoked_at = utc_now()
        obj_response.set_cookie('session_token', str_token, httponly=True,
                                secure=bool_cookie_secure, samesite='lax', path='/', max_age=28800)
        return serialize_user(obj_user)


def serialize_user(obj_user):
    return {'email': obj_user.email, 'first_name': obj_user.first_name,
            'last_name': obj_user.last_name, 'role': obj_user.role,
            'is_admin': obj_user.role == 'admin'}


def register(payload, obj_request):
    require_production(obj_request)
    str_first = payload.first_name.strip()
    str_last = payload.last_name.strip()
    if not str_first or not str_last:
        raise HTTPException(400, 'Enter your first and last name')
    str_hash = obj_hasher.hash(payload.password)
    try:
        with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
            obj_session.add(User(email=str(payload.email).strip().lower(),
                                 first_name=str_first, last_name=str_last,
                                 password_hash=str_hash, role='customer', is_active=1))
    except IntegrityError:
        raise HTTPException(400, 'Could not create account') from None
    return {'message': 'Account created'}


def me(obj_request):
    require_production(obj_request)
    with Session(obj_request.app.state.obj_engine) as obj_session:
        return serialize_user(authenticate(obj_request, obj_session))


def logout(obj_request: Request, obj_response: Response):
    require_production(obj_request)
    str_token = obj_request.cookies.get('session_token')
    if str_token:
        with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
            obj_record = obj_session.scalar(select(UserSession).where(
                UserSession.token_digest == hashlib.sha256(str_token.encode()).digest()))
            if obj_record:
                obj_record.revoked_at = utc_now()
    from auth import bool_cookie_secure
    obj_response.delete_cookie('session_token', path='/', secure=bool_cookie_secure,
                               httponly=True, samesite='lax')
    return {'message': 'Signed out'}


def create_inquiry(payload, obj_request):
    str_service = dict_services.get(payload.service)
    if str_service is None:
        raise HTTPException(422, 'Choose 3D Printing, CNC Machining, electronics, software or design')
    str_budget = payload.budget.strip()
    obj_budget = None
    if str_budget:
        try:
            obj_budget = Decimal(str_budget.replace('$', '').replace(',', ''))
            if not obj_budget.is_finite() or obj_budget < 0 or obj_budget >= Decimal('10000000000') or obj_budget.as_tuple().exponent < -2:
                raise HTTPException(422, 'Budget must be a non-negative amount with at most two decimals')
        except InvalidOperation:
            # Existing frontend sends budget ranges. Preserve them verbatim, not as invented amounts.
            pass
    with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
        obj_user = authenticate(obj_request, obj_session)
        obj_inquiry = Inquiry(customer_id=obj_user.id if obj_user and obj_user.role == 'customer' else None,
            contact_name=f'{obj_user.first_name} {obj_user.last_name}', contact_email=obj_user.email,
            company_name=payload.company, inquiry_type=str_service,
            description=payload.project_details + (f'\nBudget preference: {str_budget}' if str_budget and obj_budget is None else ''), target_budget=obj_budget)
        obj_session.add(obj_inquiry)
        obj_session.flush()
        return {'message': 'Inquiry received. Our team will review it before creating a job.', 'inquiry_id': str(obj_inquiry.id)}


def list_jobs(obj_request, str_role):
    with Session(obj_request.app.state.obj_engine) as obj_session:
        obj_user = authenticate(obj_request, obj_session)
        if str_role == 'admin':
            require_admin(obj_user)
        obj_query = select(Job).options(joinedload(Job.customer)).order_by(Job.created_at.desc(), Job.id.desc()).limit(200)
        if str_role != 'admin':
            obj_query = obj_query.where(Job.customer_id == obj_user.id)
        lst_jobs = [serialize_job(obj_job) for obj_job in obj_session.scalars(obj_query)]
        lst_inquiries = []
        if str_role == 'admin':
            lst_inquiries = [{'id': str(obj_item.id), 'customer_name': obj_item.contact_name, 'email': obj_item.contact_email,
                'company': obj_item.company_name, 'service': dict_labels[obj_item.inquiry_type],
                'project_details': obj_item.description, 'status': obj_item.status,
                'customer_id': obj_item.customer_id} for obj_item in obj_session.scalars(select(Inquiry).order_by(Inquiry.id.desc()).limit(200))]
        return {'jobs': lst_jobs, 'inquiries': lst_inquiries}


def numeric_id(str_value):
    if not str_value.isdecimal() or len(str_value) > 20:
        raise HTTPException(404, 'Record not found')
    return int(str_value)


def update_job(str_job_id, payload, obj_request):
    if payload.status not in STAGES:
        raise HTTPException(422, 'Use a production lifecycle stage')
    if payload.version is None:
        raise HTTPException(422, 'Current job version required')
    try:
        with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
            obj_user = authenticate(obj_request, obj_session)
            require_admin(obj_user)
            obj_job = obj_session.get(Job, numeric_id(str_job_id))
            if obj_job is None:
                raise HTTPException(404, 'Job not found')
            if obj_job.version != payload.version:
                raise HTTPException(409, 'Job changed; reload before saving')
            with admin_actor(obj_session, obj_user.id):
                obj_job.updated_by_admin_id = obj_user.id
                obj_job.status = payload.status
                for str_source, str_target in [('estimated_completion_date', 'target_completion_at'), ('estimated_shipping_date', 'estimated_ship_at'), ('actual_completion_date', 'actual_completion_at'), ('actual_shipping_date', 'actual_ship_at')]:
                    if str_source in payload.model_fields_set:
                        obj_value = getattr(payload, str_source)
                        setattr(obj_job, str_target, datetime.combine(obj_value, time()) if obj_value else None)
                for str_field in ('progress_percentage', 'carrier_name', 'tracking_number', 'tracking_url'):
                    if str_field in payload.model_fields_set:
                        obj_value = getattr(payload, str_field)
                        if str_field == 'progress_percentage' and obj_value is None:
                            raise HTTPException(422, 'Progress cannot be null')
                        if str_field == 'tracking_url' and obj_value and not obj_value.startswith('https://'):
                            raise HTTPException(422, 'Tracking URL must use HTTPS')
                        setattr(obj_job, str_field, obj_value)
                if obj_job.status == 'completed' and (obj_job.progress_percentage != 100 or obj_job.actual_completion_at is None):
                    raise HTTPException(422, 'Completion requires 100% progress and actual completion date')
                if obj_job.status in {'shipped', 'delivered'} and obj_job.actual_ship_at is None:
                    raise HTTPException(422, 'Actual shipping date required')
            return {'message': 'Job updated', 'job': serialize_job(obj_job)}
    except StaleDataError:
        raise HTTPException(409, 'Job changed; reload before saving')


class Conversion(BaseModel):
    customer_id: int = Field(gt=0)
    title: str = Field(min_length=2, max_length=240)


@obj_router.post('/api/inquiries/{inquiry_id}/convert', status_code=201)
def convert_inquiry(inquiry_id: str, payload: Conversion, obj_request: Request):
    require_production(obj_request)
    with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
        obj_user = authenticate(obj_request, obj_session)
        require_admin(obj_user)
        obj_inquiry = obj_session.scalar(select(Inquiry).where(Inquiry.id == numeric_id(inquiry_id)).with_for_update())
        if obj_inquiry is None:
            raise HTTPException(404, 'Inquiry not found')
        if obj_inquiry.status in {'converted', 'rejected'}:
            raise HTTPException(409, 'Inquiry cannot be converted')
        obj_customer = obj_session.get(User, payload.customer_id)
        if obj_customer is None or obj_customer.role != 'customer' or not obj_customer.is_active:
            raise HTTPException(422, 'Active customer account required')
        if obj_inquiry.customer_id is not None and obj_inquiry.customer_id != obj_customer.id:
            raise HTTPException(422, 'Inquiry belongs to a different customer')
        with admin_actor(obj_session, obj_user.id):
            obj_job = Job(job_number='SH-' + secrets.token_hex(10).upper(), customer_id=obj_customer.id,
                inquiry_id=obj_inquiry.id, title=payload.title, description=obj_inquiry.description,
                service_type=obj_inquiry.inquiry_type, updated_by_admin_id=obj_user.id,
                target_completion_at=obj_inquiry.target_completion_at)
            obj_session.add(obj_job)
            obj_session.flush()
            for obj_attachment in obj_inquiry.attachments:
                obj_attachment.inquiry_id = None
                obj_attachment.job_id = obj_job.id
            obj_inquiry.customer_id = obj_customer.id
            obj_inquiry.status = 'converted'
        return {'job': serialize_job(obj_job)}


@obj_router.get('/api/jobs/{job_id}/milestones')
def milestones(job_id: str, obj_request: Request):
    require_production(obj_request)
    with Session(obj_request.app.state.obj_engine) as obj_session:
        obj_user = authenticate(obj_request, obj_session)
        obj_job = obj_session.get(Job, numeric_id(job_id))
        if obj_job is None or (obj_user.role != 'admin' and obj_job.customer_id != obj_user.id):
            raise HTTPException(404, 'Job not found')
        return {'milestones': [{'id': obj_item.id, 'stage': obj_item.stage, 'progress_percentage': obj_item.progress_percentage,
            'note': obj_item.note, 'created_at': obj_item.created_at.isoformat()} for obj_item in obj_session.scalars(select(JobMilestone).where(JobMilestone.job_id == obj_job.id).order_by(JobMilestone.created_at, JobMilestone.id).limit(500))]}


class MilestoneNote(BaseModel):
    note: str = Field(min_length=1, max_length=10000)


@obj_router.post('/api/jobs/{job_id}/milestones', status_code=201)
def add_milestone(job_id: str, payload: MilestoneNote, obj_request: Request):
    require_production(obj_request)
    with Session(obj_request.app.state.obj_engine) as obj_session, obj_session.begin():
        obj_user = authenticate(obj_request, obj_session)
        require_admin(obj_user)
        obj_job = obj_session.scalar(select(Job).where(Job.id == numeric_id(job_id)).with_for_update())
        if obj_job is None:
            raise HTTPException(404, 'Job not found')
        with admin_actor(obj_session, obj_user.id):
            obj_record = JobMilestone(job_id=obj_job.id, admin_id=obj_user.id, stage=obj_job.status, progress_percentage=obj_job.progress_percentage, note=payload.note)
            obj_session.add(obj_record)
        return {'message': 'Note added', 'milestone_id': obj_record.id}

