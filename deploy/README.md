# CyberLoop - GCP Deployment

## Quick Start (Shell Script)

```bash
# Set your API key
export GOOGLE_API_KEY="your-gemini-api-key"

# Optional: override project ID (default: cyberloop-hackathon)
export GOOGLE_CLOUD_PROJECT="your-project-id"

# Deploy
bash deploy/deploy.sh
```

This will:
- Enable required GCP APIs
- Create an Artifact Registry repo
- Build and push the Docker image
- Deploy to Cloud Run (1 CPU, 1Gi RAM, max 3 instances)
- Print the service URL

## Cloud Build (CI/CD)

Set up a trigger for automatic deploys on push to main:

```bash
gcloud builds triggers create github \
  --repo-name=cyberloop \
  --repo-owner=YOUR_GITHUB_USER \
  --branch-pattern="^main$" \
  --build-config=deploy/cloudbuild.yaml
```

Store your API key in Secret Manager first:

```bash
echo -n "your-key" | gcloud secrets create google-api-key --data-file=-
```

## Terraform

```bash
cd deploy/terraform

terraform init

terraform plan \
  -var="project_id=your-project-id" \
  -var="image=us-central1-docker.pkg.dev/your-project/cyberloop/api:latest" \
  -var="api_key=your-api-key"

terraform apply \
  -var="project_id=your-project-id" \
  -var="image=us-central1-docker.pkg.dev/your-project/cyberloop/api:latest" \
  -var="api_key=your-api-key"
```

## Architecture

- **Backend**: Python FastAPI on Cloud Run (port 8080)
- **Container**: Python 3.13 slim, multi-stage build
- **Scaling**: 0-3 instances, 3600s timeout for WebSocket sessions
- **Auth**: Unauthenticated (demo mode)
