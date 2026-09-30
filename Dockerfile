FROM python:3.12-slim

WORKDIR /srv/app

COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app/ ./app/
RUN mkdir -p /srv/app/app/data /srv/app/app/static/uploads

WORKDIR /srv/app/app

# Koyeb injects $PORT automatically
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 120 'app:create_app()'"]
