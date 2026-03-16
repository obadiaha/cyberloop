import ScoreCard from './ScoreCard';
import { AlertTriangle } from 'lucide-react';

export interface DomainScoreData {
  domain: string;
  score: number;
  level: string;
  feedback: string;
  missed_concepts?: string[];
  depth_reached?: number;
}

interface DomainScoreProps {
  data: DomainScoreData;
}

function formatDomainName(domain: string): string {
  return domain
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');
}

export default function DomainScore({ data }: DomainScoreProps) {
  return (
    <div className="space-y-2">
      <ScoreCard
        label={formatDomainName(data.domain)}
        score={data.score}
        levelLabel={data.level}
        feedback={data.feedback}
      />

      {/* Depth Reached */}
      {data.depth_reached && (
        <div className="px-5 py-2 bg-cyber-surface/50 rounded-b-lg border border-t-0 border-cyber-border">
          <div className="flex items-center gap-2 text-xs text-cyber-text-dim font-mono">
            <span>Depth reached:</span>
            <div className="flex gap-1">
              {[1, 2, 3, 4].map((level) => (
                <div
                  key={level}
                  className={`w-6 h-1.5 rounded-full ${
                    level <= data.depth_reached!
                      ? 'bg-cyber-cyan'
                      : 'bg-cyber-border'
                  }`}
                />
              ))}
            </div>
            <span>L{data.depth_reached}</span>
          </div>
        </div>
      )}

      {/* Missed Concepts */}
      {data.missed_concepts && data.missed_concepts.length > 0 && (
        <div className="px-5 py-3 bg-cyber-amber/5 border border-cyber-amber/15 rounded-lg">
          <div className="flex items-center gap-2 mb-2">
            <AlertTriangle className="w-3.5 h-3.5 text-cyber-amber" />
            <span className="text-xs font-medium text-cyber-amber">
              Missed Concepts
            </span>
          </div>
          <ul className="space-y-1">
            {data.missed_concepts.map((concept, i) => (
              <li key={i} className="text-xs text-cyber-text-dim pl-5">
                <span className="text-cyber-amber mr-1.5">&#x2022;</span>
                {concept}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
