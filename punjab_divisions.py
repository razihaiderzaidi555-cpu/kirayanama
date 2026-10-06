"""Punjab administrative hierarchy: Division -> District -> Tehsil.

Tehsil lists sourced from Wikipedia "List of tehsils of Punjab, Pakistan"
(2023 census table). Slugs are lowercase hyphenated English names.

Structure: DIVISIONS[division_slug] = {
    "ur": ..., "en": ...,
    "districts": { district_slug: {"ur":..., "en":..., "tehsils": [(slug, ur, en), ...]} }
}
"""
from __future__ import annotations

DIVISIONS = {
    "lahore": {"ur": "لاہور", "en": "Lahore", "districts": {
        "lahore": {"ur": "لاہور", "en": "Lahore", "tehsils": [
            ("lahore-city", "لاہور شہر", "Lahore City"),
            ("lahore-cantt", "لاہور کینٹ", "Lahore Cantonment"),
            ("model-town", "ماڈل ٹاؤن", "Model Town"),
            ("raiwind", "رائیونڈ", "Raiwind"),
            ("shalimar", "شالیمار", "Shalimar"),
        ]},
        "kasur": {"ur": "قصور", "en": "Kasur", "tehsils": [
            ("kasur", "قصور", "Kasur"),
            ("chunian", "چونیاں", "Chunian"),
            ("pattoki", "پتوکی", "Pattoki"),
            ("kot-radha-kishan", "کوٹ رادھا کشن", "Kot Radha Kishan"),
        ]},
        "nankana-sahib": {"ur": "ننکانہ صاحب", "en": "Nankana Sahib", "tehsils": [
            ("nankana-sahib", "ننکانہ صاحب", "Nankana Sahib"),
            ("sangla-hill", "سانگلہ ہل", "Sangla Hill"),
            ("shah-kot", "شاہ کوٹ", "Shah Kot"),
        ]},
        "sheikhupura": {"ur": "شیخوپورہ", "en": "Sheikhupura", "tehsils": [
            ("sheikhupura", "شیخوپورہ", "Sheikhupura"),
            ("muridke", "مریدکے", "Muridke"),
            ("ferozewala", "فیروزوالہ", "Ferozewala"),
            ("safdarabad", "صفدرآباد", "Safdarabad"),
            ("sharaqpur", "شرق پور", "Sharaqpur"),
        ]},
    }},
    "gujranwala": {"ur": "گوجرانوالہ", "en": "Gujranwala", "districts": {
        "gujranwala": {"ur": "گوجرانوالہ", "en": "Gujranwala", "tehsils": [
            ("gujranwala-city", "گوجرانوالہ شہر", "Gujranwala City"),
            ("gujranwala-saddar", "گوجرانوالہ صدر", "Gujranwala Saddar"),
            ("kamoke", "کامونکی", "Kamoke"),
            ("nowshera-virkan", "نوشہرہ ورکاں", "Nowshera Virkan"),
        ]},
        "narowal": {"ur": "نارووال", "en": "Narowal", "tehsils": [
            ("narowal", "نارووال", "Narowal"),
            ("shakargarh", "شکر گڑھ", "Shakargarh"),
            ("zafarwal", "ظفر وال", "Zafarwal"),
        ]},
        "sialkot": {"ur": "سیالکوٹ", "en": "Sialkot", "tehsils": [
            ("sialkot", "سیالکوٹ", "Sialkot"),
            ("daska", "ڈسکہ", "Daska"),
            ("pasrur", "پسرور", "Pasrur"),
            ("sambrial", "سمبڑیال", "Sambrial"),
        ]},
    }},
    "gujrat": {"ur": "گجرات", "en": "Gujrat", "districts": {
        "gujrat": {"ur": "گجرات", "en": "Gujrat", "tehsils": [
            ("gujrat", "گجرات", "Gujrat"),
            ("kharian", "کھاریاں", "Kharian"),
            ("sarai-alamgir", "سرائے عالمگیر", "Sarai Alamgir"),
            ("jalalpur-jattan", "جلالپور جٹاں", "Jalalpur Jattan"),
            ("kunjah", "کنجاہ", "Kunjah"),
        ]},
        "hafizabad": {"ur": "حافظ آباد", "en": "Hafizabad", "tehsils": [
            ("hafizabad", "حافظ آباد", "Hafizabad"),
            ("pindi-bhattian", "پنڈی بھٹیاں", "Pindi Bhattian"),
        ]},
        "mandi-bahauddin": {"ur": "منڈی بہاؤالدین", "en": "Mandi Bahauddin", "tehsils": [
            ("mandi-bahauddin", "منڈی بہاؤالدین", "Mandi Bahauddin"),
            ("phalia", "پھالیہ", "Phalia"),
            ("malakwal", "ملکوال", "Malakwal"),
        ]},
        "wazirabad": {"ur": "وزیر آباد", "en": "Wazirabad", "tehsils": [
            ("wazirabad", "وزیر آباد", "Wazirabad"),
            ("ali-pur-chatta", "علی پور چٹھہ", "Ali Pur Chatta"),
        ]},
    }},
    "rawalpindi": {"ur": "راولپنڈی", "en": "Rawalpindi", "districts": {
        "rawalpindi": {"ur": "راولپنڈی", "en": "Rawalpindi", "tehsils": [
            ("rawalpindi", "راولپنڈی", "Rawalpindi"),
            ("gujar-khan", "گوجر خان", "Gujar Khan"),
            ("kahuta", "کہوٹہ", "Kahuta"),
            ("kallar-syedan", "کلر سیداں", "Kallar Syedan"),
            ("taxila", "ٹیکسلا", "Taxila"),
            ("daultala", "دولتالہ", "Daultala"),
        ]},
        "attock": {"ur": "اٹک", "en": "Attock", "tehsils": [
            ("attock", "اٹک", "Attock"),
            ("fateh-jang", "فتح جنگ", "Fateh Jang"),
            ("hassan-abdal", "حسن ابدال", "Hassan Abdal"),
            ("hazro", "حضرو", "Hazro"),
            ("jand", "جنڈ", "Jand"),
            ("pindi-gheb", "پنڈی گھیب", "Pindi Gheb"),
        ]},
        "chakwal": {"ur": "چکوال", "en": "Chakwal", "tehsils": [
            ("chakwal", "چکوال", "Chakwal"),
            ("choa-saidan-shah", "چوآ سیدن شاہ", "Choa Saidan Shah"),
            ("kallar-kahar", "کلر کہار", "Kallar Kahar"),
        ]},
        "jhelum": {"ur": "جہلم", "en": "Jhelum", "tehsils": [
            ("jhelum", "جہلم", "Jhelum"),
            ("dina", "دینہ", "Dina"),
            ("pind-dadan-khan", "پنڈ دادن خان", "Pind Dadan Khan"),
            ("sohawa", "سوہاوہ", "Sohawa"),
        ]},
        "murree": {"ur": "مری", "en": "Murree", "tehsils": [
            ("murree", "مری", "Murree"),
            ("kotli-sattian", "کوٹلی ستیاں", "Kotli Sattian"),
        ]},
        "talagang": {"ur": "تلہ گنگ", "en": "Talagang", "tehsils": [
            ("talagang", "تلہ گنگ", "Talagang"),
            ("lawa", "لاوہ", "Lawa"),
            ("multan-khurd", "ملتان خورد", "Multan Khurd"),
        ]},
    }},
    "sargodha": {"ur": "سرگودھا", "en": "Sargodha", "districts": {
        "sargodha": {"ur": "سرگودھا", "en": "Sargodha", "tehsils": [
            ("sargodha", "سرگودھا", "Sargodha"),
            ("bhalwal", "بھلوال", "Bhalwal"),
            ("bhera", "بھیرہ", "Bhera"),
            ("kot-momin", "کوٹ مومن", "Kot Momin"),
            ("sahiwal", "ساہیوال", "Sahiwal"),
            ("shahpur", "شاہ پور", "Shahpur"),
            ("sillanwali", "سلانوالی", "Sillanwali"),
        ]},
        "bhakkar": {"ur": "بھکر", "en": "Bhakkar", "tehsils": [
            ("bhakkar", "بھکر", "Bhakkar"),
            ("darya-khan", "دریا خان", "Darya Khan"),
            ("kaloorkot", "کلورکوٹ", "Kaloorkot"),
            ("mankera", "منکیرہ", "Mankera"),
        ]},
        "khushab": {"ur": "خوشاب", "en": "Khushab", "tehsils": [
            ("khushab", "خوشاب", "Khushab"),
            ("noorpur-thal", "نور پور تھل", "Noorpur Thal"),
            ("quaidabad", "قائد آباد", "Quaidabad"),
            ("naushera", "نوشہرہ (وادی سون)", "Naushera (Wadi-e-Soon)"),
        ]},
        "mianwali": {"ur": "میانوالی", "en": "Mianwali", "tehsils": [
            ("mianwali", "میانوالی", "Mianwali"),
            ("isakhel", "عیسیٰ خیل", "Isakhel"),
            ("piplan", "پپلاں", "Piplan"),
        ]},
    }},
    "faisalabad": {"ur": "فیصل آباد", "en": "Faisalabad", "districts": {
        "faisalabad": {"ur": "فیصل آباد", "en": "Faisalabad", "tehsils": [
            ("faisalabad-city", "فیصل آباد شہر", "Faisalabad City"),
            ("faisalabad-saddar", "فیصل آباد صدر", "Faisalabad Saddar"),
            ("chak-jhumra", "چک جھمرہ", "Chak Jhumra"),
            ("jaranwala", "جڑانوالہ", "Jaranwala"),
            ("samundri", "سمندری", "Samundri"),
            ("tandlianwala", "تاندلیانوالہ", "Tandlianwala"),
        ]},
        "chiniot": {"ur": "چنیوٹ", "en": "Chiniot", "tehsils": [
            ("chiniot", "چنیوٹ", "Chiniot"),
            ("lalian", "لالیاں", "Lalian"),
            ("bhuwana", "بھوانہ", "Bhuwana"),
        ]},
        "jhang": {"ur": "جھنگ", "en": "Jhang", "tehsils": [
            ("jhang", "جھنگ", "Jhang"),
            ("shorkot", "شورکوٹ", "Shorkot"),
            ("ahmadpur-sial", "احمد پور سیال", "Ahmadpur Sial"),
            ("athara-hazari", "اٹھارہ ہزاری", "Athara Hazari"),
            ("mandi-shah-jeewna", "منڈی شاہ جیونا", "Mandi Shah Jeewna"),
        ]},
        "toba-tek-singh": {"ur": "ٹوبہ ٹیک سنگھ", "en": "Toba Tek Singh", "tehsils": [
            ("toba-tek-singh", "ٹوبہ ٹیک سنگھ", "Toba Tek Singh"),
            ("gojra", "گوجرہ", "Gojra"),
            ("kamalia", "کمالیہ", "Kamalia"),
            ("pirmahal", "پیر محل", "Pirmahal"),
        ]},
    }},
    "multan": {"ur": "ملتان", "en": "Multan", "districts": {
        "multan": {"ur": "ملتان", "en": "Multan", "tehsils": [
            ("multan-city", "ملتان شہر", "Multan City"),
            ("multan-saddar", "ملتان صدر", "Multan Saddar"),
            ("shujabad", "شجاع آباد", "Shujabad"),
            ("jalalpur-pirwala", "جلالپور پیروالہ", "Jalalpur Pirwala"),
        ]},
        "khanewal": {"ur": "خانیوال", "en": "Khanewal", "tehsils": [
            ("khanewal", "خانیوال", "Khanewal"),
            ("mian-channu", "میاں چنوں", "Mian Channu"),
            ("kabirwala", "کبیروالا", "Kabirwala"),
            ("jahanian", "جہانیاں", "Jahanian"),
        ]},
        "lodhran": {"ur": "لودھراں", "en": "Lodhran", "tehsils": [
            ("lodhran", "لودھراں", "Lodhran"),
            ("kahror-pacca", "کہروڑ پکا", "Kahror Pacca"),
            ("dunyapur", "دنیا پور", "Dunyapur"),
        ]},
        "vehari": {"ur": "وہاڑی", "en": "Vehari", "tehsils": [
            ("vehari", "وہاڑی", "Vehari"),
            ("burewala", "بورے والا", "Burewala"),
            ("mailsi", "میلسی", "Mailsi"),
            ("jallah-jeem", "جلہ جیم", "Jallah Jeem"),
        ]},
    }},
    "sahiwal": {"ur": "ساہیوال", "en": "Sahiwal", "districts": {
        "sahiwal": {"ur": "ساہیوال", "en": "Sahiwal", "tehsils": [
            ("sahiwal", "ساہیوال", "Sahiwal"),
            ("chichawatni", "چیچہ وطنی", "Chichawatni"),
        ]},
        "okara": {"ur": "اوکاڑہ", "en": "Okara", "tehsils": [
            ("okara", "اوکاڑہ", "Okara"),
            ("depalpur", "دیپالپور", "Depalpur"),
            ("renala-khurd", "رینالہ خورد", "Renala Khurd"),
        ]},
        "pakpattan": {"ur": "پاکپتن", "en": "Pakpattan", "tehsils": [
            ("pakpattan", "پاکپتن", "Pakpattan"),
            ("arifwala", "عارف والا", "Arifwala"),
        ]},
    }},
    "dera-ghazi-khan": {"ur": "ڈیرہ غازی خان", "en": "Dera Ghazi Khan", "districts": {
        "dera-ghazi-khan": {"ur": "ڈیرہ غازی خان", "en": "Dera Ghazi Khan", "tehsils": [
            ("dera-ghazi-khan", "ڈیرہ غازی خان", "Dera Ghazi Khan"),
            ("kot-chutta", "کوٹ چھٹہ", "Kot Chutta"),
        ]},
        "layyah": {"ur": "لیہ", "en": "Layyah", "tehsils": [
            ("layyah", "لیہ", "Layyah"),
            ("karor-lal-esan", "کروڑ لعل عیسن", "Karor Lal Esan"),
            ("chaubara", "چوبارہ", "Chaubara"),
        ]},
        "muzaffargarh": {"ur": "مظفرگڑھ", "en": "Muzaffargarh", "tehsils": [
            ("muzaffargarh", "مظفرگڑھ", "Muzaffargarh"),
            ("jatoi", "جتوئی", "Jatoi"),
            ("alipur", "علی پور", "Alipur"),
        ]},
        "rajanpur": {"ur": "راجن پور", "en": "Rajanpur", "tehsils": [
            ("rajanpur", "راجن پور", "Rajanpur"),
            ("rojhan", "روجھان", "Rojhan"),
            ("de-excluded-area-rajanpur", "ڈی ایکسکلوڈڈ ایریا راجن پور",
             "De-Excluded Area Rajanpur"),
        ]},
        "taunsa": {"ur": "تونسہ", "en": "Taunsa", "tehsils": [
            ("taunsa", "تونسہ", "Taunsa"),
            ("koh-e-suleman", "کوہ سلیمان", "Koh-e-Suleman"),
            ("wahova", "وہوا", "Wahova"),
        ]},
        "kot-addu": {"ur": "کوٹ ادو", "en": "Kot Addu", "tehsils": [
            ("kot-addu", "کوٹ ادو", "Kot Addu"),
            ("chowk-sarwar-shaheed", "چوک سرور شہید", "Chowk Sarwar Shaheed"),
        ]},
    }},
    "bahawalpur": {"ur": "بہاولپور", "en": "Bahawalpur", "districts": {
        "bahawalpur": {"ur": "بہاولپور", "en": "Bahawalpur", "tehsils": [
            ("bahawalpur-city", "بہاولپور شہر", "Bahawalpur City"),
            ("bahawalpur-saddar", "بہاولپور صدر", "Bahawalpur Saddar"),
            ("ahmadpur-east", "احمد پور شرقیہ", "Ahmadpur East"),
            ("hasilpur", "حاصل پور", "Hasilpur"),
            ("khairpur-tamewali", "خیر پور ٹامیوالی", "Khairpur Tamewali"),
            ("yazman", "یزمان", "Yazman"),
        ]},
        "bahawalnagar": {"ur": "بہاولنگر", "en": "Bahawalnagar", "tehsils": [
            ("bahawalnagar", "بہاولنگر", "Bahawalnagar"),
            ("chishtian", "چشتیاں", "Chishtian"),
            ("haroonabad", "ہارون آباد", "Haroonabad"),
            ("minchinabad", "منچن آباد", "Minchinabad"),
            ("fort-abbas", "فورٹ عباس", "Fort Abbas"),
        ]},
        "rahim-yar-khan": {"ur": "رحیم یار خان", "en": "Rahim Yar Khan", "tehsils": [
            ("rahim-yar-khan", "رحیم یار خان", "Rahim Yar Khan"),
            ("sadiqabad", "صادق آباد", "Sadiqabad"),
            ("liaqatpur", "لیاقت پور", "Liaqatpur"),
            ("khanpur", "خان پور", "Khanpur"),
        ]},
    }},
}

