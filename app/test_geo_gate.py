"""Geo-gating tests: city-by-city launch (2026-10-07).

3 FULL DIVISIONS are open by default (Faisalabad, Sargodha, Lahore =
12 districts, default `open_districts` setting). All other districts render
a friendly construction page — listings never leak, and locked-district
submissions are rejected.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + tmpdir + "/geo.db"
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app, _migrate_open_districts
from models import (db, User, Listing, Setting,
                    open_district_slugs, is_district_open,
                    normalize_open_districts, OPEN_DISTRICTS_DEFAULT,
                    OPEN_DISTRICTS_OLD_DEFAULT)

TWELVE = ["faisalabad", "chiniot", "jhang", "toba-tek-singh",
          "sargodha", "bhakkar", "khushab", "mianwali",
          "lahore", "kasur", "nankana-sahib", "sheikhupura"]

app = create_app()
app.config["TESTING"] = True
client = app.test_client()

passed, failed = [], []


def check(name, cond):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name)


CONSTRUCTION = "جلد آ رہا ہے"  # "coming soon" marker on the construction page
CONSTRUCTION_PAGE = "🚧"  # unique to the construction page itself (the hostel
# browse dropdown legitimately lists locked districts with 🔒 markers)

with app.app_context():
    # --- setting defaults & helpers (3 full divisions = 12 districts) ---
    check("default open districts", open_district_slugs() == TWELVE)
    check("default constant", OPEN_DISTRICTS_DEFAULT == ",".join(TWELVE))
    check("old default constant",
          OPEN_DISTRICTS_OLD_DEFAULT == "lahore,faisalabad,sargodha")
    for d in TWELVE:
        check("open: " + d, is_district_open(d))
    check("multan locked", not is_district_open("multan"))
    check("rawalpindi locked", not is_district_open("rawalpindi"))
    check("normalize", normalize_open_districts("Lahore, FAISALABAD, bogus, lahore")
          == "lahore,faisalabad")

    # --- one-time migration: old 3-district default -> 12 districts ---
    mig = Setting(key="open_districts", value="lahore,faisalabad,sargodha")
    db.session.add(mig)
    db.session.commit()
    _migrate_open_districts()
    check("old default migrated to 12 districts",
          Setting.query.get("open_districts").value == ",".join(TWELVE))
    check("migrated slugs live", open_district_slugs() == TWELVE)
    _migrate_open_districts()  # second run is a no-op
    check("migration idempotent",
          Setting.query.get("open_districts").value == ",".join(TWELVE))
    mig.value = "lahore,multan"  # a customized setting must be untouched
    db.session.commit()
    _migrate_open_districts()
    check("customized setting untouched",
          Setting.query.get("open_districts").value == "lahore,multan")
    db.session.delete(mig)
    db.session.commit()
    check("default restored after migration tests",
          open_district_slugs() == TWELVE)

    # --- seed: landlord + approved listing in open faisalabad ---
    ll = User(public_id="G-LL", name="Malik", phone="03090000001",
              role="landlord", city="faisalabad-city",
              division="faisalabad", district="faisalabad")
    ll.set_password("pass1234")
    db.session.add(ll)
    db.session.commit()
    lst = Listing(title_ur="ٹیسٹ مکان فیصل آباد", landlord_id=ll.id,
                  city="faisalabad", division="faisalabad",
                  tehsil="faisalabad-city", monthly_rent=20000,
                  status="approved", photo_status="approved",
                  property_type="house")
    db.session.add(lst)
    db.session.commit()
    lid = lst.id
    # locked-district listing seeded directly (simulates pre-gate data)
    locked_lst = Listing(title_ur="بند مکان", landlord_id=ll.id,
                         city="multan", division="multan",
                         tehsil="multan-city", monthly_rent=15000,
                         status="approved", photo_status="approved",
                         property_type="house")
    db.session.add(locked_lst)
    db.session.commit()
    locked_lid = locked_lst.id

    # --- property browse: open vs locked ---
    r = client.get("/city/faisalabad")
    check("open district page 200", r.status_code == 200)
    check("open district shows listing",
          "ٹیسٹ مکان فیصل آباد" in r.data.decode())
    r = client.get("/city/multan")
    body = r.data.decode()
    check("locked district -> 200 construction", r.status_code == 200)
    check("construction text present", CONSTRUCTION in body)
    check("locked district leaks zero listings",
          "ٹیسٹ مکان فیصل آباد" not in body and "بند مکان" not in body)
    r = client.get("/city/chiniot")  # now OPEN under the 3-division default
    body = r.data.decode()
    check("chiniot now browsable",
          r.status_code == 200 and CONSTRUCTION not in body)
    r = client.get("/city/lalian")  # legacy tehsil slug of now-open chiniot
    check("legacy tehsil slug follows district (open)",
          r.status_code == 200 and CONSTRUCTION not in r.data.decode())
    r = client.get("/city/kasur")  # spot-check: 3rd division now open
    check("kasur now browsable",
          r.status_code == 200 and CONSTRUCTION not in r.data.decode())
    r = client.get(f"/listing/{lid}")
    check("open listing detail 200", r.status_code == 200)
    r = client.get(f"/listing/{locked_lid}")
    check("locked listing detail -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    r = client.get("/")
    check("home hides locked listings", "بند مکان" not in r.data.decode())

    # --- search/filter gate ---
    r = client.get("/listings?district=multan")
    check("search locked district -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    r = client.get("/listings?district=jhang")
    check("search open district (jhang) 200",
          r.status_code == 200 and CONSTRUCTION not in r.data.decode())

    # --- division page: locked districts marked ---
    r = client.get("/division/multan")
    body = r.data.decode()
    check("division page 200", r.status_code == 200)
    check("locked district marked coming-soon",
          "lodhran" in body and CONSTRUCTION in body)
    check("division featured hides locked listings",
          "بند مکان" not in body)
    r = client.get("/division/faisalabad")
    body = r.data.decode()
    check("faisalabad division fully open (no coming-soon)",
          "chiniot" in body and "ٹیسٹ مکان فیصل آباد" in body)

    # --- listing POST gates (landlord) ---
    client.post("/login", data={"phone": "03090000001", "password": "pass1234"})
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "بند شہر مکان", "monthly_rent": "10000",
        "division": "multan", "district": "multan", "tehsil": "multan-city",
        "property_type": "house"})
    check("locked listing POST -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    check("locked listing not created",
          Listing.query.filter_by(title_ur="بند شہر مکان").first() is None)
    # open district POST passes the gate (fails later on photo, as designed)
    r = client.post("/dashboard/listings/new", data={
        "title_ur": "کھلا شہر مکان", "monthly_rent": "10000",
        "division": "faisalabad", "district": "faisalabad",
        "tehsil": "faisalabad-city", "property_type": "house"})
    check("open listing POST passes gate",
          CONSTRUCTION not in r.data.decode())
    client.get("/logout")

    # --- user registration gate ---
    r = client.post("/register", data={
        "name": "Locked", "phone": "03090000002", "password": "pass1234",
        "role": "renter", "division": "multan", "district": "multan",
        "tehsil": "multan-city"})
    check("locked-district signup -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    check("locked signup creates no user",
          User.query.filter_by(phone="03090000002").first() is None)
    r = client.post("/register", data={
        "name": "Open", "phone": "03090000003", "password": "pass1234",
        "role": "renter", "division": "lahore", "district": "lahore",
        "tehsil": "lahore-city"})
    check("open-district signup -> redirect", r.status_code in (301, 302))
    client.get("/logout")

    # --- hostel browse gates ---
    r = client.get("/hostels/faisalabad")
    check("hostel open district 200", r.status_code == 200)
    r = client.get("/hostels/chiniot")
    check("hostel chiniot now open",
          r.status_code == 200 and CONSTRUCTION_PAGE not in r.data.decode())
    r = client.get("/hostels?district=multan")
    check("hostel query locked -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    r = client.get("/hostels/multan")
    check("hostel multan -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    r = client.get("/hostels/kasur")
    check("hostel kasur now open",
          r.status_code == 200 and CONSTRUCTION_PAGE not in r.data.decode())

    # --- hostel registration gate ---
    r = client.post("/hostel/register", data={
        "name": "H", "phone": "03090000004", "password": "pass1234",
        "cnic": "35202-1111111-1", "hostel_name_ur": "بند ہاسٹل",
        "district": "multan", "address": "Addr"})
    check("hostel register locked -> construction",
          r.status_code == 200 and CONSTRUCTION in r.data.decode())
    check("hostel not created",
          User.query.filter_by(phone="03090000004").first() is None)

    # --- flipping the admin setting opens a city ---
    s = Setting(key="open_districts",
                value=",".join(TWELVE + ["multan"]))
    db.session.add(s)
    db.session.commit()
    check("setting flip opens multan", is_district_open("multan"))
    r = client.get("/city/multan")
    body = r.data.decode()
    check("flipped city browsable",
          r.status_code == 200 and CONSTRUCTION not in body
          and "بند مکان" in body)
    s.value = ",".join(TWELVE)
    db.session.commit()
    check("restore locks multan", not is_district_open("multan"))

    # --- admin settings page round-trip ---
    admin = User(public_id="G-AD", name="Admin", phone="03090000009",
                 role="admin", city="lahore")
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()
    client.post("/login", data={"phone": "03090000009", "password": "admin123"})
    r = client.get("/admin/settings")
    check("admin settings 200", r.status_code == 200)
    check("settings shows open_districts field",
          'name="open_districts"' in r.data.decode())
    r = client.post("/admin/settings",
                    data={"open_districts": "lahore, faisalabad, SARGODHA, bogus"},
                    follow_redirects=True)
    check("settings save 200", r.status_code == 200)
    check("settings normalized on save",
          open_district_slugs() == ["lahore", "faisalabad", "sargodha"])
    r = client.post("/admin/settings", data={"open_districts": "bogus, nope"},
                    follow_redirects=True)
    check("bad input keeps old list",
          open_district_slugs() == ["lahore", "faisalabad", "sargodha"])

print()
if failed:
    print("FAILED:", failed)
    raise SystemExit(1)
print("ALL GEO-GATE TESTS PASSED ✔ (%d)" % len(passed))
