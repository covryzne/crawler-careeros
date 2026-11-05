# syntax=docker/dockerfile:1
# backend_source is a named build context supplied by this repo's Compose files.
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PATH="/opt/backend/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    SE_CACHE_PATH=/home/careeros/.cache/selenium
RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver ca-certificates fonts-liberation \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 careeros \
    && useradd --uid 10001 --gid careeros --create-home careeros
# Chromium sandbox namespaces are unavailable in many Docker runtimes.
# Run as an unprivileged container user; do not add privileged/cap_sys_admin.
RUN mv /usr/bin/chromium /usr/bin/chromium-distribution
COPY docker/chromium /usr/bin/chromium
RUN chmod 755 /usr/bin/chromium
COPY --from=backend_source /requirements.txt /tmp/backend-requirements.txt
COPY requirements-selenium.txt /tmp/crawler-requirements.txt
RUN python -m venv /opt/backend \
    && /opt/backend/bin/pip install -r /tmp/backend-requirements.txt \
    && python -m venv /opt/crawler \
    && /opt/crawler/bin/pip install -r /tmp/crawler-requirements.txt
WORKDIR /app/backend
COPY --from=backend_source /app /app/backend/app
COPY src /app/crawler/src
RUN mkdir -p /app/crawler/output /home/careeros/.cache/selenium \
    && chown -R careeros:careeros /app /home/careeros
USER careeros
CMD ["/opt/backend/bin/python", "-m", "app.crawler.worker"]
