#!/usr/bin/env bash
# ============================================================
# CyberLoop - Deployment Recording Script
# ============================================================
# Captures terminal output of the Cloud Run deployment
# for hackathon submission proof.
#
# Usage:
#   cd ~/cyberloop
#   bash deploy/record-proof.sh
#
# Output:
#   deploy/deployment-proof.txt    (raw terminal log)
#   deploy/deployment-proof.mp4    (if asciinema + agg available)
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "${SCRIPT_DIR}")"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FILE="${SCRIPT_DIR}/deployment-proof.txt"
CAST_FILE="${SCRIPT_DIR}/deployment-proof.cast"

# Colors
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${CYAN}"
echo "============================================"
echo "  CyberLoop - Deployment Recording"
echo "============================================"
echo -e "${NC}"

# Check GOOGLE_API_KEY
if [ -z "${GOOGLE_API_KEY:-}" ]; then
  # Try to load from .env
  if [ -f "${PROJECT_ROOT}/../../.env" ]; then
    source <(grep "^GOOGLE_API_KEY=" "${PROJECT_ROOT}/../../.env")
    echo -e "${GREEN}[OK]${NC} Loaded GOOGLE_API_KEY from .env"
  fi
fi

if [ -z "${GOOGLE_API_KEY:-}" ]; then
  echo -e "${YELLOW}[!!]${NC} GOOGLE_API_KEY not set. Export it first:"
  echo "  export GOOGLE_API_KEY='your-key'"
  exit 1
fi

export GOOGLE_API_KEY

# Check for asciinema (fancy recording)
if command -v asciinema >/dev/null 2>&1; then
  echo -e "${GREEN}[OK]${NC} asciinema found. Recording animated terminal..."
  echo ""
  echo -e "${YELLOW}  Recording will start. Run the deploy commands, then type 'exit' when done.${NC}"
  echo ""

  # Record with asciinema
  asciinema rec "${CAST_FILE}" \
    --title "CyberLoop - Cloud Run Deployment" \
    --idle-time-limit 3 \
    --command "bash ${SCRIPT_DIR}/deploy.sh 2>&1 | tee ${LOG_FILE}"

  echo ""
  echo -e "${GREEN}[OK]${NC} Recording saved:"
  echo "  Cast: ${CAST_FILE}"
  echo "  Log:  ${LOG_FILE}"

  # Convert to GIF/MP4 if agg is available
  if command -v agg >/dev/null 2>&1; then
    GIF_FILE="${SCRIPT_DIR}/deployment-proof.gif"
    agg "${CAST_FILE}" "${GIF_FILE}" 2>/dev/null && \
      echo -e "${GREEN}[OK]${NC} GIF: ${GIF_FILE}" || true
  fi

else
  # Fallback: use macOS 'script' command for plain text recording
  echo -e "${YELLOW}[!!]${NC} asciinema not found. Using 'script' for plain text recording."
  echo ""
  echo "To install asciinema for animated recordings:"
  echo "  brew install asciinema"
  echo ""

  echo -e "${GREEN}[>>]${NC} Starting deployment with recording..."
  echo ""
  echo "==============================" > "${LOG_FILE}"
  echo "CyberLoop Cloud Run Deploy" >> "${LOG_FILE}"
  echo "Date: $(date)" >> "${LOG_FILE}"
  echo "==============================" >> "${LOG_FILE}"
  echo "" >> "${LOG_FILE}"

  # Run deploy.sh and capture output
  script -q "${LOG_FILE}.raw" bash "${SCRIPT_DIR}/deploy.sh" 2>&1

  # Clean up control characters for readable log
  if command -v col >/dev/null 2>&1; then
    col -b < "${LOG_FILE}.raw" >> "${LOG_FILE}"
    rm -f "${LOG_FILE}.raw"
  else
    cat "${LOG_FILE}.raw" >> "${LOG_FILE}"
    rm -f "${LOG_FILE}.raw"
  fi

  echo ""
  echo -e "${GREEN}[OK]${NC} Deployment log saved: ${LOG_FILE}"
fi

echo ""
echo "============================================"
echo "  Proof files for hackathon submission:"
echo "============================================"
echo ""
echo "  ${LOG_FILE}"
[ -f "${CAST_FILE}" ] && echo "  ${CAST_FILE}"
[ -f "${SCRIPT_DIR}/deployment-proof.gif" ] && echo "  ${SCRIPT_DIR}/deployment-proof.gif"
echo ""
echo "  Include these in your hackathon submission"
echo "  to prove the app deploys to GCP Cloud Run."
echo ""
