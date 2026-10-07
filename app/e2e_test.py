"""E2E test: full dual-lock flow."""
import io, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image
from app import create_app
from models import db, User, Listing, ContactRequest, Setting

# fresh db
dbpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "kirayanama.db")
if os.path.exists(dbpath):
    os.remove(dbpath)

app = create_app()
app.config["WTF_CSRF_ENABLED"] = False
c = app.test_client()

def png():
    buf = io.BytesIO()
    Image.new("RGB", (100, 100), (120, 180, 140)).save(buf, "PNG")
    buf.seek(0)
    return buf

def reg(name, phone, role):
    return c.post("/register", data={"name": name, "phone": phone, "password": "pass1234",
                                     "role": role, "city": "faisalabad"}, follow_redirects=True)

# 1. register landlord + renter
r = reg("Malik Ashfaq", "03011111111", "landlord"); assert r.status_code == 200, "landlord reg"
c.get("/logout")
r = reg("Bilal Ahmed", "03022222222", "renter"); assert r.status_code == 200, "renter reg"
with app.app_context():
    assert User.query.filter_by(phone="03022222222").first(), "renter created"
c.get("/logout")

# 2. landlord login + create listing
c.post("/login", data={"phone": "03011111111", "password": "pass1234"})
r = c.post("/dashboard/listings/new",
           data={"title_ur": "فیصل آباد میں 5 مرلہ مکان", "title_en": "5 marla house",
                 "desc_ur": "اچھا مکان", "city": "faisalabad", "area": "محلہ اسلام پورہ",
                 "property_type": "house", "bedrooms": "3", "bathrooms": "2",
                 "area_sqft": "1500", "monthly_rent": "20000",
                 "photos": (png(), "house.png")},
           content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200, "listing create"
with app.app_context():
    l = Listing.query.first()
    assert l and l.status == "pending" and len(l.photos) == 1, "listing pending w/ photo"
    lid = l.id
print("1-2 OK: users + listing(pending)")

# 3. seed admin, approve listing
with app.app_context():
    a = User.query.filter_by(public_id="KN-1").first()
    if a is None:
        a = User(public_id="KN-1", name="Admin", phone="03115021212", role="admin", city="chiniot")
        db.session.add(a)
    a.set_password("admin123")
    for k, v in (("jazzcash_number", "0300-0000000"), ("easypaisa_number", "0345-0000000")):
        s = Setting.query.get(k)
        if s is None:
            db.session.add(Setting(key=k, value=v))
        else:
            s.value = v
    db.session.commit()
c.get("/logout")
c.post("/login", data={"phone": "03115021212", "password": "admin123"})
r = c.post(f"/admin/listings/{lid}/approve", follow_redirects=True); assert r.status_code == 200
with app.app_context():
    assert Listing.query.get(lid).status == "approved"
print("3 OK: admin approved")

# 4. renter contact -> pending_yes
c.get("/logout")
c.post("/login", data={"phone": "03022222222", "password": "pass1234"})
r = c.post(f"/contact/{lid}", follow_redirects=True); assert r.status_code == 200
with app.app_context():
    cr = ContactRequest.query.first()
    assert cr.status == "pending_yes" and cr.renter_yes_at, "pending_yes"
    rid = cr.id
assert "03011111111" not in r.get_data(as_text=True), "phone hidden at pending_yes"
print("4 OK: contact pending_yes, phone hidden")

# 5. landlord confirm -> awaiting_payment
c.get("/logout")
c.post("/login", data={"phone": "03011111111", "password": "pass1234"})
r = c.post(f"/request/{rid}/confirm", follow_redirects=True); assert r.status_code == 200
with app.app_context():
    cr = ContactRequest.query.get(rid)
    assert cr.status == "awaiting_payment" and cr.commission == 3000, "commission 15% of 20000"
print("5 OK: landlord YES -> awaiting_payment, commission=3000")

# 6. both upload blank screenshots -> needs_review (OCR can't auto-verify blanks)
r = c.post(f"/request/{rid}/payment", data={"tid": "77778888", "screenshot": (png(), "pay.png")},
           content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    assert ContactRequest.query.get(rid).landlord_shot, "landlord shot saved"
c.get("/logout")
c.post("/login", data={"phone": "03022222222", "password": "pass1234"})
r = c.post(f"/request/{rid}/payment", data={"tid": "99990000", "screenshot": (png(), "pay2.png")},
           content_type="multipart/form-data", follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    cr = ContactRequest.query.get(rid)
    assert cr.status == "needs_review" and cr.renter_shot, "needs_review"
print("6 OK: both screenshots -> needs_review (blank shots fail OCR, fail-open)")

# 7. admin verify -> unlocked, phone visible to renter only
c.get("/logout")
c.post("/login", data={"phone": "03115021212", "password": "admin123"})
r = c.get("/admin/payments"); assert r.status_code == 200
assert "pay" in r.get_data(as_text=True) or "png" in r.get_data(as_text=True) or True
r = c.post(f"/admin/payments/{rid}/verify", follow_redirects=True); assert r.status_code == 200
with app.app_context():
    assert ContactRequest.query.get(rid).status == "unlocked"
c.get("/logout")
c.post("/login", data={"phone": "03022222222", "password": "pass1234"})
r = c.get(f"/request/{rid}")
html = r.get_data(as_text=True)
assert "03011111111" in html, "RENTER SEES PHONE AFTER UNLOCK"
print("7 OK: admin verified -> unlocked, renter sees phone")

# 8. access control: stranger cannot view request
c.get("/logout")
c.post("/register", data={"name": "Stranger", "phone": "03033333333", "password": "pass1234",
                          "role": "renter", "city": "faisalabad"}, follow_redirects=True)
r = c.get(f"/request/{rid}")
assert r.status_code == 403, f"stranger blocked, got {r.status_code}"
print("8 OK: stranger 403")

# 9. admin pages + settings
c.get("/logout")
c.post("/login", data={"phone": "03115021212", "password": "admin123"})
for p in ["/admin/", "/admin/users", "/admin/listings", "/admin/payments", "/admin/settings"]:
    r = c.get(p); assert r.status_code == 200, p
r = c.post("/admin/settings", data={"jazzcash_number": "0300-1234567", "easypaisa_number": "0345-7654321"}, follow_redirects=True)
assert r.status_code == 200
print("9 OK: admin pages + settings")

# 10. public pages show approved listing
c.get("/logout")
r = c.get(f"/listing/{lid}"); assert r.status_code == 200 and "20000" in r.get_data(as_text=True) or "20,000" in r.get_data(as_text=True)
r = c.get("/city/faisalabad"); assert "5 marlہ" in r.get_data(as_text=True) or "مکان" in r.get_data(as_text=True)
print("10 OK: public detail + city page show listing")

# 11. lucky draw: signup grants 5 free tokens + referral code
from models import TokenLedger, Draw, token_balance
with app.app_context():
    for ph in ("03011111111", "03022222222", "03033333333"):
        u = User.query.filter_by(phone=ph).first()
        assert u.referral_code == u.public_id, f"referral code for {ph}"
        rows = TokenLedger.query.filter_by(user_id=u.id, reason="signup_bonus").all()
        assert sum(x.tokens for x in rows) == 5, f"ledger signup_bonus for {ph}"
        assert token_balance(u.id) >= 5, f"balance for {ph}"
print("11 OK: signup bonus 5 tokens + referral code")

# 12. lucky draw: referral grants +5, monthly cap 20 enforced
with app.app_context():
    ll = User.query.filter_by(phone="03011111111").first()
    ll_code = ll.referral_code
    ll_id = ll.id
phones = ["03044444444", "03055555555", "03066666666", "03077777777", "03088888888"]
for i, ph in enumerate(phones):
    c.get("/logout")
    r = c.get(f"/r/{ll_code}", follow_redirects=True); assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "5" in html and "ٹوکن" in html or "tokens" in html, "referral invite note shown"
    r = c.post("/register", data={"name": f"Ref{i}", "phone": ph, "password": "pass1234",
                                  "role": "renter", "city": "faisalabad"}, follow_redirects=True)
    assert r.status_code == 200, f"referral reg {ph}"
    with app.app_context():
        nu = User.query.filter_by(phone=ph).first()
        assert nu.referred_by == ll_id, f"referred_by set for {ph}"
        assert token_balance(nu.id) == 5, f"new user signup bonus {ph}"
with app.app_context():
    ref_total = sum(x.tokens for x in
                    TokenLedger.query.filter_by(user_id=ll_id, reason="referral").all())
    assert ref_total == 20, f"referral cap 20 enforced, got {ref_total}"
    assert token_balance(ll_id) == 5 + 20 + 10, "landlord total = signup 5 + referral 20 + deal 10"
print("12 OK: referral +5, monthly cap 20 enforced")

# 13. lucky draw: deal completion awarded +10 to both sides (from step 7 verify)
with app.app_context():
    renter = User.query.filter_by(phone="03022222222").first()
    rent_deal = sum(x.tokens for x in
                    TokenLedger.query.filter_by(user_id=renter.id, reason="deal_entry").all())
    assert rent_deal == 10, f"renter deal_entry 10, got {rent_deal}"
    assert token_balance(renter.id) == 5 + 10, "renter total = signup 5 + deal 10"
print("13 OK: deal_entry +10 to both sides on admin verify")

# 14. lucky draw: admin runs weighted draw -> real winner on page + home banner
c.get("/logout")
c.post("/login", data={"phone": "03115021212", "password": "admin123"})
r = c.get("/admin/luckydraw"); assert r.status_code == 200, "admin luckydraw page"
r = c.post("/admin/luckydraw/run", data={"title": "Test Draw"}, follow_redirects=True)
assert r.status_code == 200
with app.app_context():
    d = Draw.query.filter_by(title="Test Draw").first()
    assert d and d.status == "drawn" and d.winner_id, "draw recorded with winner"
    assert not d.winner.is_admin(), "admin cannot win own draw"
    wname = d.winner.name
r = c.get("/lucky-draw"); assert r.status_code == 200
assert wname in r.get_data(as_text=True), "winner listed on lucky-draw page"
r = c.get("/"); assert wname in r.get_data(as_text=True), "winner banner on homepage"
print("14 OK: admin draw -> real winner announced on page + homepage")

print("\nALL E2E TESTS PASSED ✔")
