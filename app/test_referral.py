"""Marketing-agent referral tracking tests (2026-10-07, Razi's cousin plan).

Covers: admin code creation (normalization, duplicates, invalid rejected);
?ref=CODE attribution on landlord/renter registration; 30-day cookie fallback;
invalid codes ignored silently; deactivated codes stop attributing;
per-agent counts (signups/listings/verified) + amount-due math; hostel-owner
registration attribution; admin agents page renders.
"""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

tmpdir = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tmpdir, "t.db")
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app
from models import (db, User, Listing, ReferralCode, normalize_agent_code,
                    get_active_agent_code, agent_stats, next_public_id,
                    AGENT_REF_COOKIE)

app = create_app()
app.config["TESTING"] = True
client = app.test_client()

passed, failed = [], []
def check(name, cond):
    (passed if cond else failed).append(name)
    print(("PASS " if cond else "FAIL ") + name)


def mkuser(name, phone, role="landlord", agent_ref=""):
    u = User(public_id=next_public_id(), name=name, phone=phone, role=role,
             agent_ref=agent_ref)
    u.set_password("secret12")
    db.session.add(u)
    db.session.commit()
    return u


def mklisting(landlord, status="approved"):
    l = Listing(landlord_id=landlord.id, title_ur="t", title_en="t",
                desc_ur="d", city="faisalabad", monthly_rent=20000,
                status=status)
    db.session.add(l)
    db.session.commit()
    return l


