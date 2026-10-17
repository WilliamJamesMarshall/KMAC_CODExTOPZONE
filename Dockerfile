FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8080

WORKDIR /app
COPY requirements-cloud.lock ./
RUN python -m pip install --no-cache-dir --require-hashes -r requirements-cloud.lock \
    && python -m playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 oss \
    && useradd --uid 10001 --gid oss --create-home oss

COPY pyproject.toml ./
COPY src/oss/ ./src/oss/
COPY web/index.html web/app.js web/styles.css ./web/
USER 10001:10001
EXPOSE 8080
CMD ["python", "-m", "oss.cloud_server"]
