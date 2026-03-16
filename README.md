# CyberLoop

**AI voice agent that conducts real-company-style mock interviews for cybersecurity roles.**

Practice with an interviewer that never goes easy on you.

Built for the [Gemini Live Agent Challenge](https://devpost.com/) | Live Agents Track

**Live Demo:** https://cyberloop-382549188807.us-central1.run.app

---

## What It Does

CyberLoop conducts realistic cybersecurity mock interviews using real-time voice, vision-based code analysis, and adaptive depth laddering. Three interview modes:

- **Hands-On Coding** — Write Python in a built-in Monaco editor. Run your code, get output analyzed by Gemini. The agent reviews your solution and probes your security analysis.
- **Behavioral** — STAR framework interviews with Amazon LP mapping. Tracks I-vs-we ratio, probes for specifics, detects story depth.
- **Technical Depth** — Four-level depth ladder (Foundational → Principal) that maps to real engineering leveling (Junior → Staff). Adapts in real-time based on your answers.

After each session, Gemini 2.5 Pro generates a detailed report card with domain scores, strengths, areas to improve, missed concepts, and study recommendations.

---

## Architecture

See [`demo/architecture-diagram.html`](demo/architecture-diagram.html) for the interactive visual diagram.

```
Browser (React + Monaco Editor + WebAudio)
        │
        │  WebSocket (PCM16 audio + JSON)
        ▼
Cloud Run: FastAPI + Google ADK
        │
        ├──► Gemini 2.5 Flash (native audio, Live API bidi streaming)
        │      Tools: evaluate_and_continue(), get_next_question(), end_interview()
        │      Config: context_window_compression, session_resumption
        │
        ├──► Gemini 2.5 Pro (report card generation, mode-specific scoring)
        │
        ├──► /run-code (sandboxed Python execution, 10s timeout)
        │
        └──► Cloud Firestore / Cloud Storage / Secret Manager
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Voice AI | Gemini 2.5 Flash (native audio via Live API) |
| Agent Framework | Google ADK (run_live, FunctionTool) |
| Report Scoring | Gemini 2.5 Pro |
| Backend | FastAPI (Python 3.12) |
| Frontend | React 18 + Vite 5 + TailwindCSS |
| Code Editor | Monaco Editor (@monaco-editor/react) |
| Audio | WebAudio API + AudioWorklet (PCM16) |
| Database | Cloud Firestore |
| Storage | Cloud Storage |
| Hosting | Cloud Run |
| Secrets | Secret Manager |

---

## Quickstart (Local Development)

### 1. Clone and configure

```bash
git clone https://github.com/obadiaha/cyberinterviewer.git
cd cyberinterviewer
cp .env.example .env
# Edit .env and add your GEMINI_API_KEY
```

### 2. Start the backend

```bash
cd backend
pip install -r requirements.txt
python3 -m uvicorn main:app --reload --port 8080
```

### 3. Start the frontend

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173` in Chrome (mic access required).

---

## Deploy to Google Cloud

```bash
# 1. Build frontend
cd frontend && npm run build && cd ..

# 2. Set API key
export GOOGLE_API_KEY="your-key"

# 3. Deploy (no Docker required)
cd backend
gcloud run deploy cyberloop \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --port 8080 \
  --timeout 3600 \
  --session-affinity \
  --set-env-vars "GEMINI_API_KEY=$GOOGLE_API_KEY"
```

Or use the automated deploy script: `bash deploy/deploy.sh`

---

## How It Works

### Depth Ladder

| Level | Maps To | What It Tests |
|-------|---------|--------------|
| L1 - Foundational | Junior | Do you know the concept? |
| L2 - Applied | Mid-Level | Can you use it in a scenario? |
| L3 - Architectural | Senior | Can you design the solution with tradeoffs? |
| L4 - Principal | Staff | Can you challenge the premise? |

The agent advances when you demonstrate depth, skips levels if you answer comprehensively, and detects your ceiling after 3 consecutive same-level responses.

### Smart Probe Selection

9 static depth probes per challenge, ordered basic to advanced. Before asking each probe, the system checks your transcript for concept coverage. If you already mentioned brute force, exfiltration, and persistence, those probes get skipped.

### Interview Domains

- **Incident Response & Triage**
- **Detection Engineering**
- **Digital Forensics (DFIR)**
- **SOC Operations**
- **Threat Intelligence**

### Company Styles

- **Amazon** — Bar raiser. Deep behavioral dives. "What did YOU specifically do?"
- **SpaceX** — First principles. Systems thinking. "What breaks first?"
- **Generic** — Professional, structured, fair.

---

## Google Cloud Services

| Service | Purpose |
|---------|---------|
| **Cloud Run** | Backend API + frontend hosting |
| **Cloud Firestore** | Session state, scores, report cards |
| **Cloud Storage** | Question trees, scoring rubrics |
| **Secret Manager** | API key storage |
| **Cloud Build** | Container builds |
| **Artifact Registry** | Docker image storage |

---

## Project Structure

```
cyberloop/
├── backend/
│   ├── main.py                  # FastAPI app + /run-code endpoint
│   ├── agent/
│   │   ├── adk_interviewer.py   # ADK session runner (run_live)
│   │   ├── adk_agent.py         # Agent factory + tool closures
│   │   ├── tools.py             # evaluate_and_continue, depth probes
│   │   ├── prompts.py           # Company personas + mode instructions
│   │   └── session.py           # Session state management
│   ├── engine/
│   │   ├── scoring.py           # Semantic scoring engine
│   │   └── report.py            # Report card generation
│   └── data/
│       ├── question_trees/      # 6 domain question banks
│       ├── calibration/         # Level calibration data
│       └── rubrics/             # Scoring rubrics
├── frontend/
│   └── src/
│       ├── pages/               # Setup, Interview, ReportCard
│       ├── components/          # AudioVisualizer, ScoreCard
│       └── hooks/               # useAudioStream, useWebSocket
├── deploy/                      # Cloud Run deployment scripts
└── demo/                        # Architecture diagram
```

---

## License

[MIT](LICENSE)

---

Built for the **Gemini Live Agent Challenge** using [Google Gemini](https://ai.google.dev/), [Google ADK](https://github.com/google/adk-python), and [Google Cloud](https://cloud.google.com/).

*CyberLoop: Practice with an interviewer that never goes easy on you.*
