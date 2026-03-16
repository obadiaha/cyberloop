variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region for Cloud Run"
  type        = string
  default     = "us-central1"
}

variable "image" {
  description = "Docker image URI in Artifact Registry"
  type        = string
}

variable "api_key" {
  description = "Google/Gemini API key"
  type        = string
  sensitive   = true
}
