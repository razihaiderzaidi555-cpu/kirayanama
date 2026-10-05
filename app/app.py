"""KirayaNama Flask app factory. Registers blueprints defensively so the app
runs at every build stage even if some blueprint modules are not written yet."""
import importlib
import os
from flask import Flask, g, request, session, redirect, url_for, Response
from flask_login import LoginManager

from models import db, User, CITIES
from translations import get_text

login_manager = LoginManager()
login_manager.login_view = "auth.login"


def create_app():
    base = os.path.dirname(os.path.abspath(__file__))
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me-kirayanama")
    os.makedirs(os.path.join(base, "data"), exist_ok=True)
    # Render/hosted Postgres when DATABASE_URL is set; local SQLite otherwise.
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL") or "sqlite:///" + os.path.join(base, "data", "kirayanama.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["UPLOAD_FOLDER"] = os.path.join(base, "static", "uploads")
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(uid):
        return User.query.get(int(uid))

    @app.before_request
    def _set_lang():
        lang = request.args.get("lang") or session.get("lang") or "ur"
        if lang not in ("ur", "en"):
            lang = "ur"
        if request.args.get("lang"):
            session["lang"] = lang
        g.lang = lang

    @app.context_processor
    def _inject():
        lang = getattr(g, "lang", "ur")
        return {
            "t": lambda k: get_text(k, lang),
            "lang": lang,
            "CITIES": CITIES,
            "city_name": lambda slug: get_text(f"city_{slug}", lang),
        }

    # blueprints (each worker owns one module; missing ones are skipped)
    _try_register(app, "routes_public", "bp")
    _try_register(app, "routes_auth", "bp")
    _try_register(app, "routes_landlord", "bp")
    _try_register(app, "routes_contact", "bp")
    _try_register(app, "routes_admin", "bp")
    _try_register(app, "routes_lucky", "bp")

    @app.route("/lang/<code>")
    def set_lang(code):
        session["lang"] = code if code in ("ur", "en") else "ur"
        return redirect(request.referrer or url_for("public.home") if "public.home" in [r.endpoint for r in app.url_map.iter_rules()] else "/")

    @app.route("/robots.txt")
    def robots():
        return Response("User-agent: *\nAllow: /\nSitemap: /sitemap.xml\n", mimetype="text/plain")

    @app.route("/healthz")
    def healthz():
        return {"ok": True}

    with app.app_context():
        db.create_all()
        _migrate_schema()
        _ensure_production_defaults()

    return app


def _migrate_schema():
    """Add new columns to DBs created before they existed (create_all never
    alters existing tables). Safe to run every boot."""
    from sqlalchemy import inspect, text
    cols = {c["name"] for c in inspect(db.engine).get_columns("listings")}
    stmts = []
    if "location_lat" not in cols:
        stmts.append("ALTER TABLE listings ADD COLUMN location_lat FLOAT")
    if "location_lng" not in cols:
        stmts.append("ALTER TABLE listings ADD COLUMN location_lng FLOAT")
    if "is_closed" not in cols:
        stmts.append("ALTER TABLE listings ADD COLUMN is_closed BOOLEAN DEFAULT 0")
    # users.email
    ucols = {c["name"] for c in inspect(db.engine).get_columns("users")}
    if "email" not in ucols:
        stmts.append("ALTER TABLE users ADD COLUMN email VARCHAR(120)")
    if stmts:
        with db.engine.begin() as conn:
            for s in stmts:
                conn.execute(text(s))


def _ensure_production_defaults():
    """First-boot seed for production: payment numbers + admin login.

    Never wipes existing data — only fills in what's missing.
    """
    from models import Setting, User, db

    defaults = {
        "jazzcash_number": "03115021212",
        "easypaisa_number": "03115021212",
        "upaisa_number": "03115021212",
        "hbl_account": "01737900590403",
    }
    for key, value in defaults.items():
        if Setting.query.get(key) is None:
            db.session.add(Setting(key=key, value=value))
    if User.query.filter_by(role="admin").first() is None:
        admin = User(public_id="KN-1", name="Admin", phone="03115021212",
                     role="admin", city="chiniot")
        admin.set_password("admin123")
        db.session.add(admin)
    db.session.commit()


def _try_register(app, module_name, attr):
    try:
        mod = importlib.import_module(module_name)
        app.register_blueprint(getattr(mod, attr))
    except (ImportError, AttributeError) as e:
        app.logger.warning("Blueprint %s not loaded yet: %s", module_name, e)


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
