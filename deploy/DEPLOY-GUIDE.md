# CyberLoop: Cloud Run Deployment Guide

**Goal:** Deploy the full-stack CyberLoop app (FastAPI backend + React frontend) to Google Cloud Run.

---

## Prerequisites

- Google Cloud account with billing enabled
- gcloud CLI installed (`brew install --cask google-cloud-sdk`)
- Frontend already built (`cd frontend && npm run build`)

---

## Deploy

```bash
# 1. Authenticate
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Build frontend
cd frontend && npm run build && cd ..

# 3. Copy frontend to backend static dir
mkdir -p backend/static
cp -r frontend/dist/* backend/static/

# 4. Deploy (no Docker required)
cd backend
gcloud run deploy cyberloop \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 3600 \
  --session-affinity \
  --set-env-vars "GEMINI_API_KEY=YOUR_API_KEY"
```

Or use the automated script: `bash deploy/deploy.sh`

---

## Verify

```bash
# Health check
curl https://YOUR_SERVICE_URL/health

# Open in browser
open https://YOUR_SERVICE_URL
```

---

## Troubleshooting

### "Billing not enabled"
Go to https://console.cloud.google.com/billing and link a billing account.

### WebSocket connection fails
Cloud Run supports WebSockets natively. The deploy uses `--session-affinity` and `--timeout 3600` for long interview sessions.

### Check logs
```bash
gcloud run services logs read cyberloop --region us-central1 --limit 50
```

---

## Cleanup

```bash
gcloud run services delete cyberloop --region us-central1 --quiet
```
