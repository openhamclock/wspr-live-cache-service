# wspr-live-cache Dockerfile
#
# Copyright (C) 2026 Open HamClock Backend (OHB) Contributors
# License: GNU Affero General Public License v3.0 (AGPLv3)
# See LICENSE or <https://www.gnu.org/licenses/agpl-3.0.html>
#
FROM debian:13.4-slim

ARG GIT_VERSION
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY docker/package-list.txt /app/
RUN apt update && \
    apt install -y --no-install-recommends $(grep -v '^#' /app/package-list.txt) && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*


COPY wspr_live_cache /app/wspr_live_cache
RUN mkdir -p /data && \
    echo $GIT_VERSION > /app/git.version

VOLUME ["/data"]
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -s http://localhost:8081/healthz || exit 1

CMD ["python3", "-m", "wspr_live_cache"]
