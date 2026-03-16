#!/usr/bin/env bash
# ============================================================
# CyberLoop - One-Command GCP Deployment (Full Stack)
# ============================================================
# Usage:
#   export GOOGLE_API_KEY="your-gemini-api-key"
#   bash deploy/deploy.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - Docker installed and running
#   - Billing enabled on GCP project
#   - Frontend already built (frontend/dist/ exists)
# ============================================================
set -euo pipefail

# ----- Configuration -----
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-cyberloop-hackathon}"
REGION="us-central1"
SERVICE_NAME="cyberloop"
REPO_NAME="cyberloop"
IMAGE_TAG="latest"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/app:${IMAGE_TAG}"

# ----- Colors -----
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

log()   { echo -e "${GREEN}[OK]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!!]${NC} $1"; }
error() { echo -e "${RED}[ERR]${NC} $1" >&2; exit 1; }
info()  { echo -e "${CYAN}[>>]${NC} $1"; }

# ----- Pre-flight checks -----
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
command -v docker >/dev/null 2>&1 || error "Docker not found. Install Docker Desktop."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

# Check frontend build exists
if [ ! -f "${PROJECT_ROOT}/frontend/dist/index.html" ]; then
  error "Frontend not built. Run: cd frontend && npm run build"
fi

echo ""
echo "============================================"
echo "  CyberLoop - GCP Deploy (Full Stack)"
echo "============================================"
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Service:  ${SERVICE_NAME}"
echo "  Image:    ${IMAGE_URI}"
echo "============================================"
echo ""

# ----- Step 1: Set project -----
info "Setting GCP project..."
gcloud config set project "${PROJECT_ID}" --quiet
log "Project set to ${PROJECT_ID}"

# ----- Step 2: Enable required APIs -----
info "Enabling required APIs..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --quiet
log "APIs enabled."

# ----- Step 3: Create Artifact Registry repo (idempotent) -----
info "Checking Artifact Registry..."
if gcloud artifacts repositories describe "${REPO_NAME}" \
    --location="${REGION}" >/dev/null 2>&1; then
  warn "Artifact Registry repo '${REPO_NAME}' already exists, skipping."
else
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="CyberLoop Docker images" \
    --quiet
  log "Artifact Registry repo created."
fi

# ----- Step 4: Configure Docker auth -----
info "Configuring Docker auth for Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
log "Docker auth configured."

# ----- Step 5: Build Docker image (full stack) -----
info "Building Docker image (backend + frontend)..."
docker build \
  -t "${IMAGE_URI}" \
  -f "${SCRIPT_DIR}/Dockerfile" \
  "${PROJECT_ROOT}" \
  || error "Docker build failed."
log "Docker image built."

# ----- Step 6: Push image -----
info "Pushing image to Artifact Registry..."
docker push "${IMAGE_URI}" || error "Docker push failed."
log "Image pushed: ${IMAGE_URI}"

# ----- Step 7: Deploy to Cloud Run -----
info "Deploying to Cloud Run..."

# Build env vars string
ENV_VARS=""
if [ -n "${GOOGLE_API_KEY:-}" ]; then
  ENV_VARS="GOOGLE_API_KEY=${GOOGLE_API_KEY},GEMINI_API_KEY=${GOOGLE_API_KEY}"
  log "API keys set from environment."
else
  warn "GOOGLE_API_KEY not set! The service will need it configured manually:"
  warn "  gcloud run services update ${SERVICE_NAME} \\"
  warn "    --set-env-vars GOOGLE_API_KEY=<key>,GEMINI_API_KEY=<key> \\"
  warn "    --region ${REGION}"
fi

DEPLOY_ARGS=(
  run deploy "${SERVICE_NAME}"
  --image "${IMAGE_URI}"
  --region "${REGION}"
  --platform managed
  --allow-unauthenticated
  --port 8080
  --cpu 1
  --memory 1Gi
  --min-instances 0
  --max-instances 3
  --timeout 3600
  --session-affinity
)

if [ -n "${ENV_VARS}" ]; then
  DEPLOY_ARGS+=(--set-env-vars "${ENV_VARS}")
fi

gcloud "${DEPLOY_ARGS[@]}" --quiet || error "Cloud Run deployment failed."
log "Cloud Run service deployed."

# ----- Step 8: Print service URL -----
SERVICE_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(status.url)' 2>/dev/null)

echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
log "Service URL: ${SERVICE_URL}"
echo ""
echo "  Test backend:   curl ${SERVICE_URL}/health"
echo "  Open frontend:  ${SERVICE_URL}"
echo ""
echo "  The frontend and backend are served from"
echo "  the same container on Cloud Run."
echo ""
