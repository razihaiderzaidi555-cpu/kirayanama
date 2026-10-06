"""W1 — public routes: home, city pages, browse/filter, listing detail, sitemap.

Only approved listings are ever visible here. No landlord phone numbers
are exposed on any public page (the contact flow lives in routes_contact).
"""
from flask import Blueprint, render_template, request, Response, abort, url_for, \
    redirect, flash, g
from flask_login import login_required
from urllib.parse import quote

from models import db, Listing, CITIES, PROPERTY_TYPES, Draw
from translations import get_text
from punjab_divisions import (
    DIVISIONS, division_slugs, district_slugs, tehsil_slugs,
    is_valid_location, division_of_district, locate_tehsil, LEGACY_CITY_MAP,
)

bp = Blueprint("public", __name__)


def _approved():
    # publicly visible = listing approved AND photos approved AND not closed
    return Listing.query.filter_by(status="approved", photo_status="approved",
                                   is_closed=False)


@bp.route("/")
def home():
    latest = _approved().order_by(Listing.created_at.desc()).limit(6).all()
    latest_draw = (Draw.query.filter_by(status="drawn")
                  .order_by(Draw.drawn_at.desc()).first())
    div_counts = {s: _approved().filter_by(division=s).count()
                  for s in division_slugs()}
    return render_template("public/home.html", listings=latest,
                           latest_winner=latest_draw.winner if latest_draw else None,
                           latest_prize=latest_draw.prize if latest_draw else "",
                           div_counts=div_counts)


@bp.route("/city/<city>")
def city_page(city):
    """District page. Legacy slugs keep working:
    'chiniot' -> chiniot district; 'lalian'/'bhuwana' -> their tehsil view."""
    listings = _approved()
    page_title = city
    if city in LEGACY_CITY_MAP:
        div, dist, teh = LEGACY_CITY_MAP[city]
        if teh != dist:  # legacy tehsil slug -> tehsil-filtered view
            listings = listings.filter_by(tehsil=teh)
            page_title = teh
        else:
            listings = listings.filter_by(city=dist)
            page_title = dist
    elif city in district_slugs():
        listings = listings.filter_by(city=city)
        page_title = city
    else:
        # maybe a bare tehsil slug
        tdiv, tdist = locate_tehsil(city)
        if tdiv:
            listings = listings.filter_by(tehsil=city)
            page_title = city
        else:
            abort(404)
    listings = listings.order_by(Listing.created_at.desc()).all()
    # tehsil chips for the district of this page
    chip_district = None
    if city in LEGACY_CITY_MAP:
        chip_district = LEGACY_CITY_MAP[city][1]
    elif city in district_slugs():
        chip_district = city
    else:
        _tdiv, _tdist = locate_tehsil(city)
        chip_district = _tdist
    tehsils = []
    if chip_district:
        _cdiv = division_of_district(chip_district)
        if _cdiv:
            tehsils = [(t,) for t in tehsil_slugs(_cdiv, chip_district)]
    return render_template("public/city.html", city_slug=page_title,
                           listings=listings, tehsils=tehsils)


@bp.route("/division/<division>")
def division_page(division):
    if division not in DIVISIONS:
        abort(404)
    listings = (
        _approved().filter_by(division=division)
        .order_by(Listing.created_at.desc()).all()
    )
    counts = {}
    dist_tehsils = {}
    for dist in DIVISIONS[division]["districts"]:
        counts[dist] = _approved().filter_by(city=dist).count()
        dist_tehsils[dist] = [(t,) for t in tehsil_slugs(division, dist)]
    return render_template("public/division.html", division=division,
                           listings=listings, counts=counts,
                           dist_tehsils=dist_tehsils)


@bp.route("/divisions")
def divisions_page():
    divs = []
    for slug in division_slugs():
        divs.append({
            "slug": slug,
            "count": _approved().filter_by(division=slug).count(),
        })
    return render_template("public/divisions.html", divisions=divs)


@bp.route("/listings")
def listings_page():
    q = (request.args.get("q") or "").strip()
    division = request.args.get("division") or ""
    district = request.args.get("district") or ""
    tehsil = request.args.get("tehsil") or ""
    city = request.args.get("city") or ""  # legacy district-slug param
    ptype = request.args.get("property_type") or ""
    min_rent = request.args.get("min_rent") or ""
    max_rent = request.args.get("max_rent") or ""
    bedrooms = request.args.get("bedrooms") or ""

    query = _approved()
    if division in DIVISIONS:
        query = query.filter_by(division=division)
        if district in district_slugs(division):
            query = query.filter_by(city=district)
            if tehsil in tehsil_slugs(division, district):
                query = query.filter_by(tehsil=tehsil)
    elif district in district_slugs():
        query = query.filter_by(city=district)
    elif city in district_slugs():
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
            "division": division,
            "district": district,
            "tehsil": tehsil,
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
    if listing.status != "approved" or listing.photo_status != "approved" or listing.is_closed:
        abort(404)
    # Anti-bypass monitoring: count views (only committed for approved listings).
    listing.view_count = (listing.view_count or 0) + 1
    db.session.commit()
    # WhatsApp share link: title + rent + location + page URL, pre-encoded.
    from punjab_divisions import place_name as _pn, tehsil_name as _tn
    title = listing.title_ur if listing.title_ur else listing.title_en
    loc_bits = [_pn(listing.city)]
    if listing.tehsil:
        loc_bits.append(_tn(listing.tehsil, district=listing.city,
                            division=listing.division))
    loc_str = "، ".join(b for b in loc_bits if b)
    share_text = "{} — {} {:,}/{}، {} | {}\n{}".format(
        title, "روپے", listing.monthly_rent or 0, "ماہانہ",
        loc_str, "کرایہ نامہ", request.url)
    share_url = "https://wa.me/?text=" + quote(share_text)
    # Landlord's average rating from completed deals.
    from models import Rating
    _ratings = Rating.query.filter_by(landlord_id=listing.landlord_id).all()
    avg_rating = round(sum(r.stars for r in _ratings) / len(_ratings), 1) if _ratings else None
    return render_template("public/detail.html", listing=listing,
                           share_url=share_url, avg_rating=avg_rating,
                           rating_count=len(_ratings))


@bp.route("/listing/<int:listing_id>/report-photo", methods=["POST"])
@login_required
def report_photo(listing_id):
    """A viewer flags a listing's photo as inappropriate.

    The listing is hidden (photo_status='pending') until an admin clears the
    flag on the /admin/photos page. Login required to prevent report spam.
    """
    listing = Listing.query.get_or_404(listing_id)
    listing.photo_flag = "user_reported"
    listing.photo_status = "pending"
    db.session.commit()
    flash(get_text("report_photo_done", getattr(g, "lang", "ur")))
    return redirect(url_for("public.listings_page"))


@bp.route("/sharait-o-zawabit")
def sharait():
    return render_template("public/sharait.html")


@bp.route("/sitemap.xml")
def sitemap():
    urls = [
        url_for("public.home", _external=True),
        url_for("public.listings_page", _external=True),
        url_for("public.divisions_page", _external=True),
    ]
    for d in division_slugs():
        urls.append(url_for("public.division_page", division=d, _external=True))
    for c in district_slugs():
        urls.append(url_for("public.city_page", city=c, _external=True))
    for listing in _approved().all():
        urls.append(
            url_for("public.listing_detail", listing_id=listing.id, _external=True)
        )
    xml = render_template("public/sitemap.xml", urls=urls)
    return Response(xml, mimetype="application/xml")
