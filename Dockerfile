# Stage 1: Build dependencies & Python packages
FROM python:3.13-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1
ENV UV_SYSTEM_PYTHON=1

WORKDIR /tmp/build

# Install system deps for pyogrio, GDAL, and general compilation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Install uv
ADD https://astral.sh/uv/install.sh /uv-installer.sh
RUN sh /uv-installer.sh && rm /uv-installer.sh
ENV PATH="/root/.local/bin:$PATH"

# Copy dependency files and package
COPY ./pyproject.toml ./uv.lock ./
COPY ./pipeloom ./pipeloom

# Install your package into the system Python (creates console scripts in /usr/local/bin)
RUN uv pip install --system --no-cache-dir .

# Stage 2: Runtime image
FROM python:3.13-slim AS final

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Runtime deps only
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python environment and binaries
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy your app (not strictly needed if installed as package, but keeps source available)
COPY ./pipeloom ./pipeloom

# Create non-root user
RUN useradd --create-home --home-dir /home/app --shell /bin/bash app \
    && chown -R app:app /app

USER app

# Run the installed console script
ENTRYPOINT ["pipeloom"]
