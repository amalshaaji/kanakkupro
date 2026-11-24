FROM node:22-bookworm-slim AS assets
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY assets ./assets
COPY templates ./templates
COPY apps ./apps
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.runtime.lock ./
RUN pip install --no-cache-dir -r requirements.runtime.lock
COPY apps ./apps
COPY config ./config
COPY templates ./templates
COPY scripts ./scripts
COPY manage.py gunicorn.conf.py ./
COPY --from=assets /build/static ./static
RUN DJANGO_SETTINGS_MODULE=config.settings.build python manage.py collectstatic --noinput \
    && useradd --create-home --uid 10001 appuser
USER appuser
ENV DJANGO_SETTINGS_MODULE=config.settings.render
EXPOSE 10000
CMD ["python", "scripts/render_start.py"]
