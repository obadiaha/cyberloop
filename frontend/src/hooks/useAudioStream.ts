import { useRef, useState, useCallback, useEffect } from 'react';
import { useWebSocket, WSStatus } from './useWebSocket';

export interface TranscriptEntry {
  speaker: 'agent' | 'candidate';
  text: string;
  timestamp: number;
}

export interface ChallengeData {
  title: string;
  type: string;
  content: string;
}

export interface InterviewEvent {
  type: string;
  domain?: string;
  depth_level?: number;
  question_count?: number;
  current_question?: string;
  scores?: any;
  session_id?: string;
  challenge_data?: ChallengeData;
  mode?: string;
}

export interface UseAudioStreamReturn {
  start: () => Promise<void>;
  stop: () => void;
  toggleMute: () => void;
  sendMessage: (data: any) => boolean;
  isMuted: boolean;
  connectionStatus: WSStatus;
  transcript: TranscriptEntry[];
  currentQuestion: string;
  interviewState: InterviewEvent;
  audioLevel: number;
  agentAudioLevel: number;
  error: string | null;
  startScreenShare: () => Promise<MediaStream | null>;
  stopScreenShare: () => void;
  isScreenSharing: boolean;
  startWebcam: () => Promise<MediaStream | null>;
  stopWebcam: () => void;
  isWebcamActive: boolean;
}