# Legacy flat city slugs (pre-division model) -> (division, district, tehsil).
LEGACY_CITY_MAP = {
    "chiniot": ("faisalabad", "chiniot", "chiniot"),
    "lalian": ("faisalabad", "chiniot", "lalian"),
    "bhuwana": ("faisalabad", "chiniot", "bhuwana"),
}


def division_slugs():
    return list(DIVISIONS.keys())


def division_name(slug, lang="ur"):
    d = DIVISIONS.get(slug)
    return d.get(lang, slug) if d else slug


def district_slugs(division=None):
    """All district slugs, or those of one division."""
    if division:
        d = DIVISIONS.get(division)
        return list(d["districts"].keys()) if d else []
    out = []
    for d in DIVISIONS.values():
        out.extend(d["districts"].keys())
    return out


def district_name(district, lang="ur"):
    for d in DIVISIONS.values():
        dist = d["districts"].get(district)
        if dist:
            return dist.get(lang, district)
    return district


def division_of_district(district):
    for div_slug, d in DIVISIONS.items():
        if district in d["districts"]:
            return div_slug
    return None


def tehsil_slugs(division, district):
    d = DIVISIONS.get(division)
    if not d:
        return []
    dist = d["districts"].get(district)
    return [t[0] for t in dist["tehsils"]] if dist else []


