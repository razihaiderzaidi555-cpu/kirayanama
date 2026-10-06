"""KirayaNama data models. Single source of truth — workers import from here, do not redefine."""
from datetime import datetime, timedelta
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from punjab_divisions import district_slugs

db = SQLAlchemy()

# All Punjab district slugs (Division -> District -> Tehsil model).
# Listing.city / legacy User.city values resolve through resolve_location().
CITIES = sorted(district_slugs())
PROPERTY_TYPES = ["house", "shop", "portion", "room"]
LISTING_STATUS = ["pending", "approved", "rejected"]
REQUEST_STATUS = ["pending_yes", "awaiting_payment", "in_review", "unlocked",
                  "rejected", "cancelled"]
COMMISSION_RATE = 0.15  # per side; platform total = 30% of monthly rent
DEALER_DEFAULT_SHARE = 5.0  # percentage POINTS of rent paid to dealer on their deals
SUSPICIOUS_MIN_VIEWS = 20  # views with zero unlocks -> flag listing
SUSPICIOUS_MIN_CANCELLATIONS = 3  # cancelled requests -> flag user


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(db.String(16), unique=True, nullable=False)  # KN-1001
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(20), unique=True, nullable=False)  # login id
    email = db.Column(db.String(120), nullable=True)  # for OTP recovery + notifications
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="renter")  # landlord/renter/dealer/admin
    city = db.Column(db.String(40), default="")  # tehsil slug (legacy: old flat city slug)
    division = db.Column(db.String(40), default="")  # division slug
    district = db.Column(db.String(40), default="")  # district slug
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)
    # referral system (lucky draw)
    referral_code = db.Column(db.String(16), unique=True)  # e.g. KN-1001 (== public_id)
    referred_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    # dealer fields
    dealer_verified = db.Column(db.Boolean, default=False)  # "Verified Dealer" badge
    dealer_share = db.Column(db.Float, default=DEALER_DEFAULT_SHARE)  # % points of rent
    warnings = db.Column(db.Integer, default=0)  # anti-bypass warnings issued

    listings = db.relationship("Listing", backref="landlord", lazy=True)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def is_admin(self):
        return self.role == "admin"

    def is_dealer(self):
        return self.role == "dealer"


class Listing(db.Model):
    __tablename__ = "listings"
    id = db.Column(db.Integer, primary_key=True)
    landlord_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    title_ur = db.Column(db.String(200), nullable=False)
    title_en = db.Column(db.String(200), nullable=False, default="")
    desc_ur = db.Column(db.Text, nullable=False, default="")
    desc_en = db.Column(db.Text, nullable=False, default="")
    city = db.Column(db.String(40), nullable=False)  # DISTRICT slug (legacy: old flat city slug)
    division = db.Column(db.String(40), nullable=True)  # division slug
    tehsil = db.Column(db.String(40), nullable=True)  # tehsil slug
    area = db.Column(db.String(120), default="")  # mohalla/society — PUBLIC
    exact_address = db.Column(db.String(255), default="")  # street/house no — MASKED until unlock
    # map pin set by landlord AFTER the deal unlocks; shown to the renter of that deal only
    location_lat = db.Column(db.Float, nullable=True)
    location_lng = db.Column(db.Float, nullable=True)
    # landlord closed the listing after renting out — hidden from public browse
    is_closed = db.Column(db.Boolean, default=False)
    property_type = db.Column(db.String(20), default="house")
    bedrooms = db.Column(db.Integer, default=0)
    bathrooms = db.Column(db.Integer, default=0)
    area_sqft = db.Column(db.Integer, default=0)
    monthly_rent = db.Column(db.Integer, nullable=False)  # PKR
    status = db.Column(db.String(20), default="pending")
    rejection_reason = db.Column(db.String(255), default="")  # shown to lister when rejected
    view_count = db.Column(db.Integer, default=0)  # anti-bypass monitoring
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    photos = db.relationship("ListingPhoto", backref="listing", lazy=True,
                             cascade="all, delete-orphan",
                             order_by="ListingPhoto.sort_order")

    @property
    def primary_photo(self):
        for p in self.photos:
            if p.is_primary:
                return p
        return self.photos[0] if self.photos else None


class ListingPhoto(db.Model):
    __tablename__ = "listing_photos"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    is_primary = db.Column(db.Boolean, default=False)
    sort_order = db.Column(db.Integer, default=0)


class ContactRequest(db.Model):
    __tablename__ = "contact_requests"
    id = db.Column(db.Integer, primary_key=True)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    renter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    landlord_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(30), default="pending_yes")
    renter_yes_at = db.Column(db.DateTime, nullable=True)
    landlord_yes_at = db.Column(db.DateTime, nullable=True)
    renter_shot = db.Column(db.String(255), nullable=True)
    landlord_shot = db.Column(db.String(255), nullable=True)
    renter_paid_at = db.Column(db.DateTime, nullable=True)
    landlord_paid_at = db.Column(db.DateTime, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # dealer economics: snapshot at unlock time
    dealer_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    dealer_earning = db.Column(db.Integer, default=0)  # PKR paid to dealer on this deal

    listing = db.relationship("Listing", backref="contact_requests")
    renter = db.relationship("User", foreign_keys=[renter_id])
    landlord = db.relationship("User", foreign_keys=[landlord_id])
    dealer = db.relationship("User", foreign_keys=[dealer_id])

    @property
    def commission(self):
        return int(round((self.listing.monthly_rent or 0) * COMMISSION_RATE))

    @property
    def dealer_cut(self):
        """Dealer's share in PKR, computed from the listing owner's dealer_share."""
        owner = self.listing.landlord if self.listing else None
        if not owner or not owner.is_dealer():
            return 0
        return int(round((self.listing.monthly_rent or 0) * (owner.dealer_share or 0) / 100.0))


class Setting(db.Model):
    __tablename__ = "settings"
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(255), default="")


