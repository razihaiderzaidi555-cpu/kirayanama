"""Hostel Rs 2000 security-fee AUTOMATIC verification tests (2026-10-07).

Covers: exact amount + identifier + fresh TID -> auto-paid; wrong amount ->
needs_review; reused TID -> rejected upfront; OCR crash -> fail-open review;
Urdu-digit TID normalization; invalid TID rejected; admin manual verify
claims the TID in UsedTrx.
"""
import os, sys, tempfile, io
from unittest import mock
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "t.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import db, User, Hostel, UsedTrx, HOSTEL_SECURITY_FEE

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
    # --- schema ---
    import sqlalchemy as sa
    insp = sa.inspect(db.engine)
    check("used_trx table", "used_trx" in insp.get_table_names())
    ucols = {c["name"] for c in insp.get_columns("used_trx")}
    check("used_trx.hostel_id column", "hostel_id" in ucols)
    hcols = {c["name"] for c in insp.get_columns("hostels")}
    for col in ("fee_tid", "fee_company", "fee_verified", "fee_review_reason"):
        check("hostels." + col, col in hcols)
    check("fee is 2000", HOSTEL_SECURITY_FEE == 2000)

    # --- seed admin + payment numbers ---
    admin = User(public_id="T-ADM", name="Admin", phone="03000000001", role="admin")
    admin.set_password("admin123")
    db.session.add(admin)
    from models import Setting
    for k, v in (("jazzcash_number", "03011234567"),
                 ("easypaisa_number", "03451234567"),
                 ("upaisa_number", "03331234567"),
                 ("hbl_account", "12345678901234")):
        s = Setting.query.get(k)
        if s:
            s.value = v
        else:
            db.session.add(Setting(key=k, value=v))
    db.session.commit()

    # --- fill quota: 50 hostels in 'sargodha', 51st owes the fee ---
    for i in range(1, 51):
        client.post("/hostel/register", data={
            "name": "Q%d" % i, "phone": "03110000%03d" % i,
            "password": "pass1234", "cnic": "35202-1111111-1",
            "hostel_name_ur": "Quota H %d" % i, "district": "sargodha",
            "address": "Addr", "photos": png_file()},
            content_type="multipart/form-data")
        client.get("/logout")
    client.post("/hostel/register", data={
        "name": "Fee Owner", "phone": "03119999999", "password": "pass1234",
        "cnic": "35202-1111111-1", "hostel_name_ur": "Fee Hostel",
        "district": "sargodha", "address": "Addr", "photos": png_file()},
        content_type="multipart/form-data")
    client.get("/logout")
    h = Hostel.query.filter_by(hostel_name_ur="Fee Hostel").first()
    check("51st: fee_due True", h is not None and h.fee_due and not h.fee_paid)
    client.post("/login", data={"phone": "03119999999", "password": "pass1234"})

    # --- fee page shows the TID field ---
    r = client.get("/hostel/%d/fee" % h.id)
    html = r.data.decode()
    check("fee page 200", r.status_code == 200)
    check("fee page has TID input", 'name="tid"' in html)

    def post_fee(tid, shot=True):
        data = {"tid": tid}
        if shot:
            data["screenshot"] = png_file("fee.png")
        return client.post("/hostel/%d/fee" % h.id, data=data,
                           content_type="multipart/form-data",
                           follow_redirects=True)

    def fresh_h():
        return Hostel.query.get(h.id)

    # --- invalid TID rejected upfront ---
    r = post_fee("123")
    check("short TID rejected", "8 سے 20" in r.data.decode() or "8 to 20" in r.data.decode())
    check("no screenshot on invalid TID", not fresh_h().fee_screenshot)

    # --- OCR crash -> fail-open (screenshot queued, reason ocr_error) ---
    with mock.patch("routes_hostel.verify_payment_screenshot",
                    side_effect=Exception("boom")):
        r = post_fee("77778888")
    h1 = fresh_h()
    check("ocr crash: screenshot saved", bool(h1.fee_screenshot))
    check("ocr crash: not paid", not h1.fee_paid)
    check("ocr crash: reason ocr_error", h1.fee_review_reason == "ocr_error")
    check("ocr crash: tid recorded", h1.fee_tid == "77778888")

    # --- amount mismatch -> needs_review ---
    with mock.patch("routes_hostel.verify_payment_screenshot",
                    return_value=(False, None, "amount_mismatch", None)):
        r = post_fee("77779999")
    h2 = fresh_h()
    check("mismatch: not paid", not h2.fee_paid)
    check("mismatch: reason recorded", h2.fee_review_reason == "amount_mismatch")

    # --- auto-verify success: exact 2000 + identifier + fresh TID ---
    with mock.patch("routes_hostel.verify_payment_screenshot",
                    return_value=(True, None, "", "jazzcash")):
        r = post_fee("55556666")
    h3 = fresh_h()
    check("auto: fee_paid True", h3.fee_paid is True)
    check("auto: fee_verified True", h3.fee_verified is True)
    check("auto: tid + company recorded",
          h3.fee_tid == "55556666" and h3.fee_company == "jazzcash")
    check("auto: TID claimed in UsedTrx",
          UsedTrx.query.get("55556666") is not None)
    check("auto: flash shown", "خودکار تصدیق" in r.data.decode())

    # --- reused TID rejected upfront (the one from the auto-paid fee) ---
    # NOTE: h is already paid, so the fee route redirects — use a fresh hostel.
    client.get("/logout")
    client.post("/hostel/register", data={
        "name": "Fee Owner R", "phone": "03116666666", "password": "pass1234",
        "cnic": "35202-1111111-1", "hostel_name_ur": "Fee Hostel R",
        "district": "sargodha", "address": "Addr", "photos": png_file()},
        content_type="multipart/form-data")
    client.get("/logout")
    hr = Hostel.query.filter_by(hostel_name_ur="Fee Hostel R").first()
    client.post("/login", data={"phone": "03116666666", "password": "pass1234"})
    r = client.post("/hostel/%d/fee" % hr.id,
                    data={"tid": "55556666", "screenshot": png_file("f.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    check("reused TID rejected", "استعمال ہو چکی" in r.data.decode())
    check("reused TID: no screenshot saved",
          not Hostel.query.get(hr.id).fee_screenshot)
    client.get("/logout")

    # --- Urdu-digit TID normalized ---
    client.post("/hostel/register", data={
        "name": "Fee Owner 2", "phone": "03118888888", "password": "pass1234",
        "cnic": "35202-1111111-1", "hostel_name_ur": "Fee Hostel 2",
        "district": "sargodha", "address": "Addr", "photos": png_file()},
        content_type="multipart/form-data")
    client.get("/logout")
    h4 = Hostel.query.filter_by(hostel_name_ur="Fee Hostel 2").first()
    client.post("/login", data={"phone": "03118888888", "password": "pass1234"})
    with mock.patch("routes_hostel.verify_payment_screenshot",
                    return_value=(True, None, "", "easypaisa")):
        client.post("/hostel/%d/fee" % h4.id,
                    data={"tid": "۱۲۳۴۵۶۷۸", "screenshot": png_file("f.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    h4 = Hostel.query.get(h4.id)
    check("urdu-digit tid normalized+paid",
          h4.fee_paid and h4.fee_tid == "12345678")
    check("urdu-digit tid in UsedTrx", UsedTrx.query.get("12345678") is not None)

    # --- admin manual verify claims the TID for a queued (ocr_error) fee ---
    client.get("/logout")
    client.post("/hostel/register", data={
        "name": "Fee Owner 3", "phone": "03117777777", "password": "pass1234",
        "cnic": "35202-1111111-1", "hostel_name_ur": "Fee Hostel 3",
        "district": "sargodha", "address": "Addr", "photos": png_file()},
        content_type="multipart/form-data")
    client.get("/logout")
    h5 = Hostel.query.filter_by(hostel_name_ur="Fee Hostel 3").first()
    client.post("/login", data={"phone": "03117777777", "password": "pass1234"})
    with mock.patch("routes_hostel.verify_payment_screenshot",
                    return_value=(False, None, "ocr_error", None)):
        client.post("/hostel/%d/fee" % h5.id,
                    data={"tid": "44443333", "screenshot": png_file("f.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/hostels")
    check("admin hostels page 200", r.status_code == 200)
    client.post("/admin/hostels/%d/verify-fee" % h5.id)
    h5 = Hostel.query.get(h5.id)
    check("admin manual verify pays fee", h5.fee_paid)
    check("admin manual verify claims TID",
          UsedTrx.query.get("44443333") is not None)

    # --- translations present in both languages ---
    from translations import TRANSLATIONS
    for key in ("tid_label", "tid_hint", "tid_invalid", "tid_reused",
                "fee_auto_verified", "fee_needs_review", "reason_amount_mismatch",
                "reason_identifier_missing", "reason_trx_missing",
                "reason_trx_reused", "reason_ocr_error", "shot_auto_verified",
                "shot_needs_review"):
        check("i18n ur." + key, key in TRANSLATIONS["ur"])
        check("i18n en." + key, key in TRANSLATIONS["en"])

print("\n%d passed, %d failed" % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
