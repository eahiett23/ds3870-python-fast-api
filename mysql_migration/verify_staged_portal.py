"""Check the installed MySQL backend as www-data without changing the service.

Run as root to read /etc/swollenhippo.env, then permanently drop to www-data.
TestClient runs the app in-process; no listening port or reverse-proxy change.
The login creates a normal temporary session which logout removes.
"""
from getpass import getpass
import json
import os
from pathlib import Path
import pwd
import sys


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    require(os.geteuid() == 0, "Run with sudo to read the protected configuration")
    path = Path("/etc/swollenhippo.env")
    info = path.stat()
    require(info.st_uid == 0 and info.st_mode & 0o077 == 0, "Environment file must be root-owned and private")
    expected = {"MYSQL_DATABASE_URL", "APP_ENV", "COOKIE_SECURE", "APP_DATA_DIR", "APP_TEMPLATE_PATH"}
    settings = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        require(key in expected, "Unexpected configuration entry; stop for review")
        require(key not in settings, "Duplicate configuration entry")
        settings[key] = json.loads(value)
    require(set(settings) == expected and settings["COOKIE_SECURE"] == "true", "Required production configuration differs")
    password = getpass("Ellis WEBSITE administrator password: ")
    os.environ.update(settings)
    account = pwd.getpwnam("www-data")
    os.setgroups([account.pw_gid])
    os.setgid(account.pw_gid)
    os.setuid(account.pw_uid)
    os.chdir("/opt/swollenhippo")
    sys.path.insert(0, "/opt/swollenhippo")
    from fastapi.testclient import TestClient
    from mysql_portal import app
    print("Running staged checks as www-data; no HTTP listener started")
    with TestClient(app, base_url="https://swollenhippoindustries.duckdns.org") as client:
        require(client.get("/healthz").status_code == 200, "Health endpoint failed")
        page = client.get("/")
        require(page.status_code == 200 and "text/html" in page.headers.get("content-type", ""), "Frontend template cannot be served")
        print("PASS: configuration, MySQL startup, health endpoint and frontend template")
        require(client.get("/api/jobs").status_code == 401, "Anonymous dashboard access was not refused")
        print("PASS: anonymous dashboard access refused")
        login = client.post("/api/auth/login", json={"email": "eahiett42@tntech.edu", "password": password},
                            headers={"Origin": "https://swollenhippoindustries.duckdns.org"})
        if login.status_code != 200:
            raise RuntimeError("Administrator login failed (HTTP " + str(login.status_code) + "); check the website password")
        try:
            require(login.json()["is_admin"] is True, "Administrator role missing")
            cookie = login.headers.get("set-cookie", "").lower()
            require("httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie, "Production cookie flags differ")
            current = client.get("/api/auth/me")
            require(current.status_code == 200 and current.json()["email"] == "eahiett42@tntech.edu", "Cookie session lookup failed")
            board = client.get("/api/jobs")
            require(board.status_code == 200 and isinstance(board.json()["jobs"], list), "Administrator dashboard response failed")
            print("PASS: administrator bcrypt login, secure cookie, session lookup and dashboard contract")
            print("Current MySQL job cards:", len(board.json()["jobs"]))
        finally:
            logout = client.post("/api/auth/logout", headers={"Origin": "https://swollenhippoindustries.duckdns.org"})
            require(logout.status_code == 200, "Logout failed; inspect the temporary session")
        require(client.get("/api/auth/me").status_code == 401, "Session still works after logout")
        print("PASS: logout removes the test session")
    print("PASS: installed backend is ready for controlled import/cutover. Live SQLite service was not changed.")


if __name__ == "__main__":
    main()
