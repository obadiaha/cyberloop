import { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Mic,
  MicOff,
  SkipForward,
  PhoneOff,
  Shield,
  Wifi,
  WifiOff,
  Loader2,
  Clock,
  Layers,
  Hash,
  Monitor,
  Video,
  ChevronDown,
  ChevronUp,
} from 'lucide-react';
import AudioVisualizer from '../components/AudioVisualizer';
import { useAudioStream, TranscriptEntry, ChallengeData } from '../hooks/useAudioStream';
import Editor from '@monaco-editor/react';

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
}

const DEPTH_LABELS: Record<number, string> = {
  1: 'L1: Foundational',
  2: 'L2: Applied',
  3: 'L3: Architectural',
  4: 'L4: Principal',
};

export default function Interview() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [started, setStarted] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [ending, setEnding] = useState(false);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const screenVideoRef = useRef<HTMLVideoElement>(null);
  const webcamVideoRef = useRef<HTMLVideoElement>(null);
  const editorRef = useRef<any>(null);
  const terminalRef = useRef<HTMLDivElement>(null);
  const [codeOutput, setCodeOutput] = useState<{ stdout: string; stderr: string; exit_code: number } | null>(null);
  const [isRunning, setIsRunning] = useState(false);

  const {
    start,
    stop,
    toggleMute,
    isMuted,
    connectionStatus,
    transcript,
    currentQuestion,
    interviewState,
    audioLevel,
    agentAudioLevel,
    error,
    startScreenShare,
    stopScreenShare,
    isScreenSharing,
    startWebcam,
    stopWebcam,
    isWebcamActive,
    sendMessage,
  } = useAudioStream(sessionId!);

  // Elapsed timer
  useEffect(() => {
    if (!started) return;
    const interval = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(interval);
  }, [started]);

  // Auto-scroll transcript
  useEffect(() => {
    transcriptEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [transcript]);

  // Navigate to report when ready
  useEffect(() => {
    if (interviewState.type === 'report_ready') {
      navigate(`/report/${interviewState.session_id || sessionId}`);
    }
  }, [interviewState, navigate, sessionId]);

  // Auto-prompt webcam for behavioral mode only
  // Coding mode: screen share is prompted by the AI voice AFTER the warm-up question
  const [autoPrompted, setAutoPrompted] = useState(false);
  useEffect(() => {
    if (!started || autoPrompted || !interviewState.mode) return;
    const mode = interviewState.mode;
    if (mode === 'behavioral' && !isWebcamActive) {
      const timer = setTimeout(async () => {
        const stream = await startWebcam();
        if (stream && webcamVideoRef.current) {
          webcamVideoRef.current.srcObject = stream;
        }
      }, 2000);
      setAutoPrompted(true);
      return () => clearTimeout(timer);
    }
  }, [started, interviewState.mode, autoPrompted]);

  const handleStart = async () => {
    await start();
    setStarted(true);
  };

  const handleEnd = () => {
    setEnding(true);
    stop();
    // Navigate to report after a short delay for the backend to generate it
    setTimeout(() => {
      navigate(`/report/${sessionId}`);
    }, 2000);
  };

  const handleSkip = () => {
    // Send skip signal through websocket
    // The useAudioStream hook exposes send via the underlying ws
  };

  const handleToggleScreenShare = async () => {
    if (isScreenSharing) {
      stopScreenShare();
    } else {
      const stream = await startScreenShare();
      if (stream && screenVideoRef.current) {
        screenVideoRef.current.srcObject = stream;
      }
    }
  };

  const handleToggleWebcam = async () => {
    if (isWebcamActive) {
      stopWebcam();
    } else {
      const stream = await startWebcam();
      if (stream && webcamVideoRef.current) {
        webcamVideoRef.current.srcObject = stream;
      }
    }
  };

  // Send editor code to backend periodically so the agent can reference line numbers
  const lastCodeRef = useRef('');
  useEffect(() => {
    if (!started || interviewState.mode !== 'coding') return;
    const interval = setInterval(() => {
      if (!editorRef.current) return;
      const code = editorRef.current.getValue() || '';
      if (code !== lastCodeRef.current && code.trim() !== '# Write your solution here') {
        lastCodeRef.current = code;
        sendMessage({ type: 'code_update', code });
      }
    }, 5000);
    return () => clearInterval(interval);
  }, [started, interviewState.mode, sendMessage]);

  const handleRunCode = async () => {
    if (!editorRef.current || isRunning) return;
    const code = editorRef.current.getValue();
    if (!code.trim()) return;

    setIsRunning(true);
    try {
      const res = await fetch('/run-code', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      const result = await res.json();
      setCodeOutput(result);

      // Send code + output to backend for agent context (vision + text)
      // Wait a tick for the terminal to render, then capture screenshot
      setTimeout(() => {
        // Send screen frame if sharing (for vision)
        if ((window as any).__captureScreenFrame) {
          (window as any).__captureScreenFrame();
        }
        // Send code + output via WebSocket
        sendMessage({
          type: 'code_result',
          code,
          stdout: result.stdout,
          stderr: result.stderr,
          exit_code: result.exit_code,
        });
      }, 500);
    } catch (err) {
      setCodeOutput({ stdout: '', stderr: 'Failed to execute code', exit_code: -1 });
    } finally {
      setIsRunning(false);
    }
  };

  const isConnected = connectionStatus === 'connected';
  const isReconnecting = connectionStatus === 'reconnecting';
  const depthLevel = interviewState.depth_level || 1;
  const questionCount = interviewState.question_count || 0;
  const domain = interviewState.domain || 'Interview';

  if (!started) {
    return (
      <div className="min-h-screen flex flex-col">
        <header className="border-b border-cyber-border px-6 py-4">
          <div className="max-w-5xl mx-auto flex items-center gap-3">
            <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
              <Shield className="w-6 h-6 text-cyber-cyan" />
              <h1 className="text-lg font-semibold tracking-tight">CyberLoop</h1>
            </Link>
          </div>
        </header>

        <main className="flex-1 flex items-center justify-center px-6">
          <div className="max-w-md w-full text-center space-y-8">
            <div className="space-y-3">
              <div className="w-20 h-20 mx-auto rounded-full bg-cyber-card border-2 border-cyber-cyan flex items-center justify-center">
                <Mic className="w-8 h-8 text-cyber-cyan" />
              </div>
              <h2 className="text-xl font-bold">Ready to Begin</h2>
              <p className="text-cyber-text-dim text-sm">
                CyberLoop needs microphone access to conduct the interview.
                Click start to begin your session.
              </p>
            </div>

            {error && (
              <div className="bg-cyber-red/10 border border-cyber-red/30 rounded-lg px-4 py-3 text-sm text-cyber-red">
                {error}
              </div>
            )}

            <button
              onClick={handleStart}
              className="cyber-btn-primary text-base px-10 py-4"
            >
              Start Interview
            </button>

            <p className="text-xs text-cyber-text-muted">
              Your browser will request microphone permission.
            </p>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* Status Bar */}
      <header className="border-b border-cyber-border px-4 py-2">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
                <Shield className="w-4 h-4 text-cyber-cyan" />
                <span className="text-sm font-semibold">CyberLoop</span>
              </Link>
            </div>
            <div className="h-4 w-px bg-cyber-border" />
            <span className="text-xs font-mono text-cyber-text-dim">{domain}</span>
          </div>

          <div className="flex items-center gap-4 text-xs font-mono">
            {/* Depth Level */}
            <div className="flex items-center gap-1.5 text-cyber-text-dim">
              <Layers className="w-3.5 h-3.5" />
              <span className={depthLevel >= 3 ? 'text-cyber-green' : ''}>
                {DEPTH_LABELS[depthLevel] || `L${depthLevel}`}
              </span>
            </div>

            {/* Question Count */}
            <div className="flex items-center gap-1.5 text-cyber-text-dim">
              <Hash className="w-3.5 h-3.5" />
              <span>Q{questionCount}</span>
            </div>

            {/* Timer */}
            <div className="flex items-center gap-1.5 text-cyber-text-dim">
              <Clock className="w-3.5 h-3.5" />
              <span>{formatTime(elapsed)}</span>
            </div>

            {/* Connection Status */}
            <div className="flex items-center gap-1.5">
              {isConnected ? (
                <Wifi className="w-3.5 h-3.5 text-cyber-green" />
              ) : isReconnecting ? (
                <Loader2 className="w-3.5 h-3.5 text-cyber-amber animate-spin" />
              ) : (
                <WifiOff className="w-3.5 h-3.5 text-cyber-red" />
              )}
              <span
                className={
                  isConnected
                    ? 'text-cyber-green'
                    : isReconnecting
                    ? 'text-cyber-amber'
                    : 'text-cyber-red'
                }
              >
                {isConnected ? 'Connected' : isReconnecting ? 'Reconnecting' : 'Disconnected'}
              </span>
            </div>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="flex-1 flex flex-col lg:flex-row">
        {/* Left: Visualizer + Controls */}
        <div className="flex-1 flex flex-col items-center justify-center px-6 py-8 space-y-8">
          {/* Current Question */}
          {currentQuestion && (
            <div className="w-full px-2" style={{ maxWidth: '900px' }}>
              <div className="cyber-card border-cyber-cyan/20">
                <p className="text-sm text-cyber-text-dim mb-1 font-mono uppercase tracking-wider">
                  Current Question
                </p>
                <p className="text-cyber-text leading-relaxed">{currentQuestion}</p>
              </div>
            </div>
          )}

          {/* Challenge hint (coding mode) */}
          {interviewState.challenge_data && interviewState.challenge_data.title !== 'Code Reading - What\'s the output?' && (
            <div className="w-full px-2" style={{ maxWidth: '900px' }}>
              <div className="cyber-card border-yellow-500/30 bg-yellow-950/10">
                <p className="text-xs font-mono text-yellow-400 leading-relaxed">
                  💡 Think out loud as you work. Talk through your reasoning, approach, and data structures.
                  You can ask clarifying questions. The interviewer will guide you but won't give the answer.
                </p>
              </div>
            </div>
          )}
          {/* Apache Access Log box removed - logs are in the code editor */}

          {/* Code Editor (coding mode only) */}
          {interviewState.mode === 'coding' && interviewState.challenge_data && (
            <div className="w-full px-2" style={{ maxWidth: '900px' }}>
              <div
                className="cyber-card border-cyber-cyan/20 p-0"
                style={{ resize: 'vertical', overflow: 'hidden', height: '650px', minHeight: '200px', maxHeight: '85vh' }}
              >
                <div className="flex items-center justify-between px-3 py-1.5 bg-[#1e1e1e] border-b border-[#30363d]">
                  <div className="flex items-center gap-2">
                    <div className="flex gap-1">
                      <span className="w-2.5 h-2.5 rounded-full bg-red-500/80" />
                      <span className="w-2.5 h-2.5 rounded-full bg-yellow-500/80" />
                      <span className="w-2.5 h-2.5 rounded-full bg-green-500/80" />
                    </div>
                    <span className="text-xs font-mono text-cyber-text-muted">solution.py</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] font-mono text-cyber-text-muted">Python</span>
                    <button
                      onClick={handleRunCode}
                      disabled={isRunning}
                      className="text-xs px-3 py-0.5 rounded bg-cyber-green/20 text-cyber-green border border-cyber-green/30 hover:bg-cyber-green/30 transition-colors font-mono disabled:opacity-50"
                    >
                      {isRunning ? 'Running...' : 'Run'}
                    </button>
                  </div>
                </div>
                <Editor
                  height="calc(100% - 32px)"
                  defaultLanguage="python"
                  defaultValue={`# Apache Access Logs (15 lines)
# ──────────────────────────────────────────────────────────────────────
logs = """192.168.1.50 - - [13/Mar/2026:08:15:22 +0000] "GET /index.html HTTP/1.1" 200 1024
10.0.0.33 - - [13/Mar/2026:08:15:23 +0000] "POST /login HTTP/1.1" 401 512
192.168.1.50 - - [13/Mar/2026:08:15:24 +0000] "GET /admin HTTP/1.1" 403 256
10.0.0.33 - - [13/Mar/2026:08:15:25 +0000] "POST /login HTTP/1.1" 401 512
172.16.5.100 - - [13/Mar/2026:08:15:26 +0000] "GET /api/users HTTP/1.1" 200 2048
10.0.0.33 - - [13/Mar/2026:08:15:27 +0000] "POST /login HTTP/1.1" 401 512
10.0.0.33 - - [13/Mar/2026:08:15:28 +0000] "POST /login HTTP/1.1" 200 1024
10.0.0.33 - - [13/Mar/2026:08:15:29 +0000] "GET /admin/config HTTP/1.1" 200 4096
10.0.0.33 - - [13/Mar/2026:08:15:30 +0000] "GET /admin/users/export HTTP/1.1" 200 8192
192.168.1.50 - - [13/Mar/2026:08:16:01 +0000] "GET /dashboard HTTP/1.1" 200 2048
10.0.0.99 - - [13/Mar/2026:08:16:15 +0000] "GET /api/health HTTP/1.1" 200 128
10.0.0.33 - - [13/Mar/2026:08:16:20 +0000] "POST /admin/users/create HTTP/1.1" 201 512
172.16.5.100 - - [13/Mar/2026:08:16:25 +0000] "DELETE /api/users/15 HTTP/1.1" 204 0
10.0.0.33 - - [13/Mar/2026:08:16:30 +0000] "GET /admin/logs/clear HTTP/1.1" 200 256
192.168.1.50 - - [13/Mar/2026:08:17:00 +0000] "GET /about HTTP/1.1" 200 1024"""

# Write your solution below
`}
                  theme="vs-dark"
                  onMount={(editor) => { editorRef.current = editor; }}
                  options={{
                    fontSize: 13,
                    minimap: { enabled: false },
                    scrollBeyondLastLine: false,
                    lineNumbers: 'on',
                    renderLineHighlight: 'line',
                    padding: { top: 8 },
                    automaticLayout: true,
                    autoIndent: 'none',
                    tabSize: 4,
                    insertSpaces: true,
                  }}
                />
              </div>

              {/* Terminal Output */}
              {codeOutput && (
                <div ref={terminalRef} className="border-t border-[#30363d] bg-[#0d1117] px-4 py-3 max-h-48 overflow-y-auto">
                  <div className="flex items-center gap-2 mb-2">
                    <span className="text-[10px] font-mono text-cyber-text-muted uppercase tracking-wider">
                      Output {codeOutput.exit_code === 0 ? '✓' : '✗'}
                    </span>
                  </div>
                  {codeOutput.stdout && (
                    <pre className="text-xs font-mono text-cyber-green whitespace-pre-wrap">{codeOutput.stdout}</pre>
                  )}
                  {codeOutput.stderr && (
                    <pre className="text-xs font-mono text-cyber-red whitespace-pre-wrap">{codeOutput.stderr}</pre>
                  )}
                  {!codeOutput.stdout && !codeOutput.stderr && (
                    <pre className="text-xs font-mono text-cyber-text-muted">(no output)</pre>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Audio Visualizer */}
          <AudioVisualizer
            audioLevel={audioLevel}
            agentAudioLevel={agentAudioLevel}
            isActive={isConnected}
            width={Math.min(600, window.innerWidth - 48)}
            height={180}
          />

          {/* Controls */}
          <div className="flex items-center gap-4">
            <button
              onClick={toggleMute}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isMuted
                  ? 'bg-cyber-red/20 text-cyber-red border border-cyber-red/30'
                  : 'bg-cyber-card border border-cyber-border text-cyber-text-dim hover:border-cyber-cyan hover:text-cyber-cyan'
              }`}
            >
              {isMuted ? (
                <>
                  <MicOff className="w-4 h-4" />
                  Muted
                </>
              ) : (
                <>
                  <Mic className="w-4 h-4" />
                  Mute
                </>
              )}
            </button>

            <button
              onClick={handleToggleScreenShare}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isScreenSharing
                  ? 'bg-cyber-green/20 text-cyber-green border border-cyber-green/30'
                  : 'bg-cyber-card border border-cyber-border text-cyber-text-dim hover:border-cyber-cyan hover:text-cyber-cyan'
              }`}
            >
              <Monitor className="w-4 h-4" />
              {isScreenSharing ? 'Sharing' : 'Share Screen'}
            </button>

            <button
              onClick={handleToggleWebcam}
              className={`flex items-center gap-2 px-5 py-2.5 rounded-lg text-sm font-medium transition-all ${
                isWebcamActive
                  ? 'bg-cyber-green/20 text-cyber-green border border-cyber-green/30'
                  : 'bg-cyber-card border border-cyber-border text-cyber-text-dim hover:border-cyber-cyan hover:text-cyber-cyan'
              }`}
            >
              <Video className="w-4 h-4" />
              {isWebcamActive ? 'Camera On' : 'Camera'}
            </button>

            <button
              onClick={handleSkip}
              className="cyber-btn-secondary flex items-center gap-2"
            >
              <SkipForward className="w-4 h-4" />
              Skip
            </button>

            <button
              onClick={handleEnd}
              disabled={ending}
              className="cyber-btn-danger flex items-center gap-2"
            >
              {ending ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Ending...
                </>
              ) : (
                <>
                  <PhoneOff className="w-4 h-4" />
                  End Interview
                </>
              )}
            </button>
          </div>

          {/* Screen Share Preview */}
          {isScreenSharing && (
            <div className="fixed bottom-4 left-4 z-50">
              <video
                ref={screenVideoRef}
                autoPlay
                muted
                className="w-[200px] h-[150px] rounded-lg border-2 border-cyber-cyan/50 object-cover shadow-lg"
              />
            </div>
          )}

          {/* Webcam Preview */}
          {isWebcamActive && (
            <div className="fixed top-20 right-4 z-50">
              <video
                ref={webcamVideoRef}
                autoPlay
                muted
                className="w-20 h-20 rounded-full border-2 border-cyber-cyan object-cover shadow-lg"
              />
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="bg-cyber-red/10 border border-cyber-red/30 rounded-lg px-4 py-3 text-sm text-cyber-red max-w-md">
              {error}
            </div>
          )}
        </div>

        {/* Right: Transcript + Rubric */}
        <aside className="lg:w-96 border-t lg:border-t-0 lg:border-l border-cyber-border flex flex-col">
          {/* Collapsible Rubric */}
          <RubricPanel mode={interviewState.mode} />
          <div className="px-4 py-3 border-b border-cyber-border">
            <h3 className="text-sm font-semibold text-cyber-text-dim uppercase tracking-wider">
              Live Transcript
            </h3>
          </div>
          <div className="flex-1 overflow-y-auto px-4 py-3 space-y-3 max-h-[calc(100vh-200px)]">
            {transcript.length === 0 ? (
              <p className="text-cyber-text-muted text-sm text-center py-8 font-mono">
                Transcript will appear here...
              </p>
            ) : (
              transcript.map((entry, i) => (
                <TranscriptBubble key={i} entry={entry} />
              ))
            )}
            <div ref={transcriptEndRef} />
          </div>
        </aside>
      </main>
    </div>
  );
}

function CodeLine({ line }: { line: string }) {
  if (!line.trim()) return <span>{'\u00A0'}</span>;

  // Comments
  if (line.trimStart().startsWith('#')) {
    const indent = line.match(/^(\s*)/)?.[1] || '';
    return <span><span>{indent}</span><span style={{ color: '#8b949e', fontStyle: 'italic' }}>{line.trimStart()}</span></span>;
  }

  // Tokenize the line into colored segments
  const tokens: { text: string; color?: string }[] = [];
  const keywords = new Set(['import', 'from', 'def', 'return', 'if', 'else', 'elif', 'for', 'in', 'not', 'and', 'or', 'while', 'try', 'except', 'with', 'as', 'class', 'print', 'True', 'False', 'None']);
  const builtins = new Set(['int', 'str', 'list', 'dict', 'set', 'len', 'range', 'max', 'min', 'round', 'split', 'strip', 'get', 'append', 'items', 'keys', 'values']);

  let i = 0;
  let buf = '';

  const flush = () => { if (buf) { tokens.push({ text: buf }); buf = ''; } };

  while (i < line.length) {
    const ch = line[i];
    // Strings
    if (ch === '"' || ch === "'") {
      flush();
      const fPrefix = i > 0 && line[i - 1] === 'f' ? (() => { tokens[tokens.length - 1].text = tokens[tokens.length - 1]?.text.slice(0, -1) || ''; return 'f'; })() : '';
      const quote = ch;
      let s = fPrefix + quote;
      i++;
      while (i < line.length && line[i] !== quote) { s += line[i]; i++; }
      if (i < line.length) { s += line[i]; i++; }
      tokens.push({ text: s, color: '#a5d6ff' });
      continue;
    }
    // Word boundaries
    if (/[a-zA-Z_]/.test(ch)) {
      flush();
      let word = '';
      while (i < line.length && /[a-zA-Z_0-9]/.test(line[i])) { word += line[i]; i++; }
      if (keywords.has(word)) {
        tokens.push({ text: word, color: '#ff7b72' });
      } else if (builtins.has(word)) {
        tokens.push({ text: word, color: '#d2a8ff' });
      } else {
        tokens.push({ text: word });
      }
      continue;
    }
    // Numbers
    if (/\d/.test(ch)) {
      flush();
      let num = '';
      while (i < line.length && /\d/.test(line[i])) { num += line[i]; i++; }
      tokens.push({ text: num, color: '#79c0ff' });
      continue;
    }
    buf += ch;
    i++;
  }
  flush();

  return (
    <span>
      {tokens.map((t, idx) =>
        t.color ? <span key={idx} style={{ color: t.color }}>{t.text}</span> : <span key={idx}>{t.text}</span>
      )}
    </span>
  );
}

function RubricPanel({ mode }: { mode?: string }) {
  const [expanded, setExpanded] = useState(true);

  const codingRubric = [
    { label: 'Approach', pct: 30, color: 'bg-cyber-cyan', tip: 'Plan first. Break down the problem.' },
    { label: 'Code Quality', pct: 25, color: 'bg-green-400', tip: 'Clean syntax, right data structures.' },
    { label: 'Security Insight', pct: 25, color: 'bg-yellow-400', tip: 'Interpret results. Spot the threat.' },
    { label: 'Communication', pct: 10, color: 'bg-purple-400', tip: 'Think out loud.' },
    { label: 'Speed', pct: 10, color: 'bg-orange-400', tip: "Don't freeze. Keep moving." },
  ];

  const technicalRubric = [
    { label: 'Technical Depth', pct: 40, color: 'bg-cyber-cyan', tip: 'Explain WHY, not just WHAT.' },
    { label: 'Specificity', pct: 30, color: 'bg-green-400', tip: 'Real tools, numbers, examples.' },
    { label: 'Communication', pct: 20, color: 'bg-purple-400', tip: 'Clear, organized, concise.' },
    { label: 'Overall', pct: 10, color: 'bg-yellow-400', tip: 'Holistic impression.' },
  ];

  const behavioralRubric = [
    { label: 'Story Depth', pct: 40, color: 'bg-cyber-cyan', tip: 'Named projects. Real details.' },
    { label: 'Specificity', pct: 30, color: 'bg-green-400', tip: '"I" not "we". Metrics. Impact.' },
    { label: 'Communication', pct: 20, color: 'bg-purple-400', tip: 'STAR structure. Clear arc.' },
    { label: 'Overall', pct: 10, color: 'bg-yellow-400', tip: 'Ownership and self-awareness.' },
  ];

  const rubric = mode === 'coding' ? codingRubric : mode === 'behavioral' ? behavioralRubric : technicalRubric;

  return (
    <div className="border-b border-cyber-border">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full px-4 py-2.5 flex items-center justify-between hover:bg-cyber-card/50 transition-colors"
      >
        <span className="text-xs font-semibold text-cyber-text-dim uppercase tracking-wider">
          Scoring Rubric
        </span>
        {expanded ? (
          <ChevronUp className="w-3.5 h-3.5 text-cyber-text-muted" />
        ) : (
          <ChevronDown className="w-3.5 h-3.5 text-cyber-text-muted" />
        )}
      </button>
      {expanded && (
        <div className="px-4 pb-3 space-y-1.5">
          {rubric.map((r) => (
            <div key={r.label} className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: 'currentColor' }}>
                <div className={`w-2 h-2 rounded-full ${r.color}`} />
              </div>
              <span className="text-xs text-cyber-text flex-1 truncate" title={r.tip}>
                {r.label}
              </span>
              <div className="w-16 h-1 bg-cyber-border rounded-full overflow-hidden flex-shrink-0">
                <div className={`h-full ${r.color} rounded-full`} style={{ width: `${r.pct}%` }} />
              </div>
              <span className="text-[10px] text-cyber-text-dim font-mono w-6 text-right">{r.pct}%</span>
            </div>
          ))}
          <p className="text-[10px] text-cyber-text-muted mt-1 italic">
            {mode === 'coding'
              ? 'Think out loud. Plan before you code.'
              : mode === 'behavioral'
              ? 'Use STAR. Say "I", not "we".'
              : 'Go deep. Explain the WHY.'}
          </p>
        </div>
      )}
    </div>
  );
}

function TranscriptBubble({ entry }: { entry: TranscriptEntry }) {
  const isAgent = entry.speaker === 'agent';
  return (
    <div className={`flex flex-col ${isAgent ? 'items-start' : 'items-end'}`}>
      <span
        className={`text-[10px] font-mono uppercase tracking-widest mb-1 ${
          isAgent ? 'text-cyber-cyan-dim' : 'text-cyber-text-muted'
        }`}
      >
        {isAgent ? 'Interviewer' : 'You'}
      </span>
      <div
        className={`rounded-lg px-3 py-2 text-sm max-w-[90%] leading-relaxed ${
          isAgent
            ? 'bg-cyber-cyan/5 border border-cyber-cyan/15 text-cyber-cyan'
            : 'bg-cyber-card border border-cyber-border text-cyber-text'
        }`}
      >
        {entry.text}
      </div>
    </div>
  );
}
