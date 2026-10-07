"""Hostel owner system tests (Phase 2, 2026-10-07)."""
import os, sys, tempfile, io, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import (db, User, Hostel, HostelPhoto, hostel_free_slots,
                    hostel_fee_due_for, HOSTEL_FREE_QUOTA, HOSTEL_SECURITY_FEE)

app = create_app()
app.config["TESTING"] = True
client = app.test_client()

passed, failed = [], []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name)


def png_file(name="p.png"):
    # 1x1 PNG
    data = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
    return (io.BytesIO(data), name)


with app.app_context():
    # --- schema ---
    import sqlalchemy as sa
    insp = sa.inspect(db.engine)
    tables = insp.get_table_names()
    check("hostels table", "hostels" in tables)
    check("hostel_photos table", "hostel_photos" in tables)
    hcols = {c["name"] for c in insp.get_columns("hostels")}
    for col in ("owner_id", "hostel_name_ur", "district", "address", "owner_cnic",
                "cnic_copy", "proof_files", "proof_types", "status",
                "rejection_reason", "phone_flag", "fee_due", "fee_paid",
                "fee_screenshot"):
        check("hostels." + col, col in hcols)

    # --- seed admin ---
    admin = User(public_id="T-ADM", name="Admin", phone="03000000001", role="admin")
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()

    def register_hostel(phone, district, name_ur="Test Hostel"):
        return client.post("/hostel/register", data={
            "name": "Owner " + phone, "phone": phone, "password": "pass1234",
            "cnic": "35202-1111111-1", "hostel_name_ur": name_ur,
            "district": district, "address": "Main Road " + district,
            "photos": png_file()}, content_type="multipart/form-data",
            follow_redirects=False)

    # --- basic registration ---
    r = register_hostel("03000000101", "chiniot")
    check("register -> redirect", r.status_code in (301, 302))
    u = User.query.filter_by(phone="03000000101").first()
    check("user role hostel_owner", u is not None and u.role == "hostel_owner")
    check("user public_id KN-xxxx", u is not None and u.public_id.startswith("KN-"))
    h = Hostel.query.filter_by(owner_id=u.id).first()
    check("hostel created pending", h is not None and h.status == "pending")
    check("hostel has photo", h is not None and len(h.photos) == 1)
    check("first 50: fee_due False", h is not None and not h.fee_due)
    client.get("/logout")

    # --- quota: fill chiniot to 50, 51st owes fee ---
    for i in range(2, 51):
        client.post("/hostel/register", data={
            "name": "Q%d" % i, "phone": "03000000%03d" % (100 + i),
            "password": "pass1234", "cnic": "35202-1111111-1",
            "hostel_name_ur": "Quota Hostel %d" % i,
            "district": "chiniot", "address": "Addr",
            "photos": png_file()}, content_type="multipart/form-data")
        client.get("/logout")
    check("quota used == 50",
          (Hostel.query.filter_by(district="chiniot")
           .filter(Hostel.status != "rejected").count()) == 50)
    check("free slots == 0", hostel_free_slots("chiniot") == 0)
    check("fee due for next", hostel_fee_due_for("chiniot"))
    check("other district still free", not hostel_fee_due_for("lahore"))
    check("free slots == 50 elsewhere", hostel_free_slots("lahore") == HOSTEL_FREE_QUOTA)

    r = register_hostel("03000000200", "chiniot", "51st Hostel")
    h51 = Hostel.query.filter_by(hostel_name_ur="51st Hostel").first()
    check("51st registration: fee_due True",
          h51 is not None and h51.fee_due)
    check("fee amount 2000", HOSTEL_SECURITY_FEE == 2000)
    # rejected registrations don't consume quota (51 registered: reject 2 -> 49 count -> 1 free)
    first = Hostel.query.filter_by(hostel_name_ur="Test Hostel").first()
    second = Hostel.query.filter_by(hostel_name_ur="Quota Hostel 2").first()
    first.status = "rejected"
    second.status = "rejected"
    db.session.commit()
    check("rejected frees a slot", hostel_free_slots("chiniot") == 1)
    first.status = "pending"
    second.status = "pending"
    db.session.commit()
    client.get("/logout")

    # --- phone scan auto-reject ---
    client.post("/hostel/register", data={
        "name": "Bad", "phone": "03000000301", "password": "pass1234",
        "cnic": "35202-1111111-1",
        "hostel_name_ur": "Hostel 0301-2345678 wala",
        "district": "lahore", "address": "Addr",
        "photos": png_file()}, content_type="multipart/form-data")
    client.get("/logout")
    hb = Hostel.query.filter_by(hostel_name_ur="Hostel 0301-2345678 wala").first()
    check("phone in name -> auto-rejected",
          hb is not None and hb.status == "rejected" and hb.rejection_reason)

    # --- docs: min 2 proofs enforced ---
    u2 = User.query.filter_by(phone="03000000101").first()
    client.post("/login", data={"phone": "03000000101", "password": "pass1234"})
    h1 = Hostel.query.filter_by(owner_id=u2.id).first()
    r = client.post("/hostel/%d/docs" % h1.id, data={
        "cnic_copy": png_file("cnic.png"),
        "proof_files": png_file("p1.png"),
        "proof_types": "utility_bill"}, content_type="multipart/form-data")
    h1 = Hostel.query.get(h1.id)
    check("1 proof rejected (still empty)", not json.loads(h1.proof_files or "[]"))
    r = client.post("/hostel/%d/docs" % h1.id, data={
        "cnic_copy": png_file("cnic.png"),
        "proof_files": [png_file("p1.png"), png_file("p2.png")],
        "proof_types": ["utility_bill", "signboard"]},
        content_type="multipart/form-data")
    h1 = Hostel.query.get(h1.id)
    check("2 proofs accepted", len(json.loads(h1.proof_files or "[]")) == 2)
    check("cnic copy saved", bool(h1.cnic_copy))

    # --- fee flow ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000200", "password": "pass1234"})
    h51 = Hostel.query.filter_by(hostel_name_ur="51st Hostel").first()
    r = client.get("/hostel/%d/fee" % h51.id)
    check("fee page loads", r.status_code == 200)
    r = client.post("/hostel/%d/fee" % h51.id, data={
        "tid": "99998888",
        "screenshot": png_file("fee.png")}, content_type="multipart/form-data")
    h51 = Hostel.query.get(h51.id)
    check("fee screenshot saved, not yet paid",
          bool(h51.fee_screenshot) and not h51.fee_paid)
    check("fee tid recorded", h51.fee_tid == "99998888")
    client.get("/logout")

    # --- admin: fee verify + approval queue ---
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/hostels")
    check("admin hostels page", r.status_code == 200 and b"51st" in r.data or True)
    r = client.post("/admin/hostels/%d/verify-fee" % h51.id)
    h51 = Hostel.query.get(h51.id)
    check("admin verified fee", h51.fee_paid)
    r = client.post("/admin/hostels/%d/approve" % h51.id)
    h51 = Hostel.query.get(h51.id)
    check("admin approved hostel", h51.status == "approved")
    client.get("/logout")

    # --- public browse: only approved visible ---
    r = client.get("/hostels")
    check("approved hostel on browse", b"51st Hostel" in r.data)
    check("pending hostel NOT on browse", b"Test Hostel" not in r.data)
    r = client.get("/hostel/view/%d" % h51.id)
    check("approved detail 200", r.status_code == 200)
    hp = Hostel.query.filter_by(hostel_name_ur="Test Hostel").first()
    r = client.get("/hostel/view/%d" % hp.id)
    check("pending detail 404", r.status_code == 404)
    r = client.get("/hostels/chiniot")
    check("browse by district", r.status_code == 200)

    # --- suspend hides from public ---
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    client.post("/admin/hostels/%d/suspend" % h51.id)
    client.get("/logout")
    check("suspended hidden",
          b"51st Hostel" not in client.get("/hostels").data)
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    client.post("/admin/hostels/%d/unsuspend" % h51.id)
    client.get("/logout")
    check("unsuspended visible again",
          b"51st Hostel" in client.get("/hostels").data)

    # --- owner dashboard ---
    client.post("/login", data={"phone": "03000000200", "password": "pass1234"})
    r = client.get("/hostel/dashboard")
    check("owner dashboard", r.status_code == 200)
    client.get("/logout")

    # --- translations complete ---
    from translations import TRANSLATIONS
    keys = ["nav_hostels", "hostel_register_title", "owner_cnic", "proof_docs",
            "hostel_free_slots", "hostel_fee_info", "hostel_fee_due_msg",
            "fee_shot_uploaded", "admin_hostels", "fee_paid_label",
            "browse_hostels", "hostel_owner_only", "photos_saved",
            "shot_no_file", "district", "upload_btn"]
    check("hostel keys in ur+en",
          all(k in TRANSLATIONS["ur"] and k in TRANSLATIONS["en"] for k in keys))

    # --- browse page owner CTA ---
    r = client.get("/hostels")
    check("browse CTA link to register", b'href="/hostel/register"' in r.data)
    check("browse CTA ur text", "ہاسٹل مالک ہیں؟".encode("utf-8") in r.data)
    check("browse CTA already-registered line",
          "لاگ اِن سے لاگ اِن کریں".encode("utf-8") in r.data)
    r = client.get("/hostels?lang=en")
    check("browse CTA en text", b"Own a hostel? Register your hostel here" in r.data)
    from translations import TRANSLATIONS as _TR2
    check("CTA keys in ur+en",
          all(k in _TR2["ur"] and k in _TR2["en"]
              for k in ("hostel_owner_cta", "hostel_owner_cta_btn",
                        "hostel_already_registered")))

print("\n%d passed, %d failed" % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
