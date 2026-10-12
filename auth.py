"""Login system for Swollen Hippo Industries.

How it works:
1. The user logs in with an email and a password.
2. We make a random token and save a scrambled copy of it in the sessions table.
3. The real token goes to the browser as a cookie that JavaScript cannot read.
4. On each request the browser sends the cookie and we look up who it is.
5. Logging out deletes the session, so the cookie stops working right away.

Admin (staff) means is_admin is True. Sign up always makes a normal customer.

Other files can use these two functions:
    auth.get_current_user(obj_request)  - any logged in user
    auth.require_admin(obj_request)     - admin only
"""
import hashlib
import os
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, insert, select
from sqlalchemy.exc import IntegrityError

from database import tbl_sessions, tbl_users

str_cookie_name = "session_token"
int_session_hours = 8
int_bcrypt_rounds = 12  # the tests lower this so they run faster

obj_router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterBody(BaseModel):
    email: EmailStr
    password: str
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)


class LoginBody(BaseModel):
    email: str
    password: str


def get_utc_now():
    # The database stores times without a timezone, so we always use UTC
    return datetime.now(timezone.utc).replace(tzinfo=None)


def hash_password(str_password):
    return bcrypt.hashpw(str_password.encode(), bcrypt.gensalt(rounds=int_bcrypt_rounds)).decode()


def hash_token(str_token):
    # We only save this scrambled copy, never the real token
    return hashlib.sha256(str_token.encode()).hexdigest()


def get_password_problem(str_password):
    # Gives back a message if the password is not allowed, or None if it is fine
    if len(str_password) < 10:
        return "Password must be at least 10 characters"
    # bcrypt only uses the first 72 bytes, so longer passwords are not allowed
    if len(str_password.encode()) > 72:
        return "Password is too long (72 bytes at most)"
    return None


def check_password(str_password, str_saved_hash):
    byt_password = str_password.encode()
    if len(byt_password) > 72:
        return False
    try:
        return bcrypt.checkpw(byt_password, str_saved_hash.encode())
    except ValueError:
        # The saved value is not a bcrypt hash
        return False


def get_current_user(obj_request: Request):
    """Gives back the logged in user, or stops with error 401."""
    str_token = obj_request.cookies.get(str_cookie_name)
    if not str_token:
        raise HTTPException(status_code=401, detail="Not logged in")

    # Find the session and skip it if it has expired
    obj_query = (
        select(tbl_users.c.email, tbl_users.c.first_name, tbl_users.c.last_name, tbl_users.c.is_admin)
        .select_from(tbl_users.join(tbl_sessions, tbl_sessions.c.user_email == tbl_users.c.email))
        .where(tbl_sessions.c.token_hash == hash_token(str_token))
        .where(tbl_sessions.c.expires_at > get_utc_now())
    )
    with obj_request.app.state.obj_engine.connect() as obj_connection:
        obj_row = obj_connection.execute(obj_query).mappings().first()

    if obj_row is None:
        raise HTTPException(status_code=401, detail="Not logged in")
    return dict(obj_row)


def require_admin(obj_request: Request):
    """Gives back the logged in user if they are an admin, or stops with error 401 or 403."""
    dict_user = get_current_user(obj_request)
    if not dict_user["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin role required")
    return dict_user


@obj_router.post("/register", status_code=201)
def register(obj_body: RegisterBody, obj_request: Request) -> dict:
    str_email = obj_body.email.strip().lower()
    str_first_name = obj_body.first_name.strip()
    str_last_name = obj_body.last_name.strip()

    str_problem = get_password_problem(obj_body.password)
    if str_problem:
        raise HTTPException(status_code=400, detail=str_problem)
    if not str_first_name or not str_last_name:
        raise HTTPException(status_code=400, detail="Enter your first and last name")

    try:
        with obj_request.app.state.obj_engine.begin() as obj_connection:
            # is_admin is always False here, so nobody can sign up as an admin
            obj_connection.execute(
                insert(tbl_users).values(
                    email=str_email,
                    first_name=str_first_name,
                    last_name=str_last_name,
                    is_admin=False,
                    hashed_password=hash_password(obj_body.password),
                )
            )
    except IntegrityError:
        # The email is the primary key, so the database refuses a second account with it
        raise HTTPException(status_code=400, detail="Could not create account")
    return {"message": "Account created"}


@obj_router.post("/login")
def login(obj_body: LoginBody, obj_request: Request, obj_response: Response) -> dict:
    str_email = obj_body.email.strip().lower()

    with obj_request.app.state.obj_engine.connect() as obj_connection:
        obj_user = obj_connection.execute(
            select(tbl_users).where(tbl_users.c.email == str_email)
        ).mappings().first()

    # Same message for a wrong email and a wrong password
    if obj_user is None or not check_password(obj_body.password, obj_user["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    str_token = secrets.token_urlsafe(32)
    with obj_request.app.state.obj_engine.begin() as obj_connection:
        # Clean out old sessions that already expired
        obj_connection.execute(delete(tbl_sessions).where(tbl_sessions.c.expires_at < get_utc_now()))
        obj_connection.execute(
            insert(tbl_sessions).values(
                token_hash=hash_token(str_token),
                user_email=obj_user["email"],
                expires_at=get_utc_now() + timedelta(hours=int_session_hours),
            )
        )

    # Set COOKIE_SECURE=true in .env when the site runs on https
    str_secure_default = "true" if os.environ.get("DATABASE_MODE", "demo").lower() == "production" else "false"
    bool_cookie_secure = os.environ.get("COOKIE_SECURE", str_secure_default).lower() == "true"
    obj_response.set_cookie(
        key=str_cookie_name,
        value=str_token,
        httponly=True,
        secure=bool_cookie_secure,
        samesite="lax",
        max_age=int_session_hours * 3600,
    )
    return {
        "email": obj_user["email"],
        "first_name": obj_user["first_name"],
        "last_name": obj_user["last_name"],
        "is_admin": bool(obj_user["is_admin"]),
    }


@obj_router.post("/logout")
def logout(obj_request: Request, obj_response: Response) -> dict:
    str_token = obj_request.cookies.get(str_cookie_name)
    if str_token:
        with obj_request.app.state.obj_engine.begin() as obj_connection:
            obj_connection.execute(
                delete(tbl_sessions).where(tbl_sessions.c.token_hash == hash_token(str_token))
            )
    obj_response.delete_cookie(str_cookie_name)
    return {"message": "Logged out"}


@obj_router.get("/me")
def me(obj_request: Request) -> dict:
    return get_current_user(obj_request)