function float32ToPCM16(float32: Float32Array): ArrayBuffer {
  const buffer = new ArrayBuffer(float32.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < float32.length; i++) {
    const s = Math.max(-1, Math.min(1, float32[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return buffer;
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

function base64ToArrayBuffer(base64: string): ArrayBuffer {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes.buffer;
}

const PLAYBACK_SAMPLE_RATE = 24000;

export function useAudioStream(sessionId: string): UseAudioStreamReturn {
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [currentQuestion, setCurrentQuestion] = useState('');
  const [interviewState, setInterviewState] = useState<InterviewEvent>({
    type: 'init',
    depth_level: 1,
    question_count: 0,
  });
  const [isMuted, setIsMuted] = useState(false);
  const [audioLevel, setAudioLevel] = useState(0);
  const [agentAudioLevel, setAgentAudioLevel] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [isScreenSharing, setIsScreenSharing] = useState(false);
  const [isWebcamActive, setIsWebcamActive] = useState(false);

  const audioContextRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const sourceRef = useRef<MediaStreamAudioSourceNode | null>(null);
  const playbackContextRef = useRef<AudioContext | null>(null);
  const playbackWorkletRef = useRef<AudioWorkletNode | null>(null);
  const muteRef = useRef(false);
  const agentSpeakingRef = useRef(false);
  const pendingChallengeRef = useRef<ChallengeData | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const animFrameRef = useRef<number>(0);
  const sendRef = useRef<(data: any) => boolean>(() => false);
  const recorderWorkletRef = useRef<AudioWorkletNode | null>(null);
  const screenStreamRef = useRef<MediaStream | null>(null);
  const screenIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const webcamStreamRef = useRef<MediaStream | null>(null);
  const webcamIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${wsProtocol}//${window.location.host}/interview-adk/${sessionId}`;

  // --- Audio playback (AudioWorklet ring-buffer approach) ---

  const enqueueAudio = useCallback((pcmBuffer: ArrayBuffer) => {
    // Compute agent audio level for visualization
    const samples = new Int16Array(pcmBuffer);
    let rms = 0;
    for (let i = 0; i < samples.length; i++) {
      const s = samples[i] / 32768;
      rms += s * s;
    }
    rms = Math.sqrt(rms / samples.length);
    setAgentAudioLevel(Math.min(1, rms * 5));

    // Post raw PCM16 ArrayBuffer to the worklet's ring buffer
    if (playbackWorkletRef.current) {
      playbackWorkletRef.current.port.postMessage(pcmBuffer);
    }
  }, []);

  // --- WebSocket message handler ---

  const handleMessage = useCallback((data: any) => {
    switch (data.type) {
      case 'session_started': {
        const mode = data.mode || '';
        setInterviewState((prev) => ({ ...prev, mode, session_id: data.session_id }));
        console.log('[CI] Session started, mode:', mode);
        break;
      }
      case 'audio': {
        agentSpeakingRef.current = true;
        const pcmBuffer = base64ToArrayBuffer(data.data);
        enqueueAudio(pcmBuffer);
        break;
      }
      case 'transcript': {
        const speaker = data.speaker || 'agent';
        const text = data.text;

        // Filter out code snippets from transcript (they belong in the challenge panel)
        const looksLikeCode = /^(import |print\(|def |for |if |ips|ip |status|failed_codes|parts =|log_line)/m.test(text)
          || (text.split('\n').length > 4 && /[{}()\[\]=]/.test(text));
        if (looksLikeCode && speaker === 'agent') {
          // Skip adding code blocks to transcript
          break;
        }

        setTranscript((prev) => {
          // Append to the last entry if same speaker, otherwise create new bubble
          if (prev.length > 0 && prev[prev.length - 1].speaker === speaker) {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            // Don't add extra spaces - transcription already includes whitespace
            updated[updated.length - 1] = {
              ...last,
              text: last.text + text,
            };
            return updated;
          }
          return [...prev, { speaker, text, timestamp: Date.now() }];
        });
        // Don't set currentQuestion from transcript - it comes from state_update
        break;
      }
      case 'turn_complete': {
        agentSpeakingRef.current = false;
        // Reveal any queued challenge data now that the AI finished speaking
        if (pendingChallengeRef.current) {
          console.log('[CI] Revealing challenge data after turn_complete:', pendingChallengeRef.current.title);
          const cd = pendingChallengeRef.current;
          pendingChallengeRef.current = null;
          setInterviewState((prev) => ({ ...prev, challenge_data: cd }));
        }
        // Let remaining queued audio play out naturally via onended chain
        break;
      }
      case 'interrupted': {
        // User barged in - clear the worklet ring buffer
        agentSpeakingRef.current = false;
        if (playbackWorkletRef.current) {
          playbackWorkletRef.current.port.postMessage({ command: 'endOfAudio' });
        }
        break;
      }
      case 'state_update': {
        if (data.current_question) {
          setCurrentQuestion(data.current_question);
        }
        if (data.challenge_data) {
          console.log('[CI] Challenge data received (queued):', data.challenge_data.title);
          // Queue challenge data - don't show until the AI finishes speaking
          pendingChallengeRef.current = data.challenge_data;
          // Apply everything else except challenge_data
          const { challenge_data: _cd, ...rest } = data;
          setInterviewState((prev) => ({ ...prev, ...rest }));
        } else {
          setInterviewState((prev) => ({ ...prev, ...data }));
        }
        break;
      }
      case 'report_ready': {
        setInterviewState((prev) => ({
          ...prev,
          type: 'report_ready',
          session_id: data.session_id,
        }));
        break;
      }
      case 'error': {
        setError(data.message || 'Unknown error from server');
        break;
      }
    }
  }, [enqueueAudio]);

  const { connect, disconnect, send, status } = useWebSocket({
    url: wsUrl,
    onMessage: handleMessage,
    onOpen: () => setError(null),
    onError: () => setError('Connection lost. Please start a new session.'),
    reconnect: false,  // Don't auto-reconnect - dead Gemini sessions can't resume
  });

  // Keep sendRef current for the audio processor callback
  useEffect(() => {
    sendRef.current = send;
  }, [send]);

  // --- Audio capture ---

  const monitorAudioLevel = useCallback(() => {
    if (!analyserRef.current) return;
    const analyser = analyserRef.current;
    const dataArray = new Uint8Array(analyser.frequencyBinCount);

    const tick = () => {
      analyser.getByteTimeDomainData(dataArray);
      let sum = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const v = (dataArray[i] - 128) / 128;
        sum += v * v;
      }
      const rms = Math.sqrt(sum / dataArray.length);
      setAudioLevel(Math.min(1, rms * 5));
      animFrameRef.current = requestAnimationFrame(tick);
    };
    tick();
  }, []);

  const start = useCallback(async () => {
    setError(null);

    try {
      // --- Playback setup (AudioWorklet at 24kHz) ---
      const playbackCtx = new AudioContext({ sampleRate: PLAYBACK_SAMPLE_RATE });
      playbackContextRef.current = playbackCtx;
      await playbackCtx.audioWorklet.addModule('/pcm-player-processor.js');
      const playerNode = new AudioWorkletNode(playbackCtx, 'pcm-player-processor');
      playerNode.connect(playbackCtx.destination);
      playbackWorkletRef.current = playerNode;

      // --- Capture setup (AudioWorklet at 16kHz) ---
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: 16000,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      streamRef.current = stream;

      const audioContext = new AudioContext({ sampleRate: 16000 });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(stream);
      sourceRef.current = source;

      const analyser = audioContext.createAnalyser();
      analyser.fftSize = 2048;
      analyserRef.current = analyser;
      source.connect(analyser);

      await audioContext.audioWorklet.addModule('/pcm-recorder-processor.js');
      const recorderNode = new AudioWorkletNode(audioContext, 'pcm-recorder-processor');
      recorderWorkletRef.current = recorderNode;

      recorderNode.port.onmessage = (e: MessageEvent) => {
        if (muteRef.current) return;
        const inputData = e.data as Float32Array;

        // Send all audio to Gemini including background noise.
        // Gemini's automatic_activity_detection handles VAD natively.
        // Only gate: while agent is speaking, require louder audio
        // to prevent echo/feedback from triggering barge-in.
        if (agentSpeakingRef.current) {
          let energy = 0;
          for (let i = 0; i < inputData.length; i++) {
            energy += inputData[i] * inputData[i];
          }
          const rms = Math.sqrt(energy / inputData.length);
          if (rms < 0.08) return;
        }

        const pcm = float32ToPCM16(inputData);
        const base64 = arrayBufferToBase64(pcm);
        sendRef.current({ type: 'audio', data: base64 });
      };

      source.connect(recorderNode);

      monitorAudioLevel();
      connect();
    } catch (err: any) {
      if (err.name === 'NotAllowedError') {
        setError('Microphone access denied. Please allow microphone access and try again.');
      } else {
        setError(`Failed to start audio: ${err.message}`);
      }
    }
  }, [connect, monitorAudioLevel]);

  // --- Screen Share ---
  const startScreenShare = useCallback(async (): Promise<MediaStream | null> => {
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
      screenStreamRef.current = stream;
      setIsScreenSharing(true);

      const video = document.createElement('video');
      video.srcObject = stream;
      video.muted = true;
      await video.play();

      const canvas = document.createElement('canvas');
      const ctx2d = canvas.getContext('2d')!;

      const captureFrame = () => {
        if (!screenStreamRef.current || !video.videoWidth) return;
        const scale = Math.min(1, 1280 / video.videoWidth);
        canvas.width = Math.round(video.videoWidth * scale);
        canvas.height = Math.round(video.videoHeight * scale);
        ctx2d.drawImage(video, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(
          (blob) => {
            if (!blob) return;
            const reader = new FileReader();
            reader.onloadend = () => {
              const base64 = (reader.result as string).split(',')[1];
              sendRef.current({ type: 'screen_frame', data: base64 });
            };
            reader.readAsDataURL(blob);
          },
          'image/jpeg',
          0.4
        );
      };
      // Also expose for manual capture
      (window as any).__captureScreenFrame = captureFrame;
      // Send frames every 20s - agent can see code but prompt forbids unsolicited comments
      screenIntervalRef.current = setInterval(captureFrame, 20000);

      // Stop sharing if user clicks browser's "Stop sharing" button
      stream.getVideoTracks()[0].onended = () => {
        stopScreenShare();
      };

      return stream;
    } catch (err: any) {
      if (err.name !== 'NotAllowedError') {
        setError(`Screen share failed: ${err.message}`);
      }
      return null;
    }
  }, []);

  const stopScreenShare = useCallback(() => {
    if (screenIntervalRef.current) {
      clearInterval(screenIntervalRef.current);
      screenIntervalRef.current = null;
    }
    if (screenStreamRef.current) {
      screenStreamRef.current.getTracks().forEach((t) => t.stop());
      screenStreamRef.current = null;
    }
    setIsScreenSharing(false);
  }, []);

  // --- Webcam ---
  const startWebcam = useCallback(async (): Promise<MediaStream | null> => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 320, height: 240, frameRate: 1 },
        audio: false,
      });
      webcamStreamRef.current = stream;
      setIsWebcamActive(true);

      const video = document.createElement('video');
      video.srcObject = stream;
      video.muted = true;
      await video.play();

      const canvas = document.createElement('canvas');
      const ctx2d = canvas.getContext('2d')!;

      webcamIntervalRef.current = setInterval(() => {
        if (!webcamStreamRef.current || !video.videoWidth) return;
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        ctx2d.drawImage(video, 0, 0);
        canvas.toBlob(
          (blob) => {
            if (!blob) return;
            const reader = new FileReader();
            reader.onloadend = () => {
              const base64 = (reader.result as string).split(',')[1];
              sendRef.current({ type: 'webcam_frame', data: base64 });
            };
            reader.readAsDataURL(blob);
          },
          'image/jpeg',
          0.5
        );
      }, 10000);

      return stream;
    } catch (err: any) {
      if (err.name !== 'NotAllowedError') {
        setError(`Webcam failed: ${err.message}`);
      }
      return null;
    }
  }, []);

  const stopWebcam = useCallback(() => {
    if (webcamIntervalRef.current) {
      clearInterval(webcamIntervalRef.current);
      webcamIntervalRef.current = null;
    }
    if (webcamStreamRef.current) {
      webcamStreamRef.current.getTracks().forEach((t) => t.stop());
      webcamStreamRef.current = null;
    }
    setIsWebcamActive(false);
  }, []);

  const stop = useCallback(() => {
    cancelAnimationFrame(animFrameRef.current);

    if (playbackWorkletRef.current) {
      playbackWorkletRef.current.port.postMessage({ command: 'endOfAudio' });
      playbackWorkletRef.current.disconnect();
      playbackWorkletRef.current = null;
    }
    if (recorderWorkletRef.current) {
      recorderWorkletRef.current.disconnect();
      recorderWorkletRef.current = null;
    }
    if (sourceRef.current) {
      sourceRef.current.disconnect();
      sourceRef.current = null;
    }
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    if (playbackContextRef.current) {
      playbackContextRef.current.close();
      playbackContextRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }

    stopScreenShare();
    stopWebcam();

    disconnect();
    setAudioLevel(0);
    setAgentAudioLevel(0);
  }, [disconnect, stopScreenShare, stopWebcam]);

  const toggleMute = useCallback(() => {
    muteRef.current = !muteRef.current;
    setIsMuted(muteRef.current);
  }, []);

  useEffect(() => {
    return () => {
      stop();
    };
  }, [stop]);

  return {
    start,
    stop,
    toggleMute,
    sendMessage: send,
    isMuted,
    connectionStatus: status,
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
  };
}
