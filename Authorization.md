# Authentication

Branch: `feature/authentication`

## What we chose
A **session ID kept in an HttpOnly cookie**. The server remembers each session in a `sessions` table.

## Why
- JavaScript cannot read an HttpOnly cookie, so a script on the page cannot steal the login.
- Sessions are in our database, so logging out or cutting off a user works right away. A JWT stays valid until it expires.
- We are one website on one domain with no mobile app, so the things JWTs are good at do not help us.

## Other options we looked at
| Option | What it does | Why not |
| JWT in localStorage / sessionStorage | Signed pass the page's JavaScript can reach | Can be stolen by a script on the page. Hard to cancel. |
| JWT in a cookie | Signed pass JavaScript cannot read | Safer, but more complicated and still hard to cancel |
| Basic auth | Sends username and password on every request | Not safe enough for a real app |
| OAuth ("Sign in with Google") | Another company confirms who you are | Extra setup we do not need |
| API keys | Secret string for programs | Made for programs, not people logging in |

## How it works
1. `POST /api/auth/register` makes a **customer** account. The password is scrambled with bcrypt and never saved as plain text.
2. `POST /api/auth/login` checks the password, saves a session, and sets the cookie. A wrong email and a wrong password give the same error.
3. `POST /api/auth/logout` deletes the session and the cookie.
4. `GET /api/auth/me` says who is logged in.
5. Admin (staff) accounts are only made with `python create_staff.py`. Admin means `is_admin` is true in the `users` table.

## Rules the server checks
- You must be logged in to see jobs (`GET /api/jobs`).
- A customer only sees jobs that have their own email on them.
- Only an admin can see all jobs or change a job (`PUT /api/jobs/{id}`).
- The old `X-User-Role` header no longer gives any access.

## What changed in the repo
- `auth.py` - login routes and session-based authorization checks
- `database.py` - user/session tables and demo/production database setup
- `create_staff.py` - creates an admin account
- `auth_sessions.sql` - adds the sessions table to an existing production users database
- `pytest.ini`, `tests/` - automated endpoint tests
- `main.py` - mounts auth routes; customer job access is scoped to the signed-in email
- `templates/index.html` - provides Log in / Sign up / Log out controls
- `requirements.txt` - lists the runtime and test dependencies

## For teammates
To protect another route, call one of these inside it:
```python
dict_user = auth.get_current_user(obj_request)   # any logged in user
auth.require_admin(obj_request)                  # admin only
```

## Setup
1. `pip install -r requirements.txt` (needs `bcrypt`, plus `pytest` and `httpx` for the tests)
2. In `.env`, set `CONNECTIONSTRING` as before. Set `COOKIE_SECURE=true` when the site runs on https.
3. Make an admin: `python create_staff.py`
4. Start the app as usual.
5. In production mode only: run `auth_sessions.sql` once in the production database. The existing database must already have the `users` table described by `database.py`.

## Tests
Run `python -m pytest -v` from the project folder.

The tests use a temporary SQLite file built by our own `initialize_database()` in demo mode, so the real database is never touched. They cover sign up, log in, log out, expired sessions, the job routes, and `create_staff.py`.

They do not prove MySQL or MariaDB works, so also try the app once by hand on the real database.

## Known limits
- Emails are not checked. Someone could sign up with another person's email and see that person's jobs. A real system would send a confirmation email.
- There is no limit on wrong password tries.
- Logging in with an email that does not exist is a little faster than a wrong password, so the timing could show which emails have accounts.
- Protection against forged requests relies on `SameSite=Lax` only.
- Job and inquiry records remain in memory to match the prototype requirements; they are cleared when the server restarts. User accounts and sessions are stored in the configured database.
- Customer accounts are not email-verified, so a person could register another person's email and view inquiries attached to it. Add an email verification flow before real customer data is used.
