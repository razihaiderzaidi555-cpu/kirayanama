"""W1 — public routes: home, city pages, browse/filter, listing detail, sitemap.

Only approved listings are ever visible here. No landlord phone numbers
are exposed on any public page (the contact flow lives in routes_contact).
"""
from flask import Blueprint, render_template, request, Response, abort, url_for
from urllib.parse import quote

from models import db, Listing, CITIES, PROPERTY_TYPES, Draw

bp = Blueprint("public", __name__)


def _approved():
    return Listing.query.filter_by(status="approved", is_closed=False)


@bp.route("/")
def home():
    latest = _approved().order_by(Listing.created_at.desc()).limit(6).all()
    latest_draw = (Draw.query.filter_by(status="drawn")
                  .order_by(Draw.drawn_at.desc()).first())
    return render_template("public/home.html", listings=latest,
                           latest_winner=latest_draw.winner if latest_draw else None,
                           latest_prize=latest_draw.prize if latest_draw else "")


@bp.route("/city/<city>")
def city_page(city):
    if city not in CITIES:
        abort(404)
    listings = (
        _approved().filter_by(city=city).order_by(Listing.created_at.desc()).all()
    )
    return render_template("public/city.html", city_slug=city, listings=listings)


@bp.route("/listings")
def listings_page():
    q = (request.args.get("q") or "").strip()
    city = request.args.get("city") or ""
    ptype = request.args.get("property_type") or ""
    min_rent = request.args.get("min_rent") or ""
    max_rent = request.args.get("max_rent") or ""
    bedrooms = request.args.get("bedrooms") or ""

    query = _approved()
    if city in CITIES:
        query = query.filter_by(city=city)
    if ptype in PROPERTY_TYPES:
        query = query.filter_by(property_type=ptype)
    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Listing.title_ur.ilike(like),
                Listing.title_en.ilike(like),
                Listing.desc_ur.ilike(like),
                Listing.desc_en.ilike(like),
                Listing.area.ilike(like),
            )
        )
    try:
        if min_rent != "":
            query = query.filter(Listing.monthly_rent >= int(min_rent))
    except ValueError:
        pass
    try:
        if max_rent != "":
            query = query.filter(Listing.monthly_rent <= int(max_rent))
    except ValueError:
        pass
    try:
        if bedrooms != "":
            query = query.filter(Listing.bedrooms >= int(bedrooms))
    except ValueError:
        pass

    listings = query.order_by(Listing.created_at.desc()).all()
    return render_template(
        "public/listings.html",
        listings=listings,
        filters={
            "q": q,
            "city": city,
            "property_type": ptype,
            "min_rent": min_rent,
            "max_rent": max_rent,
            "bedrooms": bedrooms,
        },
        property_types=PROPERTY_TYPES,
    )


@bp.route("/listing/<int:listing_id>")
def listing_detail(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    if listing.status != "approved" or listing.is_closed:
        abort(404)
    # Anti-bypass monitoring: count views (only committed for approved listings).
    listing.view_count = (listing.view_count or 0) + 1
    db.session.commit()
    # WhatsApp share link: title + rent + city + page URL, pre-encoded.
    title = listing.title_ur if listing.title_ur else listing.title_en
    share_text = "{} — {} {:,}/{}، {} | {}\n{}".format(
        title, "روپے", listing.monthly_rent or 0, "ماہانہ",
        listing.city, "کرایہ نامہ", request.url)
    share_url = "https://wa.me/?text=" + quote(share_text)
    # Landlord's average rating from completed deals.
    from models import Rating
    _ratings = Rating.query.filter_by(landlord_id=listing.landlord_id).all()
    avg_rating = round(sum(r.stars for r in _ratings) / len(_ratings), 1) if _ratings else None
    return render_template("public/detail.html", listing=listing,
                           share_url=share_url, avg_rating=avg_rating,
                           rating_count=len(_ratings))


@bp.route("/sharait-o-zawabit")
def sharait():
    return render_template("public/sharait.html")


@bp.route("/sitemap.xml")
def sitemap():
    urls = [
        url_for("public.home", _external=True),
        url_for("public.listings_page", _external=True),
    ]
    for c in CITIES:
        urls.append(url_for("public.city_page", city=c, _external=True))
    for listing in _approved().all():
        urls.append(
            url_for("public.listing_detail", listing_id=listing.id, _external=True)
        )
    xml = render_template("public/sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")
