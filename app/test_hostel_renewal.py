"""Yearly hostel registration renewal tests (2026-10-07, Razi's order).

Covers: reg_expires_at set on admin approval (+365d); expired hostels hidden
from public browse/detail; renewal fee uses the CURRENT admin-set rate;
renewal payment extends expiry by a year; first-50-free quota NEVER applies
to renewals; renewal reminders are small and polite (no harsh red banner);
admin manual verify-fee also extends an expired registration.
"""
import os, sys, tempfile, io
from datetime import date, timedelta, datetime
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import (db, User, Hostel, Setting, hostel_fee_amount,
                    hostel_is_expired, hostel_expiry_state,
                    hostel_show_welcome_notice)

app = create_app()
app.config["TESTING"] = True
client = app.test_client()

passed, failed = [], []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name)


def png_file(name="p.png"):
    data = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
    return (io.BytesIO(data), name)


with app.app_context():
    import sqlalchemy as sa
    insp = sa.inspect(db.engine)
    hcols = {c["name"] for c in insp.get_columns("hostels")}
    check("hostels.reg_expires_at column", "reg_expires_at" in hcols)
    check("hostels.renewal_dismissed_at column", "renewal_dismissed_at" in hcols)

    # --- fee amount setting: default + override + invalid fallback ---
    check("fee default 2000", hostel_fee_amount() == 2000)
    db.session.add(Setting(key="hostel_fee_amount", value="3500"))
    db.session.commit()
    check("fee follows setting", hostel_fee_amount() == 3500)
    Setting.query.get("hostel_fee_amount").value = "abc"
    db.session.commit()
    check("fee falls back on bad value", hostel_fee_amount() == 2000)
    Setting.query.get("hostel_fee_amount").value = "2000"
    db.session.commit()

    # --- seed admin ---
    admin = User(public_id="T-ADM", name="Admin", phone="03000000001", role="admin")
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()

    def register_owner(phone, district, name_ur):
        r = client.post("/hostel/register", data={
            "name": "Owner " + phone, "phone": phone, "password": "pass1234",
            "cnic": "35202-1111111-1", "hostel_name_ur": name_ur,
            "district": district, "address": "Main Road",
            "photos": png_file()}, content_type="multipart/form-data",
            follow_redirects=False)
        client.get("/logout")
        return Hostel.query.filter_by(hostel_name_ur=name_ur).first()

    def admin_approve(h):
        client.post("/login", data={"phone": "03000000001", "password": "admin123"})
        r = client.post("/admin/hostels/%d/approve" % h.id, follow_redirects=True)
        client.get("/logout")
        return r

    # --- approval sets expiry = today + 365d ---
    h1 = register_owner("03110001001", "faisalabad", "Renewal H1")
    admin_approve(h1)
    h1 = Hostel.query.get(h1.id)
    check("approval: status approved", h1.status == "approved")
    check("approval: expiry = today+365",
          h1.reg_expires_at == date.today() + timedelta(days=365))
    check("not expired when fresh", not hostel_is_expired(h1))
    check("expiry state valid", hostel_expiry_state(h1) == "valid")

    # --- visible in browse while valid ---
    r = client.get("/hostels")
    check("valid hostel in browse", "Renewal H1" in r.data.decode())
    r = client.get("/hostel/view/%d" % h1.id)
    check("valid hostel detail 200", r.status_code == 200)

    # --- expired: hidden from browse + detail 404 ---
    h1.reg_expires_at = date.today() - timedelta(days=1)
    db.session.commit()
    check("expired detected", hostel_is_expired(h1))
    check("expiry state expired", hostel_expiry_state(h1) == "expired")
    r = client.get("/hostels")
    check("expired hidden from browse", "Renewal H1" not in r.data.decode())
    r = client.get("/hostels/faisalabad")
    check("expired hidden from district browse", "Renewal H1" not in r.data.decode())
    r = client.get("/hostel/view/%d" % h1.id)
    check("expired detail 404", r.status_code == 404)

    # --- owner login for renewal flow ---
    client.post("/login", data={"phone": "03110001001", "password": "pass1234"})

    # --- dashboard: polite expired notice, no harsh red banner ---
    r = client.get("/hostel/dashboard")
    html = r.data.decode()
    check("dashboard: polite expired note shown",
          "تجدید کروا لیں" in html or "renew it" in html)
    check("dashboard: no harsh alert-err in renewal notice",
          "alert-err" not in html)
    check("dashboard: no warning emoji banner", "⚠️" not in html)
    check("dashboard: renew button present", "renew=1" in html)
    check("dashboard: policy line shown",
          "ہر سال تجدید" in html or "every year" in html)

    # --- renewal page uses CURRENT rate (change setting -> new rate) ---
    Setting.query.get("hostel_fee_amount").value = "3500"
    db.session.commit()
    r = client.get("/hostel/%d/fee?renew=1" % h1.id)
    html = r.data.decode()
    check("renewal fee page 200", r.status_code == 200)
    check("renewal page shows new rate 3500", "3500" in html)
    check("renewal page not old rate text", "Rs 2000" not in html)

    # --- renewal payment: auto-verify called with CURRENT rate, extends expiry ---
    seen_amounts = []
    def fake_verify(img_path, expected_amount, identifiers, require_trx_id=False):
        seen_amounts.append(expected_amount)
        return (True, None, "", "jazzcash")
    with mock.patch("routes_hostel.verify_payment_screenshot", side_effect=fake_verify):
        r = client.post("/hostel/%d/fee?renew=1" % h1.id,
                        data={"tid": "88889999", "screenshot": png_file("r.png")},
                        content_type="multipart/form-data", follow_redirects=True)
    h1r = Hostel.query.get(h1.id)
    check("renewal: verify called with current rate 3500", seen_amounts == [3500])
    check("renewal: fee_paid True", h1r.fee_paid is True)
    check("renewal: expiry extended to today+365",
          h1r.reg_expires_at == date.today() + timedelta(days=365))
    check("renewal: no longer expired", not hostel_is_expired(h1r))
    r = client.get("/hostels")
    check("renewed hostel visible again", "Renewal H1" in r.data.decode())
    client.get("/logout")

    # --- first-50-free NEVER applies to renewals ---
    # fresh district with free slots: first registration owes NO fee
    h2 = register_owner("03110001002", "jhang", "Renewal H2")
    check("free district: fee_due False", h2.fee_due is False)
    admin_approve(h2)
    h2 = Hostel.query.get(h2.id)
    h2.reg_expires_at = date.today() - timedelta(days=5)
    db.session.commit()
    client.post("/login", data={"phone": "03110001002", "password": "pass1234"})
    r = client.get("/hostel/%d/fee?renew=1" % h2.id)
    check("renewal form shown despite free quota", r.status_code == 200)
    html = r.data.decode()
    check("renewal charges fee even in free district",
          "تجدید کی فیس" in html or "Renewal fee" in html)
    client.get("/logout")

    # --- PHASE 1: welcome notice for newly registered owners (7 days) ---
    # h3's owner registered just now -> notice visible
    h3 = register_owner("03110001003", "jhang", "Renewal H3")
    u3 = User.query.filter_by(phone="03110001003").first()
    check("phase1: new owner gets welcome notice",
          hostel_show_welcome_notice(u3) is True)
    client.post("/login", data={"phone": "03110001003", "password": "pass1234"})
    r = client.get("/hostel/dashboard")
    html = r.data.decode()
    check("phase1: welcome wording shown",
          "1 saal ke liye valid" in html)
    check("phase1: small polite alert, no harsh banner",
          'class="alert"' in html and "alert-err" not in html
          and "⚠️" not in html)
    client.get("/logout")
    # 8 days old -> gone on its own
    u3.created_at = datetime.now() - timedelta(days=8)
    db.session.commit()
    check("phase1: hidden on 8th day",
          hostel_show_welcome_notice(u3) is False)
    client.post("/login", data={"phone": "03110001003", "password": "pass1234"})
    r = client.get("/hostel/dashboard")
    check("phase1: welcome gone from dashboard on 8th day",
          "1 saal ke liye valid" not in r.data.decode())
    client.get("/logout")

    # --- PHASE 2: daily reminder from 30 days before expiry ---
    admin_approve(h3)
    h3 = Hostel.query.get(h3.id)
    h3.reg_expires_at = date.today() + timedelta(days=10)
    db.session.commit()
    check("phase2: expiry state expiring_soon",
          hostel_expiry_state(h3) == "expiring_soon")
    client.post("/login", data={"phone": "03110001003", "password": "pass1234"})
    r = client.get("/hostel/dashboard")
    html = r.data.decode()
    check("phase2: Razi's wording with date",
          "expire ho rahi hai" in html
          and str(h3.reg_expires_at) in html)
    check("phase2: modest alert, not alert-err",
          'class="alert"' in html and "alert-err" not in html)
    check("phase2: dismiss button present", "dismiss-renewal-reminder" in html)

    # --- 30-day boundary: shows at day 30, hidden at day 31 ---
    h3.reg_expires_at = date.today() + timedelta(days=30)
    db.session.commit()
    r = client.get("/hostel/dashboard")
    check("phase2: reminder shows at exactly 30 days",
          "expire ho rahi hai" in r.data.decode())
    h3.reg_expires_at = date.today() + timedelta(days=31)
    db.session.commit()
    r = client.get("/hostel/dashboard")
    check("phase2: reminder hidden at 31 days",
          "expire ho rahi hai" not in r.data.decode())

    # --- dismiss: hidden same day, back the next day ---
    h3.reg_expires_at = date.today() + timedelta(days=10)
    h3.renewal_dismissed_at = None
    db.session.commit()
    r = client.post("/hostel/%d/dismiss-renewal-reminder" % h3.id,
                    follow_redirects=True)
    check("dismiss route redirects to dashboard", r.status_code == 200)
    h3d = Hostel.query.get(h3.id)
    check("dismissal timestamp recorded", h3d.renewal_dismissed_at is not None)
    r = client.get("/hostel/dashboard")
    check("reminder hidden after dismiss (same day)",
          "expire ho rahi hai" not in r.data.decode())
    # simulate next day: dismissal was yesterday -> reminder returns
    h3d.renewal_dismissed_at = datetime.now() - timedelta(days=1, hours=2)
    db.session.commit()
    r = client.get("/hostel/dashboard")
    check("reminder reappears next day",
          "expire ho rahi hai" in r.data.decode())
    client.get("/logout")

    # --- admin manual verify-fee extends an expired registration ---
    h4 = register_owner("03110001004", "jhang", "Renewal H4")
    admin_approve(h4)
    h4 = Hostel.query.get(h4.id)
    h4.reg_expires_at = date.today() - timedelta(days=2)
    h4.fee_screenshot = "manual.png"
    h4.fee_tid = "99990001"
    db.session.commit()
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.post("/admin/hostels/%d/verify-fee" % h4.id, follow_redirects=True)
    client.get("/logout")
    h4 = Hostel.query.get(h4.id)
    check("admin verify: fee_paid True", h4.fee_paid is True)
    check("admin verify: expiry extended",
          h4.reg_expires_at == date.today() + timedelta(days=365))

    # --- registration + fee pages show the yearly policy ---
    r = client.get("/hostel/register")
    html = r.data.decode()
    check("register page: renewal policy shown",
          "ہر سال تجدید" in html or "every year" in html)

print("\n%d passed, %d failed" % (len(passed), len(failed)))
if failed:
    print("FAILED:", failed)
    sys.exit(1)
