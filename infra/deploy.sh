#!/bin/bash
set -e

# ============================================================
# CyberLoop — One-Command GCP Deployment
# ============================================================
# Usage: bash infra/deploy.sh
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (gcloud auth login)
#   - Docker installed and running
#   - Gemini API key stored in Secret Manager (or pass via env)
#   - Billing enabled on GCP project
# ============================================================

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-cyberloop-hackathon}"
REGION="us-central1"
REPO_NAME="cyberloop"
SERVICE_NAME="cyberloop-api"
IMAGE_TAG="latest"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/api:${IMAGE_TAG}"
BUCKET_NAME="${GCS_BUCKET_NAME:-${PROJECT_ID}-data}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1" >&2; exit 1; }

# ---- Pre-flight checks ----
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
command -v docker >/dev/null 2>&1 || error "Docker not found. Install: https://docs.docker.com/get-docker/"

echo ""
echo "============================================"
echo "  CyberLoop — GCP Deployment"
echo "============================================"
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"
echo "  Service:  ${SERVICE_NAME}"
echo "  Bucket:   ${BUCKET_NAME}"
echo "============================================"
echo ""

# ---- Step 1: Set project ----
log "Setting GCP project to ${PROJECT_ID}..."
gcloud config set project "${PROJECT_ID}" --quiet || error "Failed to set project. Does '${PROJECT_ID}' exist?"

# ---- Step 2: Enable required APIs ----
log "Enabling required GCP APIs..."
gcloud services enable \
  run.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  || error "Failed to enable APIs. Check billing is enabled."

log "All APIs enabled."

# ---- Step 3: Create Artifact Registry repo (idempotent) ----
log "Creating Artifact Registry repository..."
if gcloud artifacts repositories describe "${REPO_NAME}" --location="${REGION}" >/dev/null 2>&1; then
  warn "Artifact Registry repo '${REPO_NAME}' already exists, skipping."
else
  gcloud artifacts repositories create "${REPO_NAME}" \
    --repository-format=docker \
    --location="${REGION}" \
    --description="CyberLoop Docker images" \
    || error "Failed to create Artifact Registry repository."
  log "Artifact Registry repo created."
fi

# ---- Step 4: Configure Docker auth for Artifact Registry ----
log "Configuring Docker authentication..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# ---- Step 5: Build and push Docker image ----
log "Building Docker image..."
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"

docker build \
  -t "${IMAGE_URI}" \
  -f "${PROJECT_ROOT}/backend/Dockerfile" \
  "${PROJECT_ROOT}/backend" \
  || error "Docker build failed. Check backend/Dockerfile."

log "Pushing image to Artifact Registry..."
docker push "${IMAGE_URI}" || error "Docker push failed. Check auth and network."

log "Image pushed: ${IMAGE_URI}"

# ---- Step 6: Create Gemini API key secret (if not exists) ----
log "Checking Secret Manager for gemini-api-key..."
if gcloud secrets describe gemini-api-key >/dev/null 2>&1; then
  warn "Secret 'gemini-api-key' already exists."
else
  if [ -n "${GEMINI_API_KEY}" ]; then
    echo -n "${GEMINI_API_KEY}" | gcloud secrets create gemini-api-key --data-file=- \
      || error "Failed to create secret."
    log "Secret 'gemini-api-key' created from env var."
  else
    warn "GEMINI_API_KEY not set in environment."
    warn "Create it manually: echo -n 'your-key' | gcloud secrets create gemini-api-key --data-file=-"
  fi
fi

# ---- Step 7: Deploy to Cloud Run ----
log "Deploying to Cloud Run..."

# Get the Cloud Run service account for secret access
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
SA_EMAIL="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

# Grant secret access to Cloud Run service account
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" \
  --quiet 2>/dev/null || warn "Could not bind secret IAM (may already exist)."

gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_URI}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 2Gi \
  --min-instances 0 \
  --max-instances 10 \
  --timeout 300 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},GCS_BUCKET_NAME=${BUCKET_NAME}" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest" \
  --session-affinity \
  || error "Cloud Run deployment failed."

log "Cloud Run service deployed."

# ---- Step 8: Create Cloud Storage bucket and upload data ----
log "Setting up Cloud Storage bucket..."
if gsutil ls "gs://${BUCKET_NAME}" >/dev/null 2>&1; then
  warn "Bucket 'gs://${BUCKET_NAME}' already exists."
else
  gsutil mb -l "${REGION}" "gs://${BUCKET_NAME}" \
    || error "Failed to create Cloud Storage bucket."
  log "Bucket created: gs://${BUCKET_NAME}"
fi

log "Uploading question trees and data..."
if [ -d "${PROJECT_ROOT}/backend/data" ]; then
  gsutil -m cp -r "${PROJECT_ROOT}/backend/data/"* "gs://${BUCKET_NAME}/" \
    || warn "Some files failed to upload. Check backend/data/ contents."
  log "Data uploaded to gs://${BUCKET_NAME}/"
else
  warn "No backend/data/ directory found. Skipping data upload."
fi

# ---- Step 9: Initialize Firestore (idempotent) ----
log "Initializing Firestore database..."
if gcloud firestore databases describe --database="(default)" >/dev/null 2>&1; then
  warn "Firestore database already exists."
else
  gcloud firestore databases create \
    --region="${REGION}" \
    --type=firestore-native \
    || warn "Firestore creation failed (may already exist in another region)."
  log "Firestore database created in ${REGION}."
fi

# ---- Step 10: Get deployed URL ----
API_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(status.url)' 2>/dev/null)

echo ""
echo "============================================"
echo "  Deployment Complete!"
echo "============================================"
echo ""
log "API URL: ${API_URL}"
log "Bucket:  gs://${BUCKET_NAME}"
log "Project: ${PROJECT_ID}"
log "Region:  ${REGION}"
echo ""
echo "  Next steps:"
echo "    1. Test the API: curl ${API_URL}/health"
echo "    2. Deploy frontend: bash infra/deploy-frontend.sh"
echo "    3. Set min-instances=1 before demo day:"
echo "       gcloud run services update ${SERVICE_NAME} --min-instances=1 --region=${REGION}"
echo ""
