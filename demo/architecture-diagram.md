# CyberLoop Architecture Diagram

**Export as:** `architecture.png` (place in repo root)

---

## Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│                         User's Browser                               │
│                     React 18 + Vite + TailwindCSS                    │
│                                                                       │
│  ┌──────────────┐  ┌───────────────────────┐  ┌──────────────────┐  │
│  │  Setup Page   │  │   Live Interview      │  │   Report Card    │  │
│  │  • Company    │  │   🎤 Voice Audio      │  │   • Domain Scores│  │
│  │  • Level      │  │   📝 Monaco Editor    │  │   • Strengths    │  │
│  │  • Mode       │  │   ▶️  Run Code Button │  │   • Improvements │  │
│  │  • Domain     │  │   🖥️  Screen Share    │  │   • Transcript   │  │
│  └──────────────┘  │   📊 Live Transcript   │  │   • Study Recs   │  │
│                     └───────────────────────┘  └──────────────────┘  │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
              WebSocket (PCM16 audio + JSON)
              ↕ Bidirectional: audio, transcripts,
                screen frames, code results, tool events
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                    FastAPI Backend (Cloud Run)                        │
│                                                                       │
│  ┌────────────────────┐    ┌─────────────────────────────────────┐  │
│  │  Session Handler   │    │  Interview Agent (Google ADK)       │  │
│  │  • WebSocket mgmt  │    │  • Runner.run_live() bidi streaming │  │
│  │  • Audio routing   │    │  • Automatic voice activity detect  │  │
│  │  • Screen frame    │    │  • Context window compression      │  │
│  │    storage         │    │  • Session resumption              │  │
│  │  • Code execution  │    │                                     │  │
│  │    (subprocess)    │    │  Tools (ADK FunctionTool):          │  │
│  │  • Transcript      │    │  ┌──────────────────────────────┐  │  │
│  │    dedup + flush   │    │  │ evaluate_and_continue()      │  │  │
│  │  • Audio repetition│    │  │  → Score + Advance + Next Q  │  │  │
│  │    detection       │    │  │  → Smart probe skipping      │  │  │
│  └────────────────────┘    │  │  → Code + output in response │  │  │
│                             │  ├──────────────────────────────┤  │  │
│  ┌────────────────────┐    │  │ get_next_question()          │  │  │
│  │  /run-code         │    │  │  → Depth ladder navigation   │  │  │
│  │  Python sandbox    │    │  │  → Concept coverage check    │  │  │
│  │  10s timeout       │    │  ├──────────────────────────────┤  │  │
│  │  stdout/stderr     │    │  │ end_interview()              │  │  │
│  └────────────────────┘    │  │  → Report generation trigger │  │  │
│                             │  └──────────────────────────────┘  │  │
│                             └─────────────────────────────────────┘  │
└───────┬──────────────────────────┬──────────────────────────────────┘
        │                          │
        │  ◄───── Realtime ──────► │
        │                          │
        ▼                          ▼
┌───────────────────┐    ┌──────────────────────────────────┐
│ ☁️ Gemini 2.5     │    │ ☁️ Gemini 2.5 Pro               │
│    Flash          │    │    Report Analysis               │
│                   │    │                                  │
│ • Native Audio    │    │ • Full transcript evaluation     │
│   (Charon voice)  │    │ • Mode-specific scoring:         │
│ • Live API bidi   │    │   - Coding: approach, code       │
│ • Vision (screen  │    │     quality, security insight    │
│   frames)         │    │   - Behavioral: STAR, I-vs-we   │
│ • Function calling│    │   - Technical: depth, specificity│
│ • Input/output    │    │ • Strengths & improvements       │
│   transcription   │    │ • Missed concepts (semantic)     │
│                   │    │ • Study recommendations          │
│ Config:           │    └──────────────────────────────────┘
│ • compression:    │
│   sliding_window  │
│   (20K tokens)    │
│ • session_        │
│   resumption      │
│ • silence: 2000ms │
└───────────────────┘

        ┌──────────────────────────────────────────────────┐
        │              Data Layer                            │
        │                                                    │
        │  ┌──────────────┐  ┌───────────────┐  ┌────────┐ │
        │  │  Firestore   │  │ Cloud Storage │  │ Secret │ │
        │  │  • Sessions  │  │ • Question    │  │ Manager│ │
        │  │  • Exchanges │  │   Trees (6)   │  │ • API  │ │
        │  │  • Scores    │  │ • Calibration │  │   Keys │ │
        │  │  • Reports   │  │ • Rubrics     │  └────────┘ │
        │  │  • Transcript│  │ • Company     │              │
        │  └──────────────┘  │   Profiles    │              │
        │                     └───────────────┘              │
        └──────────────────────────────────────────────────┘
```

---

## Key Architectural Features

### Real-Time Voice Pipeline
```
Browser Mic → PCM16 Float32 → AudioWorklet → Base64 → WebSocket
  → FastAPI → LiveRequestQueue.send_realtime() → Gemini Live API
  → Audio response → Base64 → WebSocket → AudioWorklet → Speaker
```

### Vision Pipeline (Code Execution)
```
Monaco Editor → Click "Run" → /run-code (subprocess) → stdout/stderr
  → WebSocket code_result → send_content(text + screen_frame)
  → Gemini analyzes output → Spoken feedback referencing results
```

### Smart Depth Ladder
```
Root Question (L1) → Candidate answers → evaluate_and_continue()
  → Check concept coverage against transcript
  → Skip probes already answered → Find next uncovered probe
  → Return probe text for agent to paraphrase naturally
```

### Interruption Handling
```
Candidate speaks over agent → START_SENSITIVITY_HIGH detects voice
  → interrupted event → Agent yields floor
  → Barge-in gate (RMS > 0.08) prevents echo false-triggers
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Voice AI | Gemini 2.5 Flash (native audio, Live API) |
| Agent Framework | Google ADK (run_live, FunctionTool) |
| Report Scoring | Gemini 2.5 Pro (batch analysis) |
| Backend | FastAPI + Python 3.12 |
| Frontend | React 18 + Vite 5 + TypeScript + TailwindCSS |
| Code Editor | Monaco Editor (@monaco-editor/react) |
| Audio | WebAudio API + AudioWorklet (PCM16) |
| Database | Cloud Firestore |
| Storage | Cloud Storage |
| Hosting | Cloud Run |
| Secrets | Secret Manager |

---

## Interview Modes

| Mode | Agent Behavior | Scoring Rubric |
|------|---------------|----------------|
| **Coding** | Presents log parsing challenge, observes coding, reviews output | Approach 30%, Code Quality 25%, Security Insight 25%, Communication 10%, Speed 10% |
| **Behavioral** | STAR probing, "what did YOU do?", pushes for metrics | STAR structure, I-vs-we ratio, depth under pressure, story count |
| **Technical** | Depth ladder L1→L4, concept coverage, ceiling detection | Technical depth 40%, Specificity 30%, Communication 20%, Breadth 10% |
