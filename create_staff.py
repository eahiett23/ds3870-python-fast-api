"""Create an administrator account; public registration can create customers only."""

from getpass import getpass

from sqlalchemy import insert
from sqlalchemy.exc import IntegrityError

from auth import get_password_problem, hash_password
from database import initialize_database, tbl_users


def main() -> None:
    str_email = input("Admin email: ").strip().lower()
    str_first_name = input("First name: ").strip()
    str_last_name = input("Last name: ").strip()
    str_password = getpass("Password (at least 10 characters): ")

    str_problem = get_password_problem(str_password)
    if str_problem:
        raise SystemExit(str_problem)
    if not str_first_name or not str_last_name:
        raise SystemExit("Enter the admin's first and last name")

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
    except IntegrityError as obj_error:
        raise SystemExit("An account with that email already exists.") from obj_error
    finally:
        obj_engine.dispose()

    print("Admin account created for", str_email)


if __name__ == "__main__":
    main()
