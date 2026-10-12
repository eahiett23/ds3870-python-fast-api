"""Makes an admin (staff) account. Sign up on the website can only make customers.

Run it once from the project folder:  python create_staff.py
"""
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from auth import get_password_problem, hash_password
from database import initialize_database, tbl_users

load_dotenv(Path(__file__).with_name(".env"), override=False)

str_email = input("Admin email: ").strip().lower()
str_first_name = input("First name: ").strip()
str_last_name = input("Last name: ").strip()
str_password = getpass("Password (at least 10 characters): ")

str_problem = get_password_problem(str_password)
if str_problem:
    raise SystemExit(str_problem)

obj_engine = initialize_database()
try:
    with obj_engine.begin() as obj_connection:
        obj_connection.execute(
            insert(tbl_users).values(
                email=str_email,
                first_name=str_first_name,
                last_name=str_last_name,
                is_admin=True,
                hashed_password=hash_password(str_password),
            )
        )
except IntegrityError:
    raise SystemExit("An account with that email already exists.")
finally:
    obj_engine.dispose()

print("Admin account created for", str_email)
