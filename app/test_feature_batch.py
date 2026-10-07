"""Local e2e test for the KirayaNama feature batch (2026-10-05)."""
import os, sys, tempfile, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Isolated test DB (app reads DATABASE_URL, not SQLALCHEMY_DATABASE_URI)
tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "test.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import db, User, Listing, ContactRequest, PasswordReset, Rating, get_setting

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
        "division": "faisalabad", "district": "faisalabad", "tehsil": "faisalabad-city"})
    check("register with email -> redirect", r.status_code in (301, 302))
    naya = User.query.filter_by(phone="03000000004").first()
    check("email saved", naya.email == "naya@test.com")
    check("register division saved", naya.division == "faisalabad")
    check("register district saved", naya.district == "faisalabad")
    check("register tehsil saved", naya.city == "faisalabad-city")
    client.get("/logout")

    # legacy flat city still resolves (backward compat) — unit level; bhuwana
    # now lands in OPEN chiniot under the 3-division default, so the
    # locked-district signup check uses multan (still locked) instead.
    from punjab_divisions import resolve_location as _rl
    check("legacy city resolves (unit)", _rl(city="bhuwana") == ("faisalabad", "chiniot", "bhuwana"))
    r = client.post("/register", data={"name": "Purana", "phone": "03000000006",
        "email": "purana@test.com", "password": "pass1234", "role": "renter",
        "division": "multan", "district": "multan", "tehsil": "multan-city"})
    check("locked-district signup -> construction",
          r.status_code == 200 and "جلد آ رہا ہے" in r.data.decode())
    check("locked-district signup creates no user",
          User.query.filter_by(phone="03000000006").first() is None)
    client.get("/logout")

    # duplicate email rejected
    r = client.post("/register", data={"name": "Dup", "phone": "03000000005",
        "email": "naya@test.com", "password": "pass1234", "role": "renter", "city": "faisalabad"})
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
        "title_ur": "ٹیسٹ مکان", "city": "faisalabad", "monthly_rent": "15000",
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
        "division": "faisalabad", "district": "faisalabad", "tehsil": "faisalabad-city",
        "property_type": "house",
        "photos": (buf, "test.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    check("listing with photo created", Listing.query.count() == 1)
    listing = Listing.query.first()
    check("listing division saved", listing.division == "faisalabad")
    check("listing district saved", listing.city == "faisalabad")
    check("listing tehsil saved", listing.tehsil == "faisalabad-city")
    listing.status = "approved"; listing.photo_status = "approved"; db.session.commit()

    # legacy city-only listing post still works
    buf2 = io.BytesIO(); img.save(buf2, "PNG"); buf2.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "پرانا مکان", "city": "jaranwala", "monthly_rent": "12000",
        "property_type": "house",
        "photos": (buf2, "test2.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    check("legacy city listing created", Listing.query.count() == 2)
    legacy = Listing.query.filter_by(title_ur="پرانا مکان").first()
    check("legacy listing division", legacy.division == "faisalabad")
    check("legacy listing district", legacy.city == "faisalabad")
    check("legacy listing tehsil", legacy.tehsil == "jaranwala")
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
    r = client.get("/city/faisalabad")
    check("district page 200", r.status_code == 200)
    r = client.get("/city/jaranwala")
    check("tehsil slug page 200", r.status_code == 200)
    check("tehsil page filtered", "پرانا مکان" in r.data.decode()
          and "ٹیسٹ مکان" not in r.data.decode())
    r = client.get("/city/nowhere")
    check("bad city 404", r.status_code == 404)
    r = client.get("/listings?division=faisalabad&district=faisalabad&tehsil=faisalabad-city")
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
    # (geo-gating: the garbage triple falls back to chiniot, which is OPEN
    # under the 3-division default — the listing lands in a visible city,
    # never an invisible one)
    buf3 = io.BytesIO(); img.save(buf3, "PNG"); buf3.seek(0)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "غلط مقام", "monthly_rent": "9000",
        "division": "nope", "district": "nope", "tehsil": "nope",
        "property_type": "house",
        "photos": (buf3, "test3.png")}, content_type="multipart/form-data",
        follow_redirects=True)
    bad = Listing.query.filter_by(title_ur="غلط مقام").first()
    check("invalid triple -> falls back to open chiniot, listed visibly",
          bad is not None and bad.city == "chiniot"
          and "جلد آ رہا ہے" not in r.data.decode())

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
        "division": "faisalabad", "district": "faisalabad", "tehsil": "faisalabad-city",
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
            "division": "faisalabad", "district": "faisalabad", "tehsil": "faisalabad-city",
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
        "division": "faisalabad", "district": "faisalabad", "tehsil": "faisalabad-city",
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

    # --- automatic payment verification (payment_guard) ---
    import payment_guard
    from models import UsedTrx, REQUEST_STATUS
    from datetime import datetime as _dt

    check("used_trx table", "used_trx" in insp.get_table_names())
    _crcols = {c["name"] for c in insp.get_columns("contact_requests")}
    check("cr.renter_verified column", "renter_verified" in _crcols)
    check("cr.landlord_verified column", "landlord_verified" in _crcols)
    check("cr.renter_review_reason column", "renter_review_reason" in _crcols)
    check("cr.landlord_review_reason column", "landlord_review_reason" in _crcols)
    check("needs_review in REQUEST_STATUS", "needs_review" in REQUEST_STATUS)

    # guard unit tests
    check("pay: amount exact match",
          payment_guard.find_amount("Rs 2,250 bhej diye", 2250) is True)
    check("pay: amount substring rejected",
          payment_guard.find_amount("Rs 12250 bhej diye", 2250) is False)
    check("pay: identifier plain",
          payment_guard.find_identifier("send to 03115021212 now", ["03115021212"]) == "03115021212")
    check("pay: identifier dashed shape",
          payment_guard.find_identifier("0311-5021212", ["03115021212"]) == "03115021212")
    check("pay: identifier absent",
          payment_guard.find_identifier("send to 03009998888", ["03115021212"]) is None)
    check("pay: hbl account matched",
          payment_guard.find_identifier("ac 01737900590403", ["01737900590403"]) is not None)
    check("pay: trx transaction-id shape",
          payment_guard.extract_trx_id("Transaction ID: 12345678901") == "12345678901")
    check("pay: trx tid shape",
          payment_guard.extract_trx_id("TID 987654321") == "987654321")
    check("pay: trx ref shape",
          payment_guard.extract_trx_id("Ref No 555666777") == "555666777")
    check("pay: no trx",
          payment_guard.extract_trx_id("payment ho gai shukriya") is None)
    with mock.patch("payment_guard.ocr_text",
                     return_value="Easypaisa Rs 2,250 to 03115021212 Transaction ID 12345678901"):
        ok, trx, reason, company = payment_guard.verify_payment_screenshot(
            "/tmp/x.png", 2250, ["03115021212", "01737900590403"])
        check("pay: full pass", ok is True and trx == "12345678901" and reason == "")
        check("pay: company none for plain identifiers", company is None)
    with mock.patch("payment_guard.ocr_text",
                     return_value="Rs 2,250 to 01737900590403 Transaction ID 12345678901"):
        ok, trx, reason, company = payment_guard.verify_payment_screenshot(
            "/tmp/x.png", 2250, [("easypaisa", "03115021212"), ("hbl", "01737900590403")])
        check("pay: company detected from pairs", ok is True and company == "hbl")
    with mock.patch("payment_guard.ocr_text",
                     return_value="Easypaisa Rs 2,000 to 03115021212 Transaction ID 12345678901"):
        check("pay: amount mismatch",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "amount_mismatch")
    with mock.patch("payment_guard.ocr_text",
                     return_value="Easypaisa Rs 2,250 to 03009998888 Transaction ID 12345678901"):
        check("pay: identifier missing",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "identifier_missing")
    with mock.patch("payment_guard.ocr_text",
                     return_value="Easypaisa Rs 2,250 to 03115021212 shukriya"):
        check("pay: trx missing",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "trx_missing")
    with mock.patch("payment_guard.ocr_text",
                     return_value="Rs ۲۲۵۰ to 03115021212 Transaction ID 12345678901"):
        check("pay: urdu digits amount",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[0] is True)
    with mock.patch("payment_guard.ocr_text", side_effect=RuntimeError("boom")):
        check("pay: OCR crash -> ocr_error, no raise",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "ocr_error")
    with mock.patch("payment_guard.ocr_text", return_value=None):
        check("pay: OCR None -> ocr_error",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "ocr_error")
    with mock.patch("payment_guard.ocr_text", return_value=""):
        check("pay: OCR empty -> ocr_error",
              payment_guard.verify_payment_screenshot(
                  "/tmp/x.png", 2250, ["03115021212"])[2] == "ocr_error")

    # route-level: auto-verify flow with mocked OCR
    def _mkdeal(rent):
        lst = Listing(title_ur="ڈیل ٹیسٹ", title_en="deal", desc_ur="x",
                      city="chiniot", division="faisalabad", tehsil="chiniot",
                      monthly_rent=rent, status="approved", photo_status="approved",
                      landlord_id=ll.id, property_type="house")
        db.session.add(lst)
        db.session.commit()
        c = ContactRequest(listing_id=lst.id, renter_id=renter.id,
                           landlord_id=ll.id, status="awaiting_payment",
                           renter_yes_at=_dt.utcnow(), landlord_yes_at=_dt.utcnow())
        db.session.add(c)
        db.session.commit()
        return c

    def _shot():
        b = io.BytesIO()
        img.save(b, "PNG")
        b.seek(0)
        return (b, "shot.png")

    cr1 = _mkdeal(15000)  # commission = 2250
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    # typed TID takes precedence over OCR-extracted trx for the claim
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(True, "TRXAAA111", "", "easypaisa")):
        r = client.post(f"/request/{cr1.id}/payment",
                        data={"tid": "11111111", "screenshot": _shot()},
                        content_type="multipart/form-data", follow_redirects=True)
    c1 = ContactRequest.query.get(cr1.id)
    check("pay: renter auto-verified", c1.renter_verified is True)
    check("pay: typed tid claimed in UsedTrx",
          UsedTrx.query.get("11111111") is not None)
    check("pay: typed tid beats OCR trx",
          UsedTrx.query.get("TRXAAA111") is None)
    check("pay: one side only -> awaiting_payment", c1.status == "awaiting_payment")
    check("pay: auto flash shown", "خودکار تصدیق" in r.data.decode())

    client.get("/logout")
    client.post("/login", data={"phone": "03000000002", "password": "ll123456"})
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(True, "TRXBBB222", "", "easypaisa")):
        client.post(f"/request/{cr1.id}/payment",
                    data={"tid": "22222222", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    c1 = ContactRequest.query.get(cr1.id)
    check("pay: both sides auto -> unlocked", c1.status == "unlocked")
    check("pay: verified_at set", c1.verified_at is not None)

    # TID format validation: letters rejected
    cr5 = _mkdeal(15000)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.post(f"/request/{cr5.id}/payment",
                    data={"tid": "abc", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    c5 = ContactRequest.query.get(cr5.id)
    check("pay: bad tid format -> Urdu error", "8 سے 20" in r.data.decode())
    check("pay: bad tid -> nothing saved", c5.renter_shot is None)
    check("pay: bad tid -> status unchanged",
          c5.status == "awaiting_payment")
    # too short
    r = client.post(f"/request/{cr5.id}/payment",
                    data={"tid": "12345", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    check("pay: short tid rejected", "8 سے 20" in r.data.decode()
          and ContactRequest.query.get(cr5.id).renter_shot is None)
    # missing tid entirely
    r = client.post(f"/request/{cr5.id}/payment",
                    data={"screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    check("pay: missing tid rejected", "8 سے 20" in r.data.decode())

    # TID reuse across deals -> Urdu error, upload not even saved
    cr2 = _mkdeal(15000)
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(True, "TRXZZZ999", "", "easypaisa")) as mv:
        r = client.post(f"/request/{cr2.id}/payment",
                        data={"tid": "11111111", "screenshot": _shot()},
                        content_type="multipart/form-data", follow_redirects=True)
    c2 = ContactRequest.query.get(cr2.id)
    check("pay: reused tid -> Urdu error", "پہلے استعمال" in r.data.decode())
    check("pay: reused tid -> nothing saved", c2.renter_shot is None)
    check("pay: reused tid -> status unchanged",
          c2.status == "awaiting_payment")
    check("pay: reused tid -> OCR never ran", mv.call_count == 0)

    # Urdu digits in TID accepted (normalized)
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(True, "TRXUUU1", "", "easypaisa")):
        client.post(f"/request/{cr2.id}/payment",
                    data={"tid": "۱۲۳۴۵۶۷۸", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    c2 = ContactRequest.query.get(cr2.id)
    check("pay: urdu-digit tid accepted", c2.renter_verified is True)
    check("pay: urdu-digit tid normalized",
          UsedTrx.query.get("12345678") is not None)

    # amount mismatch (valid tid, OCR fails amount)
    cr3 = _mkdeal(15000)
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(False, None, "amount_mismatch", None)):
        client.post(f"/request/{cr3.id}/payment",
                    data={"tid": "33333333", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    c3 = ContactRequest.query.get(cr3.id)
    check("pay: mismatch -> needs_review", c3.status == "needs_review")
    check("pay: mismatch reason saved", c3.renter_review_reason == "amount_mismatch")
    check("pay: mismatch keeps screenshot", c3.renter_shot is not None)

    # OCR crash -> fail open
    cr4 = _mkdeal(15000)
    with mock.patch("routes_contact.verify_payment_screenshot",
                    side_effect=RuntimeError("boom")):
        r = client.post(f"/request/{cr4.id}/payment",
                        data={"tid": "44444444", "screenshot": _shot()},
                        content_type="multipart/form-data", follow_redirects=True)
        check("pay: guard crash -> no 500", r.status_code in (200, 302))
    c4 = ContactRequest.query.get(cr4.id)
    check("pay: crash -> needs_review", c4.status == "needs_review")
    check("pay: crash reason ocr_error", c4.renter_review_reason == "ocr_error")

    # re-upload after failure succeeds
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(True, "TRXCCC333", "", "easypaisa")):
        client.post(f"/request/{cr4.id}/payment",
                    data={"tid": "55555555", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    c4 = ContactRequest.query.get(cr4.id)
    check("pay: reupload -> verified", c4.renter_verified is True)
    check("pay: reupload -> awaiting_payment", c4.status == "awaiting_payment")

    # request page: TID input + SLA line + re-upload hint
    r = client.get(f"/request/{cr3.id}")
    check("pay: request page 200 on needs_review", r.status_code == 200)
    check("pay: reupload hint shown", "دوبارہ اپ لوڈ" in r.data.decode())
    check("pay: tid input rendered", 'name="tid"' in r.data.decode())
    check("pay: SLA line shown", "24 گھنٹے" in r.data.decode())

    # admin queue lists needs_review + manual verify/reject still work
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/payments")
    check("pay: admin queue lists needs_review", "ڈیل ٹیسٹ" in r.data.decode())
    r = client.post(f"/admin/payments/{cr3.id}/verify", follow_redirects=True)
    check("pay: admin manual verify on needs_review",
          ContactRequest.query.get(cr3.id).status == "unlocked")
    cr6 = _mkdeal(15000)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    with mock.patch("routes_contact.verify_payment_screenshot",
                    return_value=(False, None, "identifier_missing", None)):
        client.post(f"/request/{cr6.id}/payment",
                    data={"tid": "66666666", "screenshot": _shot()},
                    content_type="multipart/form-data", follow_redirects=True)
    check("pay: cr6 needs_review", ContactRequest.query.get(cr6.id).status == "needs_review")
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.post(f"/admin/payments/{cr6.id}/reject", follow_redirects=True)
    check("pay: admin reject on needs_review",
          ContactRequest.query.get(cr6.id).status == "rejected")

    # --- rechecking-window SLA message ---
    from translations import TRANSLATIONS
    check("sla: rechecking window ur",
          "رات 9 سے 12" in TRANSLATIONS["ur"]["payment_sla"]
          and "دونوں فریقین کا رابطہ" in TRANSLATIONS["ur"]["payment_sla"])
    check("sla: rechecking window en",
          "9 PM" in TRANSLATIONS["en"]["payment_sla"])
    client.get("/logout")
    client.post("/login", data={"phone": "03000000003", "password": "rt123456"})
    r = client.get(f"/request/{cr5.id}")  # still awaiting_payment
    check("sla: rendered on payment page",
          r.status_code == 200 and "رات 9 سے 12" in r.data.decode())

    # --- typed TID + company persisted on upload ---
    check("pay: renter tid stored", c1.renter_tid == "11111111")
    check("pay: renter company stored", c1.renter_company == "easypaisa")

    # --- alert token auto-generated on boot ---
    tok = get_setting("alert_token")
    check("api: alert token auto-generated", isinstance(tok, str) and len(tok) == 32)

    # --- /api/payment-events ---
    import json as _json
    since_old = "2020-01-01T00:00:00"
    r = client.get(f"/api/payment-events?since={since_old}&token={tok}")
    check("api: 200 with valid token", r.status_code == 200)
    evs = _json.loads(r.data)["events"]
    check("api: events listed", len(evs) >= 2)
    ev0 = evs[0]
    check("api: event shape",
          set(ev0) == {"event_id", "created_at", "deal_id", "side", "payer_name",
                       "amount", "tid", "company", "auto_status"})
    check("api: events ordered asc",
          all(evs[i]["created_at"] <= evs[i + 1]["created_at"] for i in range(len(evs) - 1)))
    renter_ev = [e for e in evs if e["deal_id"] == cr1.id and e["side"] == "renter"][0]
    check("api: renter event fields",
          renter_ev["tid"] == "11111111" and renter_ev["company"] == "easypaisa"
          and renter_ev["auto_status"] == "verified"
          and renter_ev["amount"] == c1.commission and renter_ev["payer_name"] == "Kirayedar")
    needs = [e for e in evs if e["auto_status"] == "needs_review"]
    check("api: needs_review events included", len(needs) >= 1)
    r = client.get(f"/api/payment-events?since=2999-01-01T00:00:00&token={tok}")
    check("api: since filters", _json.loads(r.data)["events"] == [])
    r = client.get(f"/api/payment-events?since={since_old}&token=wrong")
    check("api: wrong token -> 403", r.status_code == 403)
    r = client.get(f"/api/payment-events?since={since_old}")
    check("api: missing token -> 403", r.status_code == 403)
    r = client.get(f"/api/payment-events?since=not-a-date&token={tok}")
    check("api: bad since -> 400", r.status_code == 400)
    r = client.get(f"/api/payment-events?token={tok}")
    check("api: missing since -> 400", r.status_code == 400)

    # --- company detection unit tests ---
    check("pay: detect_company easypaisa",
          payment_guard.detect_company("sent 1800 to 03115021212",
                                       [("jazzcash", "03119998888"),
                                        ("easypaisa", "03115021212")]) == "easypaisa")
    check("pay: detect_company first-match-wins",
          payment_guard.detect_company("to 03115021212",
                                       [("jazzcash", "03115021212"),
                                        ("easypaisa", "03115021212")]) == "jazzcash")
    check("pay: detect_company hbl",
          payment_guard.detect_company("ac 01737900590403",
                                       [("easypaisa", "03115021212"),
                                        ("hbl", "01737900590403")]) == "hbl")
    check("pay: detect_company none",
          payment_guard.detect_company("shukriya", [("easypaisa", "03115021212")]) is None)

    # --- trademark symbol on brand displays ---
    from translations import get_text as _gt
    check("tm: ur app_name plain", _gt("app_name", "ur") == "کرایہ نامہ")
    check("tm: en app_name plain", _gt("app_name", "en") == "KirayaNama")
    r = client.get("/")
    html = r.data.decode()
    check("tm: home <title> has tm", "کرایہ نامہ™" in html)
    check("tm: header brand has styled tm", '<span class="tm-mark">™</span>' in html)
    check("tm: running sentence untouched",
          "کرایہ نامہ کا اصل مقصد" in html and "کرایہ نامہ™ کا اصل مقصد" not in html)
    r = client.get("/?lang=en")
    check("tm: en header brand", '<span class="tm-mark">™</span>' in r.data.decode())
    client.get("/?lang=ur")

    # --- visitor counter ---
    from datetime import datetime as _dt, timedelta as _td
    from models import VisitStat, visit_counts
    t0, tot0 = visit_counts()
    client.get("/")
    t1, tot1 = visit_counts()
    check("visits: public GET increments", t1 == t0 + 1 and tot1 == tot0 + 1)
    client.get("/static/style.css")
    check("visits: static skipped", visit_counts()[0] == t1)
    client.get("/", headers={"User-Agent": "Googlebot/2.1 (+http://www.google.com/bot.html)"})
    check("visits: bot skipped", visit_counts()[0] == t1)
    client.get("/admin/")
    check("visits: admin skipped", visit_counts()[0] == t1)
    client.get("/api/payment-events?since=2020-01-01T00:00:00&token=x")
    check("visits: api skipped", visit_counts()[0] == t1)
    r = client.get("/")
    fhtml = r.data.decode()
    check("visits: footer shows counts",
          "آج کے وزٹر" in fhtml and str(visit_counts()[0]) in fhtml)
    yday = (_dt.utcnow() - _td(days=1)).strftime("%Y-%m-%d")
    db.session.add(VisitStat(day=yday, count=41))
    db.session.commit()
    tb, _ = visit_counts()
    client.get("/")
    check("visits: day rollover",
          visit_counts()[0] == tb + 1 and VisitStat.query.get(yday).count == 41)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/")
    dhtml = r.data.decode()
    check("visits: admin dashboard card",
          "👁️" in dhtml and "ویب سائٹ کے وزٹر" in dhtml
          and str(visit_counts()[1]) in dhtml)
    client.get("/logout")

print(f"\n==== {len(passed)} passed, {len(failed)} failed ====")
if failed:
    print("FAILED:", failed)
shutil.rmtree(tmpdir, ignore_errors=True)
sys.exit(1 if failed else 0)