with app.app_context():
    import sqlalchemy as sa
    insp = sa.inspect(db.engine)
    check("referral_codes table", "referral_codes" in insp.get_table_names())
    ucols = {c["name"] for c in insp.get_columns("users")}
    check("users.agent_ref column", "agent_ref" in ucols)

    # --- normalization ---
    check("normalize ok", normalize_agent_code("Ahmed-LHR") == "ahmed-lhr")
    check("normalize strips", normalize_agent_code("  x-1 ") == "x-1")
    check("normalize rejects spaces", normalize_agent_code("a b") == "")
    check("normalize rejects empty", normalize_agent_code("") == "")
    check("normalize rejects symbols", normalize_agent_code("a/b") == "")

    # --- seed admin ---
    admin = User(public_id="T-ADM", name="Admin", phone="03000000001", role="admin")
    admin.set_password("admin123")
    db.session.add(admin)
    db.session.commit()
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})

    # --- admin creates a code ---
    r = client.post("/admin/agents/new", data={
        "code": "Ahmed-LHR", "agent_name": "Ahmed",
        "territory": "Lahore", "per_listing_rate": "200"})
    check("create redirects to list", r.status_code == 302)
    rc = ReferralCode.query.filter_by(code="ahmed-lhr").first()
    check("code stored lowercase", rc is not None and rc.code == "ahmed-lhr")
    check("rate stored", rc.per_listing_rate == 200)
    check("active by default", rc.is_active is True)

    # --- duplicate rejected ---
    r = client.post("/admin/agents/new", data={
        "code": "ahmed-lhr", "agent_name": "Dupe", "territory": "",
        "per_listing_rate": "150"})
    check("duplicate not created",
          ReferralCode.query.filter_by(code="ahmed-lhr").count() == 1)

    # --- invalid code rejected ---
    r = client.post("/admin/agents/new", data={
        "code": "bad code!", "agent_name": "Bad", "territory": "",
        "per_listing_rate": "150"})
    check("invalid code not created",
          ReferralCode.query.filter_by(agent_name="Bad").count() == 0)

    # --- edit ---
    r = client.post(f"/admin/agents/{rc.id}/edit", data={
        "agent_name": "Ahmed Raza", "territory": "Lahore",
        "per_listing_rate": "175"})
    rc = ReferralCode.query.get(rc.id)
    check("edit saves", rc.agent_name == "Ahmed Raza" and rc.per_listing_rate == 175)

    # --- get_active_agent_code ---
    check("active code resolves", get_active_agent_code("ahmed-lhr") is not None)
    check("unknown code None", get_active_agent_code("nope-1") is None)

    # --- ?ref=CODE attribution on registration ---
    client.get("/logout")
    client.get("/?ref=ahmed-lhr")  # capture on any page
    r = client.post("/register", data={
        "name": "Landlord One", "phone": "03000000011",
        "password": "secret12", "role": "landlord"})
    u1 = User.query.filter_by(phone="03000000011").first()
    check("registration attributed", u1 is not None and u1.agent_ref == "ahmed-lhr")

    # --- invalid ?ref= ignored silently ---
    # (clear the 30-day cookie set by the earlier ?ref= visit first)
    client.get("/logout")
    client.delete_cookie(AGENT_REF_COOKIE)
    client.get("/?ref=BAD CODE!!")
    r = client.post("/register", data={
        "name": "Landlord Two", "phone": "03000000012",
        "password": "secret12", "role": "landlord"})
    u2 = User.query.filter_by(phone="03000000012").first()
    check("invalid ref ignored", u2 is not None and (u2.agent_ref or "") == "")

    # --- 30-day cookie fallback ---
    client.get("/logout")
    client.set_cookie(AGENT_REF_COOKIE, "ahmed-lhr")
    r = client.post("/register", data={
        "name": "Renter Three", "phone": "03000000013",
        "password": "secret12", "role": "renter"})
    u3 = User.query.filter_by(phone="03000000013").first()
    check("cookie fallback attributes", u3 is not None and u3.agent_ref == "ahmed-lhr")
    client.delete_cookie(AGENT_REF_COOKIE)
    # cookie max age is 30 days
    with client.session_transaction():
        pass  # session valid

    # --- deactivated code stops attributing ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    client.post(f"/admin/agents/{rc.id}/toggle")  # deactivate
    check("deactivated", ReferralCode.query.get(rc.id).is_active is False)
    check("deactivated not resolvable",
          get_active_agent_code("ahmed-lhr") is None)
    client.get("/logout")
    client.get("/?ref=ahmed-lhr")
    r = client.post("/register", data={
        "name": "Landlord Four", "phone": "03000000014",
        "password": "secret12", "role": "landlord"})
    u4 = User.query.filter_by(phone="03000000014").first()
    check("deactivated code ignored", u4 is not None and (u4.agent_ref or "") == "")
    # reactivate for stats tests (u4's registration auto-logged-in u4)
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    client.post(f"/admin/agents/{rc.id}/toggle")
    check("reactivated", ReferralCode.query.get(rc.id).is_active is True)

    # --- hostel owner registration attribution ---
    client.get("/logout")
    client.get("/?ref=ahmed-lhr")
    r = client.post("/hostel/register", data={
        "name": "Hostel Owner", "phone": "03000000015", "password": "secret12",
        "cnic": "3310012345671", "hostel_name_ur": "ٹیسٹ ہاسٹل",
        "district": "faisalabad", "address": "test address"})
    uh = User.query.filter_by(phone="03000000015").first()
    check("hostel owner attributed",
          uh is not None and uh.role == "hostel_owner" and uh.agent_ref == "ahmed-lhr")

    # --- per-agent stats ---
    mklisting(u1, "approved")
    mklisting(u1, "approved")
    mklisting(u1, "pending")
    mklisting(u2, "approved")  # not attributed -> excluded
    st = agent_stats("ahmed-lhr")
    check("stats signups", st["signups"] == 3)  # u1, u3, uh
    check("stats listings", st["listings"] == 3)
    check("stats verified", st["verified"] == 2)
    check("amount due = 2 x 175", st["amount_due"] == 350)

    # --- unknown code stats are zeros ---
    st0 = agent_stats("nope-1")
    check("unknown code zeros",
          st0["signups"] == 0 and st0["amount_due"] == 0)

    # --- admin agents page renders with stats ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000001", "password": "admin123"})
    r = client.get("/admin/agents")
    body = r.get_data(as_text=True)
    check("agents page 200", r.status_code == 200)
    check("agents page shows code", "ahmed-lhr" in body)
    check("agents page shows amount", "350" in body)

    # --- non-admin blocked ---
    client.get("/logout")
    client.post("/login", data={"phone": "03000000011", "password": "secret12"})
    r = client.get("/admin/agents")
    check("non-admin 403", r.status_code == 403)

print("\n%d passed, %d failed" % (len(passed), len(failed)))
sys.exit(1 if failed else 0)
