"""Weekly auto-backup for KirayaNama (runs as a PythonAnywhere scheduled task).

What it does:
  1. Makes a consistent copy of the SQLite DB using sqlite3's online backup
     API (safe even while the site is running) -> ~/backups/kirayanama-YYYY-MM-DD.db
  2. Keeps the newest 8 weekly copies on the server, deletes older ones.
  3. Emails the backup as an attachment to the admin's Gmail (FREE via
     Gmail SMTP). Needs GMAIL_USER + GMAIL_APP_PASSWORD in the environment.
     If not configured, it still keeps the local copy and just skips email.

Run locally for a dry test:
    python3 backup_weekly.py
"""
import os
import smtplib
import sqlite3
from datetime import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

KEEP_COPIES = 8

# Candidate DB locations (first one that exists wins).
_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kirayanama.db"),
    os.path.expanduser("~/kirayanama/app/data/kirayanama.db"),
]

BACKUP_DIR = os.path.expanduser("~/backups")


def find_db():
    for p in _CANDIDATES:
        if os.path.exists(p):
            return p
    raise SystemExit("database not found; checked: " + ", ".join(_CANDIDATES))


def make_backup(db_path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    dest = os.path.join(BACKUP_DIR, "kirayanama-%s.db" % stamp)
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(dest)
    with dst:
        src.backup(dst)
    dst.close()
    src.close()
    # Prune old copies, keep the newest KEEP_COPIES.
    files = sorted(f for f in os.listdir(BACKUP_DIR)
                   if f.startswith("kirayanama-") and f.endswith(".db"))
    for f in files[:-KEEP_COPIES]:
        os.remove(os.path.join(BACKUP_DIR, f))
    return dest


def email_backup(dest):
    user = os.environ.get("GMAIL_USER")
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not (user and pw):
        print("GMAIL not configured — local backup only: %s" % dest)
        return False
    stamp = os.path.basename(dest)[len("kirayanama-"):-len(".db")]
    msg = MIMEMultipart()
    msg["Subject"] = "KirayaNama weekly backup — %s" % stamp
    msg["From"] = user
    msg["To"] = user
    msg.attach(MIMEText(
        "Assalam-o-Alaikum,\n\n"
        "Your KirayaNama weekly database backup is attached (%s).\n"
        "A copy is also kept on the server (newest %d weeks).\n\n"
        "— KirayaNama auto-backup" % (os.path.basename(dest), KEEP_COPIES),
        "plain", "utf-8"))
    with open(dest, "rb") as fh:
        part = MIMEBase("application", "octet-stream")
        part.set_payload(fh.read())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", "attachment",
                    filename=os.path.basename(dest))
    msg.attach(part)
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as s:
        s.starttls()
        s.login(user, pw)
        s.send_message(msg)
    print("backup emailed to %s" % user)
    return True


def main():
    db_path = find_db()
    dest = make_backup(db_path)
    print("backup written: %s" % dest)
    email_backup(dest)


if __name__ == "__main__":
    main()
