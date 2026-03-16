#!/bin/bash
set -e

# ============================================================
# CyberLoop — Frontend Deployment
# ============================================================
# Deploys the React/Vite frontend to Cloud Run as a static
# Nginx container. This avoids Cloud CDN complexity for the
# hackathon while keeping everything behind Cloud Run.
#
# Usage: bash infra/deploy-frontend.sh [BACKEND_URL]
#
# If BACKEND_URL is not passed, it's auto-detected from the
# existing backend Cloud Run service.
# ============================================================

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-cyberloop-hackathon}"
REGION="us-central1"
REPO_NAME="cyberloop"
SERVICE_NAME="cyberloop-web"
IMAGE_TAG="latest"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO_NAME}/web:${IMAGE_TAG}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()   { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1" >&2; exit 1; }

# ---- Pre-flight ----
command -v gcloud >/dev/null 2>&1 || error "gcloud CLI not found."
command -v docker >/dev/null 2>&1 || error "Docker not found."
command -v npm >/dev/null 2>&1    || error "npm not found. Install Node 18+."

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
FRONTEND_DIR="${PROJECT_ROOT}/frontend"

[ -d "${FRONTEND_DIR}" ] || error "Frontend directory not found at ${FRONTEND_DIR}"

# ---- Detect backend URL ----
BACKEND_URL="${1:-}"
if [ -z "${BACKEND_URL}" ]; then
  log "Auto-detecting backend URL from Cloud Run..."
  BACKEND_URL=$(gcloud run services describe cyberloop-api \
    --region="${REGION}" \
    --format='value(status.url)' 2>/dev/null) \
    || error "Could not detect backend URL. Pass it as first argument: bash infra/deploy-frontend.sh https://your-api-url"
fi

echo ""
echo "============================================"
echo "  CyberLoop — Frontend Deployment"
echo "============================================"
echo "  Backend URL: ${BACKEND_URL}"
echo "  Service:     ${SERVICE_NAME}"
echo "============================================"
echo ""

# ---- Step 1: Build Vite app ----
log "Installing frontend dependencies..."
cd "${FRONTEND_DIR}"
npm ci --silent || npm install --silent || error "npm install failed."

log "Building Vite app with API URL..."
VITE_API_URL="${BACKEND_URL}" npm run build || error "Vite build failed."

[ -d "${FRONTEND_DIR}/dist" ] || error "Build output not found at frontend/dist/"
log "Frontend built successfully."

# ---- Step 2: Create production Dockerfile for static serving ----
log "Creating Nginx Dockerfile for static serving..."
cat > "${FRONTEND_DIR}/Dockerfile.prod" << 'DOCKERFILE'
FROM nginx:1.25-alpine

# Remove default Nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Add custom config for SPA routing
COPY nginx.conf /etc/nginx/conf.d/

# Copy built assets
COPY dist/ /usr/share/nginx/html/

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
DOCKERFILE

# Nginx config for SPA (all routes -> index.html)
cat > "${FRONTEND_DIR}/nginx.conf" << 'NGINX'
server {
    listen 8080;
    server_name _;
    root /usr/share/nginx/html;
    index index.html;

    # SPA fallback: all non-file routes serve index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Cache static assets aggressively
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Gzip
    gzip on;
    gzip_types text/plain text/css application/json application/javascript text/xml application/xml text/javascript image/svg+xml;
}
NGINX

# ---- Step 3: Build and push Docker image ----
log "Building frontend Docker image..."
docker build \
  -t "${IMAGE_URI}" \
  -f "${FRONTEND_DIR}/Dockerfile.prod" \
  "${FRONTEND_DIR}" \
  || error "Docker build failed."

log "Pushing image to Artifact Registry..."
gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet
docker push "${IMAGE_URI}" || error "Docker push failed."

# ---- Step 4: Deploy to Cloud Run ----
log "Deploying frontend to Cloud Run..."
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_URI}" \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --port 8080 \
  --cpu 1 \
  --memory 256Mi \
  --min-instances 0 \
  --max-instances 5 \
  || error "Cloud Run deployment failed."

# ---- Step 5: Get deployed URL ----
FRONTEND_URL=$(gcloud run services describe "${SERVICE_NAME}" \
  --region="${REGION}" \
  --format='value(status.url)' 2>/dev/null)

# ---- Cleanup temp files ----
rm -f "${FRONTEND_DIR}/Dockerfile.prod" "${FRONTEND_DIR}/nginx.conf"

echo ""
echo "============================================"
echo "  Frontend Deployment Complete!"
echo "============================================"
echo ""
log "Frontend URL: ${FRONTEND_URL}"
log "Backend URL:  ${BACKEND_URL}"
echo ""
echo "  The app is live at: ${FRONTEND_URL}"
echo ""
