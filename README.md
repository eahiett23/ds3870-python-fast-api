# Swollen Hippo Industries

A FastAPI prototype intake and job-tracking app with a vanilla JavaScript frontend.

## Run locally

```sh
python -m pip install -r requirements.txt
uvicorn main:app --reload
```

Open `http://127.0.0.1:8000`. Use **Sign up** to create a customer login. To create an admin, run `python create_staff.py` and follow the prompts. Public registration always creates a customer account.

The default demo mode stores accounts and login sessions in `swollen_hippo.db` (SQLite). Set `DATABASE_MODE=production` and `CONNECTIONSTRING` in `.env` to use the configured production SQLAlchemy URL. Set `COOKIE_SECURE=true` when serving the site over HTTPS; production mode defaults it to true.

Job inquiries and job updates use in-memory lists to match the prototype assignment and are cleared when the app restarts. Authenticated customers see only active jobs whose inquiry email matches their account. Staff accounts can see all jobs and update status and estimated dates.

## Test

```sh
python -m pytest -v
```

The API tests use a temporary SQLite database and cover account registration, login/logout, session expiration, customer job scoping, staff-only updates, and staff account creation.
