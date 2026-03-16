interface ScoreCardProps {
  label: string;
  score: number;        // 1-10
  maxScore?: number;
  levelLabel: string;   // "Junior" | "Mid" | "Senior" | "Staff"
  feedback?: string;
  compact?: boolean;
}

function getLevelColor(level: string): string {
  switch (level.toLowerCase()) {
    case 'junior':
      return 'text-cyber-amber bg-cyber-amber/10 border-cyber-amber/30';
    case 'mid':
      return 'text-cyber-cyan bg-cyber-cyan/10 border-cyber-cyan/30';
    case 'senior':
      return 'text-cyber-green bg-cyber-green/10 border-cyber-green/30';
    case 'staff':
    case 'principal':
      return 'text-purple-400 bg-purple-400/10 border-purple-400/30';
    default:
      return 'text-cyber-text-dim bg-cyber-card border-cyber-border';
  }
}

function getProgressColor(score: number): string {
  if (score <= 3) return 'bg-cyber-amber';
  if (score <= 6) return 'bg-cyber-cyan';
  if (score <= 9) return 'bg-cyber-green';
  return 'bg-purple-400';
}

export default function ScoreCard({
  label,
  score,
  maxScore = 10,
  levelLabel,
  feedback,
  compact = false,
}: ScoreCardProps) {
  const pct = (score / maxScore) * 100;
  const levelColors = getLevelColor(levelLabel);
  const barColor = getProgressColor(score);

  if (compact) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-sm text-cyber-text-dim w-24 shrink-0">{label}</span>
        <div className="flex-1 h-1.5 bg-cyber-surface rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${barColor}`}
            style={{ width: `${pct}%` }}
          />
        </div>
        <span className="text-sm font-mono font-bold w-10 text-right">{score}/{maxScore}</span>
      </div>
    );
  }

  return (
    <div className="cyber-card space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h4 className="font-semibold text-sm">{label}</h4>
        </div>
        <div className="flex items-center gap-2">
          <span className="text-2xl font-bold font-mono">{score}</span>
          <span className="text-cyber-text-muted text-sm font-mono">/{maxScore}</span>
        </div>
      </div>

      {/* Level Badge */}
      <span className={`cyber-badge border ${levelColors}`}>
        {levelLabel}
      </span>

      {/* Progress Bar */}
      <div className="h-2 bg-cyber-surface rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-700 ease-out ${barColor}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Feedback */}
      {feedback && (
        <p className="text-xs text-cyber-text-dim leading-relaxed">{feedback}</p>
      )}
    </div>
  );
}
