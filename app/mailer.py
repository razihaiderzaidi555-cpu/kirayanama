"""Free email sending via Gmail SMTP — no charges, no third-party OTP service.

Configure with environment variables (set on the server, never in chat):
  GMAIL_USER          — the Gmail address emails are sent from
  GMAIL_APP_PASSWORD  — 16-char app password (NOT the Google login password)

If not configured, send_email logs instead of raising (dev-safe: the app
keeps working, emails just don't go out).
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

log = logging.getLogger(__name__)


def is_configured():
    return bool(os.environ.get("GMAIL_USER") and os.environ.get("GMAIL_APP_PASSWORD"))


def send_email(to_addr, subject, body):
    """Send a plain-text UTF-8 email. Returns True on success.

    Returns False (and logs) when unconfigured or on SMTP failure —
    callers should degrade gracefully, never crash the request.
    """
    if not to_addr:
        return False
    if not is_configured():
        log.warning("EMAIL NOT CONFIGURED — would send to %s | %s", to_addr, subject)
        return False
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = os.environ["GMAIL_USER"]
    msg["To"] = to_addr
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as s:
            s.starttls()
            s.login(os.environ["GMAIL_USER"], os.environ["GMAIL_APP_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception:
        log.exception("send_email failed to %s", to_addr)
        return False


# ---------- Deal-flow notifications (free via Gmail SMTP) ----------

def _safe_send(to_addr, subject, body):
    try:
        return send_email(to_addr, subject, body)
    except Exception:
        log.exception("notification failed")
        return False


def notify_new_request(cr):
    """Renter contacted -> tell the landlord (Urdu)."""
    ll = getattr(cr, "landlord", None)
    listing = getattr(cr, "listing", None)
    if not ll or not ll.email or not listing:
        return False
    subject = "کرایہ نامہ — آپ کی لسٹنگ پر نئی رابطہ درخواست"
    body = (
        "السلام علیکم {}!\n\n"
        "آپ کی لسٹنگ \"{}\" کے لیے ایک کرایہ دار نے رابطہ کیا ہے۔\n"
        "براہ کرم ڈیش بورڈ کھول کر اپنی رضامندی دیں:\n"
        "{}\n\n"
        "— کرایہ نامہ"
    ).format(ll.name, listing.title_ur, "https://razishah110.pythonanywhere.com/dashboard/requests")
    return _safe_send(ll.email, subject, body)


def notify_landlord_confirmed(cr):
    """Landlord said yes -> tell the renter to pay commission."""
    renter = getattr(cr, "renter", None)
    listing = getattr(cr, "listing", None)
    if not renter or not renter.email or not listing:
        return False
    subject = "کرایہ نامہ — مالک راضی، اب کمیشن ادا کریں"
    body = (
        "السلام علیکم {}!\n\n"
        "مکان \"{}\" کے مالک نے رابطے پر رضامندی دے دی ہے۔\n"
        "اب اپنا 15% کمیشن ادا کر کے اسکرین شاٹ اپ لوڈ کریں:\n"
        "{}\n\n"
        "— کرایہ نامہ"
    ).format(renter.name, listing.title_ur, "https://razishah110.pythonanywhere.com/request/{}".format(cr.id))
    return _safe_send(renter.email, subject, body)


def notify_unlocked(cr):
    """Admin verified -> tell both sides the contact is unlocked."""
    listing = getattr(cr, "listing", None)
    if not listing:
        return False
    ok = True
    for user, role in ((getattr(cr, "renter", None), "کرایہ دار"), (getattr(cr, "landlord", None), "مالک")):
        if not user or not user.email:
            continue
        subject = "کرایہ نامہ — رابطہ کھل گیا! 🎉"
        body = (
            "السلام علیکم {}!\n\n"
            "مبارک ہو — مکان \"{}\" کی ڈیل مکمل ہو گئی اور رابطہ کھل گیا ہے۔\n"
            "تفصیل یہاں دیکھیں:\n"
            "{}\n\n"
            "— کرایہ نامہ"
        ).format(user.name, listing.title_ur, "https://razishah110.pythonanywhere.com/request/{}".format(cr.id))
        ok = _safe_send(user.email, subject, body) and ok
    return ok