def tehsil_name(tehsil, lang="ur", district=None, division=None):
    """Find a tehsil by slug (optionally scoped) and return its name."""
    idx = 2 if lang == "en" else 1
    search = []
    if division and district:
        d = DIVISIONS.get(division)
        dist = (d["districts"].get(district) if d else None)
        search = [(division, district, dist)] if dist else []
    else:
        for div_slug, d in DIVISIONS.items():
            for dist_slug, dist in d["districts"].items():
                search.append((div_slug, dist_slug, dist))
    for _, _, dist in search:
        for t in dist["tehsils"]:
            if t[0] == tehsil:
                return t[idx]
    return tehsil


def locate_tehsil(tehsil):
    """Return (division, district) for a tehsil slug, or (None, None)."""
    for div_slug, d in DIVISIONS.items():
        for dist_slug, dist in d["districts"].items():
            if any(t[0] == tehsil for t in dist["tehsils"]):
                return div_slug, dist_slug
    return None, None


def is_valid_location(division, district, tehsil):
    """True when the triple is a real division -> district -> tehsil chain."""
    d = DIVISIONS.get(division)
    if not d:
        return False
    dist = d["districts"].get(district)
    if not dist:
        return False
    return any(t[0] == tehsil for t in dist["tehsils"])


def resolve_location(division=None, district=None, tehsil=None, city=None):
    """Resolve any mix of new/legacy location inputs to a canonical triple.

    Returns (division, district, tehsil). Never returns all-None: falls back
    to Faisalabad/Chiniot/Chiniot (the original launch city).
    """
    if is_valid_location(division, district, tehsil):
        return division, district, tehsil
    if city:
        if city in LEGACY_CITY_MAP:
            return LEGACY_CITY_MAP[city]
        div = division_of_district(city)
        if div:
            return div, city, ""
        tdiv, tdist = locate_tehsil(city)
        if tdiv:
            return tdiv, tdist, city
    if division and district and tehsil_slugs(division, district):
        return division, district, tehsil_slugs(division, district)[0]
    return "faisalabad", "chiniot", "chiniot"


def place_name(slug, lang="ur"):
    """Display name for any legacy city / tehsil / district / division slug."""
    if not slug:
        return ""
    # Imported lazily: translations.py must not import this module at top level.
    from translations import get_text
    for prefix in ("city_", "teh_", "dist_", "div_"):
        key = prefix + slug
        val = get_text(key, lang)
        if val != key:
            return val
    return slug.replace("-", " ").title()


def divisions_for_json():
    """Compact structure for the cascading-select JS (slugs only; names via t())."""
    return {
        div: {dist: [t[0] for t in d["tehsils"]]}
        for div, data in DIVISIONS.items()
        for d in [data] for dist in [data["districts"]]
    }
