"""Local e2e test for the KirayaNama feature batch (2026-10-05)."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Isolated test DB (app reads DATABASE_URL, not SQLALCHEMY_DATABASE_URI)
tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import db, User, Listing, ContactRequest, PasswordReset, Rating

app = create_app()
app.config["TESTING"] = True
client = app.test_client()

passed, failed = [], []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name)

with app.app_context():
    # --- schema has new columns ---
    import sqlalchemy as sa
    insp = sa.inspect(db.engine)
    cols_users = {c["name"] for c in insp.get_columns("users")}
    cols_list = {c["name"] for c in insp.get_columns("listings")}
    check("users.email column", "email" in cols_users)
    check("listings.is_closed column", "is_closed" in cols_list)
    check("password_resets table", "password_resets" in insp.get_table_names())
    check("ratings table", "ratings" in insp.get_table_names())

    # --- seed users ---
    admin = User(public_id="T-ADMIN", name="Admin", phone="03000000001", role="admin", city="chiniot")
    admin.set_password("admin123"); admin.email = "admin@test.com"
    ll = User(public_id="T-LL", name="Malik", phone="03000000002", role="landlord", city="chiniot")
    ll.set_password("ll123456"); ll.email = "landlord@test.com"
    renter = User(public_id="T-RT", name="Kirayedar", phone="03000000003", role="renter", city="chiniot")
    renter.set_password("rt123456"); renter.email = "renter@test.com"
    db.session.add_all([admin, ll, renter]); db.session.commit()

    # --- register with email + cascading location ---
    r = client.post("/register", data={"name": "Naya", "phone": "03000000004",
        "email": "naya@test.com", "password": "pass1234", "role": "renter",
        "division": "faisalabad", "district": "chiniot", "tehsil": "lalian"})
    check("register with email -> redirect", r.status_code in (301, 302))
    naya = User.query.filter_by(phone="03000000004").first()
    check("email saved", naya.email == "naya@test.com")
    check("register division saved", naya.division == "faisalabad")
    check("register district saved", naya.district == "chiniot")
    check("register tehsil saved", naya.city == "lalian")
    client.get("/logout")

    # legacy flat city still resolves (backward compat)
    r = client.post("/register", data={"name": "Purana", "phone": "03000000006",
        "email": "purana@test.com", "password": "pass1234", "role": "renter",
        "city": "bhuwana"})
    check("legacy city register -> redirect", r.status_code in (301, 302))
    pur = User.query.filter_by(phone="03000000006").first()
    check("legacy city resolves division", pur.division == "faisalabad")
    check("legacy city resolves district", pur.district == "chiniot")
    check("legacy city resolves tehsil", pur.city == "bhuwana")
    client.get("/logout")

    # duplicate email rejected
    r = client.post("/register", data={"name": "Dup", "phone": "03000000005",
        "email": "naya@test.com", "password": "pass1234", "role": "renter", "city": "chiniot"})
    check("duplicate email rejected", b"email_taken" in r.data or "email" in r.data.decode().lower())
    client.get("/logout")

    # --- login as renter, my-requests page ---
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.get("/my-requests")
    check("my-requests page 200", r.status_code == 200)
    check("my-requests empty text", "my_requests_empty" in r.data.decode() or "رابطہ" in r.data.decode())

    # --- listing with photo required: create listing as landlord ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    # no photo -> rejected
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "ٹیسٹ مکان", "city": "chiniot", "monthly_rent": "15000",
        "property_type": "house"}, follow_redirects=True)
    check("listing without photo rejected", "photo_required" in r.data.decode() or "تصویر" in r.data.decode())
    check("no listing created", Listing.query.count() == 0)

    # with a photo -> accepted (generate a small png)
    from PIL import Image
    import io
    img = Image.new("RGB", (100, 100), "red")
    buf = io.BytesIO(); img.save(buf, "PNG"); buf.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "ٹیسٹ مکان", "monthly_rent": "15000",
        "division": "faisalabad", "district": "chiniot", "tehsil": "chiniot",
        "property_type": "house",
        "photos": (buf, "test.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    check("listing with photo created", Listing.query.count() == 1)
    listing = Listing.query.first()
    check("listing division saved", listing.division == "faisalabad")
    check("listing district saved", listing.city == "chiniot")
    check("listing tehsil saved", listing.tehsil == "chiniot")
    listing.status = "approved"; listing.photo_status = "approved"; db.session.commit()

    # legacy city-only listing post still works
    buf2 = io.BytesIO(); img.save(buf2, "PNG"); buf2.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "پرانا مکان", "city": "lalian", "monthly_rent": "12000",
        "property_type": "house",
        "photos": (buf2, "test2.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    check("legacy city listing created", Listing.query.count() == 2)
    legacy = Listing.query.filter_by(title_ur="پرانا مکان").first()
    check("legacy listing division", legacy.division == "faisalabad")
    check("legacy listing district", legacy.city == "chiniot")
    check("legacy listing tehsil", legacy.tehsil == "lalian")
    legacy.status = "approved"; legacy.photo_status = "approved"; db.session.commit()

    # --- renter contacts -> my-requests shows it ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.post(f"/contact/{listing.id}", follow_redirects=True)
    cr = ContactRequest.query.filter_by(renter_id=renter.id).first()
    check("contact request created", cr is not None)
    r = client.get("/my-requests")
    check("my-requests shows listing", "ٹیسٹ مکان" in r.data.decode())

    # --- landlord closes listing -> hidden from public ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    r = client.post(f"/dashboard/listings/{listing.id}/close", follow_redirects=True)
    check("close sets is_closed", Listing.query.get(listing.id).is_closed is True)
    r = client.get(f"/listing/{listing.id}")
    check("closed listing 404", r.status_code == 404)
    r = client.get("/listings")
    check("closed listing not in browse", "ٹیسٹ مکان" not in r.data.decode())
    # reopen
    r = client.post(f"/dashboard/listings/{listing.id}/reopen", follow_redirects=True)
    check("reopen works", Listing.query.get(listing.id).is_closed is False)
    r = client.get(f"/listing/{listing.id}")
    check("reopened listing 200", r.status_code == 200)

    # --- division/district/tehsil pages & filters ---
    r = client.get("/division/faisalabad")
    check("division page 200", r.status_code == 200)
    check("division page shows listing", "ٹیسٹ مکان" in r.data.decode())
    r = client.get("/division/nonexistent")
    check("bad division 404", r.status_code == 404)
    r = client.get("/divisions")
    check("divisions index 200", r.status_code == 200)
    check("divisions index lists lahore", "لاہور" in r.data.decode())
    r = client.get("/city/chiniot")
    check("district page 200", r.status_code == 200)
    r = client.get("/city/lalian")
    check("legacy tehsil slug page 200", r.status_code == 200)
    check("legacy tehsil page filtered", "پرانا مکان" in r.data.decode()
          and "ٹیسٹ مکان" not in r.data.decode())
    r = client.get("/city/nowhere")
    check("bad city 404", r.status_code == 404)
    r = client.get("/listings?division=faisalabad&district=chiniot&tehsil=chiniot")
    body = r.data.decode()
    check("tehsil filter shows match", "ٹیسٹ مکان" in body)
    check("tehsil filter hides other", "پرانا مکان" not in body)
    r = client.get("/listings?division=lahore")
    check("division filter empties other division",
          "ٹیسٹ مکان" not in r.data.decode())
    r = client.get("/sitemap.xml")
    check("sitemap 200", r.status_code == 200)
    check("sitemap has division urls", "/division/lahore" in r.data.decode())

    # invalid triple on listing form -> graceful fallback, no crash
    buf3 = io.BytesIO(); img.save(buf3, "PNG"); buf3.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "غلط مقام", "monthly_rent": "9000",
        "division": "nope", "district": "nope", "tehsil": "nope",
        "property_type": "house",
        "photos": (buf3, "test3.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    bad = Listing.query.filter_by(title_ur="غلط مقام").first()
    check("invalid triple falls back", bad is not None and bad.division == "faisalabad")

    # --- OTP forgot password flow (mock email as sent) ---
    import mailer
    _real_send = mailer.send_email
    mailer.send_email = lambda *a, **k: True
    # routes_auth imported send via "from mailer import send_email" inside _send_otp,
    # so patch the attribute on the module:
    client.get("/logout")
    r = client.post("/forgot-password", data={"phone": "03000000003"}, follow_redirects=False)
    check("forgot -> verify redirect", r.status_code in (301, 302) and "verify" in r.headers.get("Location", ""))
    pr = PasswordReset.query.filter_by(user_id=renter.id).order_by(PasswordReset.id.desc()).first()
    check("OTP row created", pr is not None and not pr.used)
    # wrong code
    r = client.post("/forgot-password/verify", data={"code": "000000"}, follow_redirects=True)
    check("wrong OTP rejected", "otp_wrong" in r.data.decode() or "غلط" in r.data.decode())
    # can't know the code (hashed) — verify hash works via model check
    from werkzeug.security import check_password_hash
    check("code stored hashed", pr.code_hash != "000000" and len(pr.code_hash) > 20)
    mailer.send_email = _real_send  # restore

    # --- rating: unlock then rate ---
    cr.status = "unlocked"; db.session.commit()
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.post(f"/request/{cr.id}/rate", data={"stars": "5", "comment": "بہت اچھے"},
                    follow_redirects=True)
    check("rating saved", Rating.query.filter_by(contact_request_id=cr.id).first() is not None)
    r = client.post(f"/request/{cr.id}/rate", data={"stars": "1"}, follow_redirects=True)
    check("double rating blocked", Rating.query.filter_by(contact_request_id=cr.id).count() == 1)
    r = client.get(f"/listing/{listing.id}")
    check("avg rating on detail", "5.0" in r.data.decode() or "5/5" in r.data.decode())

    # --- admin backup ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/backup")
    check("backup downloads", r.status_code == 200 and len(r.data) > 1000)

    # --- profile email update ---
    r = client.post("/profile", data={"email": "admin2@test.com"}, follow_redirects=True)
    check("profile email update", User.query.get(admin.id).email == "admin2@test.com")

    # --- mailer dev-safe (no creds) ---
    from mailer import send_email, is_configured
    check("mailer unconfigured in dev", is_configured() is False)
    check("send_email False not crash", send_email("x@y.com", "s", "b") is False)

    # --- automatic photo checks: clean photo auto-approves (no admin needed) ---
    check("listings.photo_status column", "photo_status" in cols_list)
    check("listings.photo_flag column", "photo_flag" in cols_list)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    img3 = Image.new("RGB", (100, 100), "blue")
    buf3 = io.BytesIO(); img3.save(buf3, "PNG"); buf3.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "فوٹو ٹیسٹ", "monthly_rent": "15000",
        "division": "faisalabad", "district": "chiniot", "tehsil": "chiniot",
        "property_type": "house", "photos": (buf3, "p3.png")},
        content_type="multipart/form-data", follow_redirects=True)
    pl = Listing.query.filter_by(title_ur="فوٹو ٹیسٹ").first()
    # test env has no cv2/tesseract -> both guards fail open -> auto approved
    check("clean photo auto-approved", pl is not None and pl.photo_status == "approved")
    check("clean photo flag empty", pl.photo_flag == "")
    check("hidden: listing status still pending",
          client.get(f"/listing/{pl.id}").status_code == 404)
    check("not in browse (listing pending)",
          "فوٹو ٹیسٹ" not in client.get("/listings").data.decode())
    check("contact blocked (listing pending)",
          client.post(f"/contact/{pl.id}").status_code in (302, 404))

    # admin photo review page still exists (background queue for OCR flags)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/photos")
    check("photo review page 200", r.status_code == 200)
    # simulate an OCR-flagged listing, then approve it
    pl.photo_status = "pending"; pl.photo_flag = "phone_detected"; db.session.commit()
    r = client.get("/admin/photos")
    check("photo review lists pending", "فوٹو ٹیسٹ" in r.data.decode())
    r = client.post(f"/admin/photos/{pl.id}/approve", follow_redirects=True)
    check("photo approve sets approved", Listing.query.get(pl.id).photo_status == "approved")
    check("photo approve clears flag", Listing.query.get(pl.id).photo_flag == "")
    pl.status = "approved"; db.session.commit()
    check("visible after both approvals", client.get(f"/listing/{pl.id}").status_code == 200)

    # pipeline: mocked person detection -> auto reject with Urdu reason
    from unittest import mock
    buf5 = io.BytesIO(); img3.save(buf5, "PNG"); buf5.seek(0)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    with mock.patch("person_guard.scan_photo_paths", return_value=True):
        client.post("/dashboard/listings/new", data={
            "title_ur": "شخص ٹیسٹ", "monthly_rent": "15000",
            "division": "faisalabad", "district": "chiniot", "tehsil": "chiniot",
            "property_type": "house", "photos": (buf5, "p5.png")},
            content_type="multipart/form-data", follow_redirects=True)
    pp = Listing.query.filter_by(title_ur="شخص ٹیسٹ").first()
    check("person detected -> photo rejected",
          pp is not None and pp.photo_status == "rejected")
    check("person detected -> flag set", pp.photo_flag == "person_detected")
    check("landlord sees Urdu reject reason",
          pp.rejection_reason == "تصویر میں کوئی شخص نظر آ رہا ہے — خالی مکان/دکان کی تصویر لگائیں۔")
    check("rejected photo hidden from public",
          client.get(f"/listing/{pp.id}").status_code == 404)

    # report-photo flow: viewer flags -> hidden until admin clears
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.post(f"/listing/{pl.id}/report-photo", follow_redirects=True)
    check("report-photo 302/200", r.status_code in (200, 302))
    rp = Listing.query.get(pl.id)
    check("report sets user_reported flag", rp.photo_flag == "user_reported")
    check("reported listing hidden", client.get(f"/listing/{pl.id}").status_code == 404)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    client.post(f"/admin/photos/{pl.id}/approve", follow_redirects=True)
    check("admin clears report -> visible again",
          client.get(f"/listing/{pl.id}").status_code == 200)

    # admin photo review queue: reject with reason
    buf4 = io.BytesIO(); img3.save(buf4, "PNG"); buf4.seek(0)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    client.post("/dashboard/listings/new", data={
        "title_ur": "مسترد ٹیسٹ", "monthly_rent": "15000",
        "division": "faisalabad", "district": "chiniot", "tehsil": "chiniot",
        "property_type": "house", "photos": (buf4, "p4.png")},
        content_type="multipart/form-data", follow_redirects=True)
    rl = Listing.query.filter_by(title_ur="مسترد ٹیسٹ").first()
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.post(f"/admin/photos/{rl.id}/reject", data={"reason": "tasveer mein number"},
                    follow_redirects=True)
    rl2 = Listing.query.get(rl.id)
    check("photo reject status", rl2.photo_status == "rejected")
    check("photo reject reason saved", rl2.rejection_reason == "tasveer mein number")

    # migration backfill: NULL photo_status -> approved
    from sqlalchemy import text as _satext
    db.session.execute(_satext("UPDATE listings SET photo_status=NULL WHERE id=:i"), {"i": pl.id})
    db.session.commit()
    from app import _migrate_schema
    _migrate_schema()
    check("migration backfills NULL -> approved",
          Listing.query.get(pl.id).photo_status == "approved")
    _migrate_schema()  # idempotent: second run changes nothing
    check("migration idempotent", Listing.query.get(pl.id).photo_status == "approved")

    # --- photo_guard unit tests ---
    import photo_guard
    from unittest import mock
    check("guard: plain text no match",
          photo_guard.find_phone_in_text("khoobsurat ghar karaye par") is None)
    check("guard: detects 03 number",
          photo_guard.find_phone_in_text("call 0301-2345678 now") == "0301-2345678")
    check("guard: detects +92",
          photo_guard.find_phone_in_text("rabta +923001234567") == "+923001234567")
    check("guard: detects PTCL shape",
          photo_guard.find_phone_in_text("041-8712345") == "041-8712345")
    check("guard: urdu digits",
          photo_guard.find_phone_in_text("۰۳۰۱۲۳۴۵۶۷۸") == "03012345678")
    check("guard: house number not matched",
          photo_guard.find_phone_in_text("makan number 123 gali 4") is None)
    with mock.patch("photo_guard.tesseract_available", return_value=False):
        check("guard: no tesseract -> None, no crash",
              photo_guard.find_phone_in_image("/tmp/does-not-exist.png") is None)
    with mock.patch("photo_guard.ocr_image_text", return_value="rabta 0321-7654321"):
        check("guard: mocked OCR hit",
              photo_guard.find_phone_in_image("/tmp/x.png") == "0321-7654321")
    with mock.patch("photo_guard.ocr_image_text", return_value="koi number nahi"):
        check("guard: mocked OCR no hit",
              photo_guard.find_phone_in_image("/tmp/x.png") is None)
    with mock.patch("photo_guard.ocr_image_text", side_effect=RuntimeError("boom")):
        check("guard: OCR crash -> None, no raise",
              photo_guard.find_phone_in_image("/tmp/x.png") is None)
    check("guard: scan skips missing files",
          photo_guard.scan_photo_paths(["/tmp/nope1.png", "/tmp/nope2.png"]) is None)

    # --- person_guard unit tests ---
    import person_guard
    check("person: no cv2 -> fail open False, no raise",
          person_guard.person_detected_in_image("/tmp/knpg-does-not-exist.png") is False)
    check("person: threshold strong hit",
          person_guard._is_valid_detection(0.9, 0.50) is True)
    check("person: low confidence rejected",
          person_guard._is_valid_detection(0.40, 0.50) is False)
    check("person: tiny box rejected",
          person_guard._is_valid_detection(0.90, 0.01) is False)
    check("person: boundary values accepted",
          person_guard._is_valid_detection(0.50, 0.02) is True)
    check("person: thresholds documented",
          person_guard.CONFIDENCE_THRESHOLD == 0.5
          and person_guard.MIN_BOX_AREA_RATIO == 0.02)
    with mock.patch("person_guard._get_net", return_value=object()):
        with mock.patch("person_guard._person_boxes", return_value=[(0.92, 0.35)]):
            check("person: mocked detector hit -> True",
                  person_guard.person_detected_in_image("/tmp/x.png") is True)
        with mock.patch("person_guard._person_boxes", return_value=[(0.92, 0.005)]):
            check("person: mocked tiny detection ignored -> False",
                  person_guard.person_detected_in_image("/tmp/x.png") is False)
        with mock.patch("person_guard._person_boxes", return_value=[]):
            check("person: mocked detector miss -> False",
                  person_guard.person_detected_in_image("/tmp/x.png") is False)
    with mock.patch("person_guard._get_net", return_value=None):
        check("person: net unavailable -> fail open False",
              person_guard.person_detected_in_image("/tmp/x.png") is False)
    with mock.patch("person_guard._get_net", side_effect=RuntimeError("boom")):
        check("person: net crash -> False, no raise",
              person_guard.person_detected_in_image("/tmp/x.png") is False)
    with mock.patch("person_guard.model_available", return_value=False):
        check("person: model missing -> scan False, no download crash",
              person_guard.scan_photo_paths(["/tmp/x.png"]) is False)
    check("person: scan skips missing files",
          person_guard.scan_photo_paths(["/tmp/nope1.png"]) is False)

print(f"\n==== {len(passed)} passed, {len(failed)} failed ====")
if failed:
    print("FAILED:", failed)
shutil.rmtree(tmpdir, ignore_errors=True)
sys.exit(1 if failed else 0)
