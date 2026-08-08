# OmniSite — AI-Driven Telco Infrastructure Intelligence
#
# Single-stage on purpose: every geospatial dependency (shapely, geopandas via
# pyogrio, pyproj) ships manylinux wheels with GEOS/PROJ/GDAL bundled, so no
# compiler or system geo libraries are needed. curl is the only extra package,
# and only for the health check.

# 3.13 matches the locally tested runtime and carries the fewest open CVEs of the
# slim images at the time of writing.
FROM python:3.13-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first for layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY .streamlit/ .streamlit/

# Non-root runtime user; ./cache holds osmnx response caches.
RUN useradd -m -u 1000 omnisite \
    && mkdir -p /app/cache \
    && chown -R omnisite:omnisite /app
USER omnisite

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

EXPOSE 8501

ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
