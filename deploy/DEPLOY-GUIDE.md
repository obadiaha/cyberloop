# CyberLoop: Cloud Run Deployment Guide

**Goal:** Deploy the full-stack CyberLoop app (FastAPI backend + React frontend) to Google Cloud Run with Firestore for session persistence.

---

## Prerequisites

- Google Cloud account with billing enabled
- gcloud CLI installed (`brew install --cask google-cloud-sdk`)
- Node 18+ and Python 3.12+

---

## Deploy

```bash
# 1. Authenticate and set project
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Enable required APIs
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  --quiet

# 3. Create Firestore database (one-time)
gcloud firestore databases create --location=us-central1

# 4. Build frontend
cd frontend && npm install && npm run build && cd ..

# 5. Copy frontend build to backend static dir
mkdir -p backend/static
cp -r frontend/dist/* backend/static/

# 6. Deploy to Cloud Run (no Docker required)
cd backend
gcloud run deploy cyberloop \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 3600 \
  --session-affinity \
  --set-env-vars "GEMINI_API_KEY=YOUR_API_KEY,GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID"
```

Cloud Build compiles the container remotely and stores it in Artifact Registry. No local Docker needed.

---

## Verify

```bash
# Health check
curl https://YOUR_SERVICE_URL/health

# Open in browser
open https://YOUR_SERVICE_URL
```

The health check response should show `"firestore_available": true`.

---

## Google Cloud Services Used

| Service | Purpose |
|---------|---------|
| **Cloud Run** | Backend + frontend hosting, WebSocket support |
| **Cloud Firestore** | Session state, interview scores, report cards |
| **Cloud Build** | Builds container from source |
| **Artifact Registry** | Stores Docker images |

---

## Troubleshooting

### "Billing not enabled"
Go to https://console.cloud.google.com/billing and link a billing account.

### Firestore not connecting
Ensure `GOOGLE_CLOUD_PROJECT` is set in the Cloud Run env vars. The app falls back to in-memory sessions if Firestore is unavailable.

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
