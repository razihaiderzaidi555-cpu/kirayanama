# KirayaNama — کرایہ نامہ

Pakistan rental-listings website: landlords list houses/shops, renters browse free,
contact unlocks after double-YES + 15% commission each side (JazzCash/EasyPaisa,
screenshot verified by admin). Launch cities: Chiniot, Lalian, Bhuwana.

## Stack
- Flask + Flask-SQLAlchemy + Flask-Login + Pillow + Gunicorn
- SQLite locally (`app/data/kirayanama.db`); Postgres when `DATABASE_URL` is set

## Run with Docker (Render/Railway/Fly)
Builds from `Dockerfile`. The host injects `$PORT`; set `SECRET_KEY` env var
in production. `DATABASE_URL` optional (Postgres), else SQLite.

## Local run
```
cd app
pip install -r requirements.txt
python app.py
```
