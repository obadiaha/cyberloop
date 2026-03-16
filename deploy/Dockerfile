# ============================================================
# CyberLoop - Multi-Stage Docker Build (Full Stack)
# ============================================================
# Stage 1: Install Python dependencies in a builder layer
# Stage 2: Copy backend + frontend dist into the final slim image
# ============================================================

# --- Stage 1: Builder ---
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies into a virtual env for clean copy
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.13-slim

# Prevent .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy backend application code
COPY backend/ .

# Copy frontend dist (pre-built React app)
COPY frontend/dist/ ./static/

# Cloud Run injects PORT env var (default 8080)
ENV PORT=8080
EXPOSE 8080

# Run with uvicorn - single worker for WebSocket session affinity
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
