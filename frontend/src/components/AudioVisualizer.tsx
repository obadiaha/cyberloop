import { useRef, useEffect, useCallback } from 'react';

interface AudioVisualizerProps {
  audioLevel: number;       // 0-1: microphone input level
  agentAudioLevel: number;  // 0-1: agent playback level
  isActive: boolean;
  width?: number;
  height?: number;
}

export default function AudioVisualizer({
  audioLevel,
  agentAudioLevel,
  isActive,
  width = 600,
  height = 200,
}: AudioVisualizerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const animFrameRef = useRef<number>(0);
  const phaseRef = useRef(0);
  const smoothUserLevel = useRef(0);
  const smoothAgentLevel = useRef(0);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.scale(dpr, dpr);

    // smooth the levels
    smoothUserLevel.current += (audioLevel - smoothUserLevel.current) * 0.15;
    smoothAgentLevel.current += (agentAudioLevel - smoothAgentLevel.current) * 0.15;

    const userLvl = smoothUserLevel.current;
    const agentLvl = smoothAgentLevel.current;
    const combinedLevel = Math.max(userLvl, agentLvl);

    phaseRef.current += 0.03;

    // clear
    ctx.clearRect(0, 0, width, height);

    const centerY = height / 2;
    const barCount = 64;
    const barWidth = (width / barCount) * 0.6;
    const gap = width / barCount;

    // draw bars
    for (let i = 0; i < barCount; i++) {
      const x = i * gap + gap * 0.2;

      // frequency-like distribution
      const normalizedPos = i / barCount;
      const distFromCenter = Math.abs(normalizedPos - 0.5) * 2;
      const envelope = 1 - distFromCenter * distFromCenter;

      // multiple wave layers
      const wave1 = Math.sin(phaseRef.current * 2 + i * 0.3) * 0.5 + 0.5;
      const wave2 = Math.sin(phaseRef.current * 3.7 + i * 0.15) * 0.3 + 0.5;
      const wave3 = Math.sin(phaseRef.current * 1.3 + i * 0.5) * 0.2 + 0.5;

      const waveComposite = (wave1 + wave2 + wave3) / 3;

      const baseHeight = isActive ? 4 : 2;
      const activeHeight = combinedLevel * height * 0.7 * envelope * waveComposite;
      const barHeight = baseHeight + activeHeight;

      // color: blend between cyan (agent) and green (user)
      const agentRatio = agentLvl > 0.01 ? agentLvl / (agentLvl + userLvl + 0.001) : 0;
      const r = 0;
      const g = Math.round(229 + (255 - 229) * (1 - agentRatio));
      const b = Math.round(255 * agentRatio + 136 * (1 - agentRatio));
      const alpha = isActive ? 0.4 + combinedLevel * 0.6 : 0.15;

      ctx.fillStyle = `rgba(${r}, ${g}, ${b}, ${alpha})`;

      // draw mirrored bar
      const halfBar = barHeight / 2;
      ctx.fillRect(x, centerY - halfBar, barWidth, barHeight);

      // glow on high levels
      if (combinedLevel > 0.3 && isActive) {
        ctx.shadowColor = `rgba(${r}, ${g}, ${b}, 0.3)`;
        ctx.shadowBlur = 8;
        ctx.fillRect(x, centerY - halfBar, barWidth, barHeight);
        ctx.shadowBlur = 0;
      }
    }

    // center line
    ctx.strokeStyle = isActive
      ? `rgba(0, 229, 255, ${0.1 + combinedLevel * 0.15})`
      : 'rgba(0, 229, 255, 0.05)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, centerY);
    ctx.lineTo(width, centerY);
    ctx.stroke();

    animFrameRef.current = requestAnimationFrame(draw);
  }, [audioLevel, agentAudioLevel, isActive, width, height]);

  useEffect(() => {
    animFrameRef.current = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(animFrameRef.current);
  }, [draw]);

  return (
    <div className="relative">
      <canvas
        ref={canvasRef}
        style={{ width, height }}
        className="rounded-lg"
      />
      {!isActive && (
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-cyber-text-muted text-sm font-mono">
            Waiting for audio...
          </span>
        </div>
      )}
    </div>
  );
}
