"""Seed demo data: admin, demo users, settings, 9 listings with demo house photos."""
import os, sys, shutil, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from datetime import datetime, timedelta
from app import create_app
from models import (db, User, Listing, ListingPhoto, Setting, TokenLedger, Draw,
                    award_tokens, ensure_referral_code)

BASE = os.path.dirname(os.path.abspath(__file__))
dbpath = os.path.join(BASE, "data", "kirayanama.db")
if os.path.exists(dbpath):
    os.remove(dbpath)

# Map each demo listing to one of the 4 royal house photos (by property type)
HOUSE_PHOTOS = {
    "house":   ["house-2.jpg", "house-1.jpg"],
    "portion": ["house-4.jpg", "house-1.jpg"],
    "room":    ["house-4.jpg"],
    "shop":    ["house-3.jpg"],
}

def _clear_stale_demos():
    d = os.path.join(BASE, "static", "uploads", "listings")
    os.makedirs(d, exist_ok=True)
    for old in glob.glob(os.path.join(d, "demo_*")):
        try: os.remove(old)
        except OSError: pass

def demo_photo(ptype, idx, fname):
    d = os.path.join(BASE, "static", "uploads", "listings")
    os.makedirs(d, exist_ok=True)
    pool = HOUSE_PHOTOS.get(ptype, ["house-1.jpg"])
    src = os.path.join(BASE, "static", "images", pool[idx % len(pool)])
    dst = os.path.join(d, fname)
    shutil.copyfile(src, dst)
    return fname

app = create_app()

LISTINGS = [
    # chiniot
    ("چنیوٹ میں 5 مرلہ مکان", "5 Marla House in Chiniot", "صاف ستھرا مکان، بجلی پانی گیس کی سہولت۔", "chiniot", "محلہ اسلام پورہ", "house", 3, 2, 1500, 20000),
    ("چنیوٹ بازار میں دکان", "Shop in Chiniot Bazaar", "مین بازار میں کاروبار کے لیے بہترین دکان۔", "chiniot", "مین بازار", "shop", 0, 1, 300, 15000),
    ("لالیاں روڈ پر پورشن", "Portion on Lalian Road", "الگ گیٹ والا اوپر کا پورشن۔", "chiniot", "لالیاں روڈ", "portion", 2, 1, 900, 12000),
    # lalian
    ("لالیاں میں 10 مرلہ مکان", "10 Marla House in Lalian", "کھلا صحن، دو منزلہ مکان۔", "lalian", "محلہ فاروقیہ", "house", 4, 3, 2700, 28000),
    ("لالیاں میں کمرہ کرائے پر", "Room for rent in Lalian", "اکیلے فرد کے لیے کمرہ۔", "lalian", "نزد ریلوے اسٹیشن", "room", 1, 1, 250, 6000),
    ("لالیاں میں دکان", "Shop in Lalian", "چوک میں دکان، ہر کاروبار کے لیے موزوں۔", "lalian", "مین چوک", "shop", 0, 1, 400, 18000),
    # bhuwana
    ("بھوانہ میں 7 مرلہ مکان", "7 Marla House in Bhuwana", "نیا تعمیر شدہ مکان، ٹائل پتھر۔", "bhuwana", "محلہ غوثیہ", "house", 3, 2, 1900, 22000),
    ("بھوانہ میں پورشن", "Portion in Bhuwana", "نیچے کا پورشن، الگ میٹر۔", "bhuwana", "کالج روڈ", "portion", 2, 1, 1000, 14000),
    ("بھوانہ بازار میں دکان", "Shop in Bhuwana Bazaar", "رش والی جگہ پر دکان۔", "bhuwana", "مین بازار", "shop", 0, 1, 350, 16000),
]

with app.app_context():
    admin = User(public_id="KN-1", name="Admin", phone="03115021212", role="admin", city="chiniot",
                 division="faisalabad", district="chiniot")
    admin.set_password("admin123")
    ll = User(public_id="KN-1001", name="Malik Ashfaq", phone="03011111111", role="landlord", city="chiniot",
            division="faisalabad", district="chiniot")
    ll.set_password("landlord123")
    renter = User(public_id="KN-1002", name="Bilal Ahmed", phone="03022222222", role="renter", city="lalian",
                division="faisalabad", district="chiniot")
    renter.set_password("renter123")
    # demo lucky-draw users
    sana = User(public_id="KN-1003", name="Sana Bibi", phone="03044444444", role="renter", city="chiniot",
              division="faisalabad", district="chiniot")
    sana.set_password("demo1234")
    db.session.add_all([admin, ll, renter, sana])
    db.session.flush()
    for u in (admin, ll, renter, sana):
        ensure_referral_code(u)
    # sana was referred by Bilal
    sana.referred_by = renter.id
    db.session.add(Setting(key="jazzcash_number", value="03115021212"))
    db.session.add(Setting(key="easypaisa_number", value="03115021212"))
    db.session.add(Setting(key="upaisa_number", value="03115021212"))
    db.session.add(Setting(key="hbl_account", value="01737900590403"))
    db.session.commit()
    # demo token ledger: signup bonuses + one referral + one past drawn winner
    award_tokens(ll.id, 5, "signup_bonus")
    award_tokens(renter.id, 5, "signup_bonus")
    award_tokens(sana.id, 5, "signup_bonus")
    award_tokens(renter.id, 5, "referral")          # Bilal referred Sana
    award_tokens(sana.id, 20, "deal_entry")        # Sana completed deals before
    db.session.commit()
    past = Draw(title="پہلی ماہانہ قرعہ اندازی", status="drawn", winner_id=sana.id,
                drawn_at=datetime.utcnow() - timedelta(days=30), prize="prize_1month")
    db.session.add(past)
    db.session.commit()

    _clear_stale_demos()
    from punjab_divisions import resolve_location
    for i, (tu, te, du, city, area, ptype, br, ba, sqft, rent) in enumerate(LISTINGS):
        _div, _dist, _teh = resolve_location(city=city)
        l = Listing(landlord_id=ll.id, title_ur=tu, title_en=te, desc_ur=du,
                    city=_dist, division=_div, tehsil=_teh,
                    area=area, exact_address=f"{area}، گلی نمبر {i+1}، مکان نمبر {10+i}",
                    property_type=ptype, bedrooms=br,
                    bathrooms=ba, area_sqft=sqft, monthly_rent=rent, status="approved")
        db.session.add(l)
        db.session.flush()
        fn = demo_photo(ptype, i, f"demo_{i+1}.jpg")
        db.session.add(ListingPhoto(listing_id=l.id, filename=fn, is_primary=True, sort_order=0))
    db.session.commit()
    print("seeded:", User.query.count(), "users,", Listing.query.count(), "listings")
print("SEED DONE")
