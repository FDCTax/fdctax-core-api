# FDC Core Backend - Production Dockerfile
# Multi-stage build for minimal image size

# ==================== BUILD STAGE ====================
FROM python:3.11-slim as builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ==================== PRODUCTION STAGE ====================
FROM python:3.11-slim as production

# Build arguments for metadata
ARG BUILD_DATE
ARG GIT_SHA
ARG VERSION

# Labels
LABEL org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.title="FDC Core Backend" \
      org.opencontainers.image.description="FDC Tax Core API with Transaction Engine" \
      org.opencontainers.image.vendor="FDC Tax"

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -r fdccore && useradd -r -g fdccore fdccore

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY --chown=fdccore:fdccore . .

# Create data directory with proper permissions
RUN mkdir -p /app/data/uploads && \
    chown -R fdccore:fdccore /app/data

# Environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    PORT=8001

# Switch to non-root user
USER fdccore

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health/live || exit 1

# Expose port
EXPOSE ${PORT}

# Run database migrations and start server
CMD ["sh", "-c", "python -c 'import asyncio; from database import init_db; asyncio.run(init_db())' && uvicorn server:app --host 0.0.0.0 --port ${PORT}"]