class PasswordReset(db.Model):
    """Email-OTP password recovery. Codes are hashed; expire in 10 minutes."""
    __tablename__ = "password_resets"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    code_hash = db.Column(db.String(255), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)
    attempts = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User")


class Rating(db.Model):
    """Renter rates the landlord after a deal unlocks — one per deal."""
    __tablename__ = "ratings"
    id = db.Column(db.Integer, primary_key=True)
    contact_request_id = db.Column(db.Integer, db.ForeignKey("contact_requests.id"),
                                   unique=True, nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey("listings.id"), nullable=False)
    renter_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    landlord_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    stars = db.Column(db.Integer, nullable=False)  # 1-5
    comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


# ---------- Lucky Draw: free token ledger + draws ----------
# All tokens are FREE (signup bonus, referrals, completed deals). Nothing is
# purchasable. Winners are always real users picked by weighted random draw.

TOKEN_SIGNUP_BONUS = 5      # tokens granted on registration
TOKEN_REFERRAL = 5         # tokens per verified referral
TOKEN_REFERRAL_MONTHLY_CAP = 20  # max referral tokens per user per calendar month
TOKEN_DEAL_ENTRY = 10      # tokens per side when a rental deal completes


class TokenLedger(db.Model):
    __tablename__ = "token_ledger"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    tokens = db.Column(db.Integer, nullable=False, default=0)
    reason = db.Column(db.String(30), nullable=False, default="")  # signup_bonus/referral/deal_entry
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", backref="token_entries")


class Draw(db.Model):
    __tablename__ = "draws"
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="open")  # open/drawn
    winner_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    drawn_at = db.Column(db.DateTime, nullable=True)
    prize = db.Column(db.String(80), nullable=False, default="prize_1month")  # translation key
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    winner = db.relationship("User", foreign_keys=[winner_id])


class WheelSpin(db.Model):
    """Every wheel spin is recorded server-side.

    Used for: max 3 spins per rolling 24h, and the cumulative counter that
    awards one month of free rent to renters at 1000 total spins.
    """
    __tablename__ = "wheel_spins"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship("User", foreign_keys=[user_id])


def wheel_spins_total(user_id):
    """Cumulative spin count for a user."""
    if not user_id:
        return 0
    return WheelSpin.query.filter_by(user_id=user_id).count()


def wheel_spins_24h(user_id):
    """Spins in the last rolling 24 hours."""
    if not user_id:
        return 0
    day_ago = datetime.utcnow() - timedelta(hours=24)
    return (WheelSpin.query.filter_by(user_id=user_id)
            .filter(WheelSpin.created_at > day_ago).count())


def get_setting(key, default=""):
    s = Setting.query.get(key)
    return s.value if s else default


def next_public_id():
    """KN-1001, KN-1002, ..."""
    last = User.query.order_by(User.id.desc()).first()
    n = (last.id if last else 0) + 1001
    return f"KN-{n}"


def award_tokens(user_id, tokens, reason):
    """Append a free-token ledger entry. Returns tokens actually awarded."""
    if not user_id or tokens <= 0:
        return 0
    entry = TokenLedger(user_id=user_id, tokens=tokens, reason=reason)
    db.session.add(entry)
    return tokens


def token_balance(user_id):
    """Total free tokens held by a user."""
    if not user_id:
        return 0
    total = (db.session.query(db.func.coalesce(db.func.sum(TokenLedger.tokens), 0))
             .filter(TokenLedger.user_id == user_id).scalar())
    return int(total or 0)


def referral_tokens_this_month(user_id):
    """Referral tokens earned in the current calendar month (for the cap)."""
    if not user_id:
        return 0
    now = datetime.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = (db.session.query(db.func.coalesce(db.func.sum(TokenLedger.tokens), 0))
             .filter(TokenLedger.user_id == user_id,
                     TokenLedger.reason == "referral",
                     TokenLedger.created_at >= month_start).scalar())
    return int(total or 0)


def award_referral_tokens(referrer_id):
    """+5 tokens per verified referral, capped at 20/month. Returns awarded."""
    if not referrer_id:
        return 0
    used = referral_tokens_this_month(referrer_id)
    room = TOKEN_REFERRAL_MONTHLY_CAP - used
    if room <= 0:
        return 0
    return award_tokens(referrer_id, min(TOKEN_REFERRAL, room), "referral")


def ensure_referral_code(user):
    """Backfill-safe: referral_code mirrors the unique public_id."""
    if user and not user.referral_code:
        user.referral_code = user.public_id
