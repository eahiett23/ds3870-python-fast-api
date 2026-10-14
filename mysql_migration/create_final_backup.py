"""Create and verify a private final SQLite backup while the service is stopped."""
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import sqlite3
import subprocess


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run this backup script with sudo")
    state = subprocess.run(["systemctl", "is-active", "swollenhippo.service"],
                           capture_output=True, text=True, check=False).stdout.strip()
    if state != "inactive":
        raise SystemExit("Stop swollenhippo.service before creating the final cutover backup")
    source = Path("/var/lib/swollenhippo/swollen_hippo.sqlite3")
    with source.open("rb") as stream:
        header = stream.read(20)
    if header[:16] != b"SQLite format 3\x00" or header[18:20] != b"\x01\x01":
        raise SystemExit("Unexpected SQLite header/journal mode. Stop for review.")
    folder = Path("/var/backups/swollenhippo")
    if folder.is_symlink():
        raise SystemExit("Backup folder must not be a symlink")
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = folder.stat()
    if info.st_uid != 0 or info.st_mode & 0o077:
        raise SystemExit("Backup folder must be root-owned with no group/other access")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = folder / ("sqlite-before-mysql-" + stamp + ".sqlite3")
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    src = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)
    dst = sqlite3.connect(target.as_uri() + "?mode=rw", uri=True)
    try:
        src.backup(dst)
        checks = [row[0] for row in dst.execute("PRAGMA integrity_check")]
        if checks != ["ok"] or dst.execute("PRAGMA foreign_key_check").fetchall():
            raise RuntimeError("Final backup integrity/foreign-key check failed; do not import this file")
        counts = {table: dst.execute('SELECT COUNT(*) FROM "' + table + '"').fetchone()[0]
                  for table in ("users", "jobs", "sessions")}
    finally:
        dst.close()
        src.close()
    with target.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    print("Verified final backup:", target)
    print("Integrity: ok")
    print("Counts:", counts)
    print("SHA256:", digest)
    print("Source unchanged. Service remains stopped for controlled import.")


if __name__ == "__main__":
    main()
