"""Provision/reset a production account; password is prompted, never a CLI argument."""
import argparse
from getpass import getpass
import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from argon2 import PasswordHasher
from dotenv import load_dotenv
from pathlib import Path
from .models import User


def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=False)
    obj_parser = argparse.ArgumentParser()
    obj_parser.add_argument('--email', required=True)
    obj_parser.add_argument('--role', choices=['customer', 'admin'], required=True)
    obj_parser.add_argument('--first-name', required=True)
    obj_parser.add_argument('--last-name', required=True)
    obj_args = obj_parser.parse_args()
    str_password = getpass('New password (at least 12 characters): ')
    if len(str_password) < 12 or str_password != getpass('Confirm password: '):
        raise SystemExit('Password too short or confirmation mismatch')
    obj_engine = create_engine(os.environ['CONNECTIONSTRING'])
    if obj_engine.dialect.name != 'mysql':
        raise SystemExit('Production provisioning requires MySQL')
    try:
        with Session(obj_engine) as obj_session, obj_session.begin():
            obj_user = obj_session.scalar(select(User).where(User.email == obj_args.email.strip().lower()))
            if obj_user is None:
                obj_user = User(email=obj_args.email.strip().lower())
                obj_session.add(obj_user)
            obj_user.role = obj_args.role
            obj_user.first_name = obj_args.first_name
            obj_user.last_name = obj_args.last_name
            obj_user.password_hash = PasswordHasher().hash(str_password)
            obj_user.is_active = 1
            # Existing tokens must stop working after credential provisioning/reset.
            from .api import utc_now
            for obj_record in obj_user.sessions:
                obj_record.revoked_at = utc_now()
            obj_session.flush()
            print(f'Account provisioned: id={obj_user.id}, email={obj_user.email}')
    finally:
        obj_engine.dispose()


if __name__ == '__main__':
    main()
