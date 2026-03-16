import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import {
  Shield,
  Building2,
  Rocket,
  Globe,
  ChevronRight,
  Brain,
  Users,
  Crosshair,
  Search,
  Monitor,
  FileSearch,
  Radio,
  Code2,
} from 'lucide-react';

type Company = 'amazon' | 'spacex' | 'generic';
type Mode = 'technical' | 'behavioral' | 'coding';
type Domain =
  | 'incident_response'
  | 'detection_engineering'
  | 'soc_operations'
  | 'digital_forensics'
  | 'threat_intelligence';
type BehavioralFramework = 'amazon_lps' | 'custom';

const COMPANIES: { id: Company; name: string; desc: string; icon: typeof Building2 }[] = [
  { id: 'amazon', name: 'Amazon', desc: 'Bar raiser style. Deep LP probing.', icon: Building2 },
  { id: 'spacex', name: 'SpaceX', desc: 'First principles. Systems thinking.', icon: Rocket },
  { id: 'generic', name: 'Generic', desc: 'Professional structured interview.', icon: Globe },
];

const DOMAINS: { id: Domain; name: string; icon: typeof Shield }[] = [
  { id: 'incident_response', name: 'Incident Response', icon: Crosshair },
  { id: 'detection_engineering', name: 'Detection Engineering', icon: Search },
  { id: 'soc_operations', name: 'SOC Operations', icon: Monitor },
  { id: 'digital_forensics', name: 'Digital Forensics', icon: FileSearch },
  { id: 'threat_intelligence', name: 'Threat Intelligence', icon: Radio },
];

export default function Setup() {
  const navigate = useNavigate();
  const [company, setCompany] = useState<Company>('generic');
  const [mode, setMode] = useState<Mode>('technical');
  const [domains, setDomains] = useState<Domain[]>(['incident_response']);
  const [behavioralFramework, setBehavioralFramework] =
    useState<BehavioralFramework>('amazon_lps');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const toggleDomain = (d: Domain) => {
    setDomains((prev) =>
      prev.includes(d) ? prev.filter((x) => x !== d) : [...prev, d]
    );
  };

  const canStart =
    mode === 'behavioral' || mode === 'coding' || (mode === 'technical' && domains.length > 0);

  // Demo mode: check URL param
  const isDemo = new URLSearchParams(window.location.search).get('demo') === 'true';

  const startInterview = async () => {
    if (!canStart) return;
    setLoading(true);
    setError(null);

    try {
      const body: Record<string, unknown> = {
        company,
        level: 'mid',
        mode,
        domains: mode === 'technical' ? domains : mode === 'coding' ? ['detection_engineering'] : [],
        behavioral_framework: mode === 'behavioral' ? behavioralFramework : null,
      };
      if (isDemo) body.demo = true;

      const res = await fetch('/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        throw new Error(`Server error: ${res.status}`);
      }

      const data = await res.json();
      navigate(`/interview/${data.session_id}`);
    } catch (err: any) {
      setError(err.message || 'Failed to create session');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-cyber-border px-6 py-4">
        <div className="max-w-5xl mx-auto flex items-center gap-3">
          <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
            <Shield className="w-6 h-6 text-cyber-cyan" />
            <h1 className="text-lg font-semibold tracking-tight">
              CyberLoop
            </h1>
          </Link>
          {isDemo && (
            <span className="ml-2 px-2 py-0.5 text-[10px] font-mono font-bold uppercase tracking-wider bg-cyber-amber/20 text-cyber-amber border border-cyber-amber/30 rounded">
              Demo Mode
            </span>
          )}
          <span className="text-cyber-text-muted text-sm font-mono ml-auto">
            v0.1
          </span>
        </div>
      </header>

      <main className="flex-1 px-6 py-10">
        <div className="max-w-5xl mx-auto space-y-10">
          {/* Title */}
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              Configure Your Interview
            </h2>
            <p className="text-cyber-text-dim mt-1">
              Set up a mock interview tailored to your target role and company.
            </p>
          </div>

          {/* Company Style */}
          <section className="space-y-3">
            <label className="text-sm font-medium text-cyber-text-dim uppercase tracking-wider">
              Company Style
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              {COMPANIES.map((c) => {
                const Icon = c.icon;
                const selected = company === c.id;
                return (
                  <button
                    key={c.id}
                    onClick={() => setCompany(c.id)}
                    className={selected ? 'cyber-card-selected' : 'cyber-card-interactive'}
                  >
                    <div className="flex items-start gap-3">
                      <Icon
                        className={`w-5 h-5 mt-0.5 ${
                          selected ? 'text-cyber-cyan' : 'text-cyber-text-muted'
                        }`}
                      />
                      <div className="text-left">
                        <div className="font-semibold text-sm">{c.name}</div>
                        <div className="text-xs text-cyber-text-dim mt-0.5">
                          {c.desc}
                        </div>
                      </div>
                    </div>
                  </button>
                );
              })}
            </div>
          </section>

          {/* Interview Mode */}
          <section className="space-y-3">
            <label className="text-sm font-medium text-cyber-text-dim uppercase tracking-wider">
              Interview Mode
            </label>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <button
                onClick={() => setMode('technical')}
                className={
                  mode === 'technical' ? 'cyber-card-selected' : 'cyber-card-interactive'
                }
              >
                <div className="flex items-center gap-3">
                  <Brain
                    className={`w-5 h-5 ${
                      mode === 'technical' ? 'text-cyber-cyan' : 'text-cyber-text-muted'
                    }`}
                  />
                  <div className="text-left">
                    <div className="font-semibold text-sm">Technical Depth</div>
                    <div className="text-xs text-cyber-text-dim mt-0.5">
                      Domain knowledge, depth ladder, architecture
                    </div>
                  </div>
                </div>
              </button>
              <button
                onClick={() => setMode('behavioral')}
                className={
                  mode === 'behavioral' ? 'cyber-card-selected' : 'cyber-card-interactive'
                }
              >
                <div className="flex items-center gap-3">
                  <Users
                    className={`w-5 h-5 ${
                      mode === 'behavioral' ? 'text-cyber-cyan' : 'text-cyber-text-muted'
                    }`}
                  />
                  <div className="text-left">
                    <div className="font-semibold text-sm">Behavioral</div>
                    <div className="text-xs text-cyber-text-dim mt-0.5">
                      STAR stories, leadership principles, soft skills
                    </div>
                  </div>
                </div>
              </button>
              <button
                onClick={() => setMode('coding')}
                className={
                  mode === 'coding' ? 'cyber-card-selected' : 'cyber-card-interactive'
                }
              >
                <div className="flex items-center gap-3">
                  <Code2
                    className={`w-5 h-5 ${
                      mode === 'coding' ? 'text-cyber-cyan' : 'text-cyber-text-muted'
                    }`}
                  />
                  <div className="text-left">
                    <div className="font-semibold text-sm">Hands-On Coding</div>
                    <div className="text-xs text-cyber-text-dim mt-0.5">
                      Log analysis, query writing, live screen sharing
                    </div>
                  </div>
                </div>
              </button>
            </div>
          </section>

          {/* Domain Selection (Technical / Coding) */}
          {mode === 'technical' && (
            <section className="space-y-3">
              <label className="text-sm font-medium text-cyber-text-dim uppercase tracking-wider">
                Domains{' '}
                <span className="text-cyber-text-muted font-normal normal-case">
                  (select one or more)
                </span>
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                {DOMAINS.map((d) => {
                  const Icon = d.icon;
                  const selected = domains.includes(d.id);
                  return (
                    <button
                      key={d.id}
                      onClick={() => toggleDomain(d.id)}
                      className={selected ? 'cyber-card-selected' : 'cyber-card-interactive'}
                    >
                      <div className="flex items-center gap-3">
                        <Icon
                          className={`w-5 h-5 ${
                            selected ? 'text-cyber-cyan' : 'text-cyber-text-muted'
                          }`}
                        />
                        <span className="text-sm font-medium">{d.name}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
              {domains.length === 0 && (
                <p className="text-xs text-cyber-red">
                  Select at least one domain to continue.
                </p>
              )}
            </section>
          )}

          {/* Behavioral Framework */}
          {mode === 'behavioral' && (
            <section className="space-y-3">
              <label className="text-sm font-medium text-cyber-text-dim uppercase tracking-wider">
                Framework
              </label>
              <div className="grid grid-cols-2 gap-3">
                <button
                  onClick={() => setBehavioralFramework('amazon_lps')}
                  className={
                    behavioralFramework === 'amazon_lps'
                      ? 'cyber-card-selected'
                      : 'cyber-card-interactive'
                  }
                >
                  <div className="text-center">
                    <div className="font-semibold text-sm">Amazon LPs</div>
                    <div className="text-xs text-cyber-text-dim mt-0.5">
                      16 Leadership Principles
                    </div>
                  </div>
                </button>
                <button
                  onClick={() => setBehavioralFramework('custom')}
                  className={
                    behavioralFramework === 'custom'
                      ? 'cyber-card-selected'
                      : 'cyber-card-interactive'
                  }
                >
                  <div className="text-center">
                    <div className="font-semibold text-sm">Custom</div>
                    <div className="text-xs text-cyber-text-dim mt-0.5">
                      General behavioral questions
                    </div>
                  </div>
                </button>
              </div>
            </section>
          )}

          {/* Scoring Rubric Preview */}
          <section className="space-y-3">
            <label className="text-sm font-medium text-cyber-text-dim uppercase tracking-wider">
              How You'll Be Scored
            </label>
            {mode === 'coding' ? (
              <div className="cyber-card border-cyber-border bg-cyber-bg/50">
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Approach</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-cyan rounded-full" style={{ width: '30%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">30%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Plan before coding. Break down the problem. Ask clarifying questions.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Code Quality</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-green rounded-full" style={{ width: '25%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">25%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Correct syntax, clean structure, appropriate data structures.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Security Insight</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-yellow-400 rounded-full" style={{ width: '25%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">25%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Interpret results. Identify the attack. Explain the threat chain.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Communication</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-purple-400 rounded-full" style={{ width: '10%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">10%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Think out loud. Explain your reasoning as you work.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Speed</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-orange-400 rounded-full" style={{ width: '10%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">10%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Reasonable pace. Efficient approach. Don't freeze.</p>
                </div>
              </div>
            ) : mode === 'behavioral' ? (
              <div className="cyber-card border-cyber-border bg-cyber-bg/50">
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Story Depth</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-cyan rounded-full" style={{ width: '40%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">40%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Specific situations, named projects, real details that hold up under probing.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Specificity</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-green rounded-full" style={{ width: '30%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">30%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Quantified results. "I" not "we". Metrics and business impact.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Communication</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-purple-400 rounded-full" style={{ width: '20%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">20%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">STAR structure. Concise yet complete. Clear narrative arc.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Overall</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-yellow-400 rounded-full" style={{ width: '10%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">10%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Holistic impression. Ownership, lessons learned, self-awareness.</p>
                </div>
              </div>
            ) : (
              <div className="cyber-card border-cyber-border bg-cyber-bg/50">
                <div className="space-y-2.5">
                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Technical Depth</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-cyan rounded-full" style={{ width: '40%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">40%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Explain WHY, not just WHAT. Underlying principles and architecture.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Specificity</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-cyber-green rounded-full" style={{ width: '30%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">30%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Real tool names, vendor experience, concrete examples and numbers.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Communication</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-purple-400 rounded-full" style={{ width: '20%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">20%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Clear, organized, concise answers. Structured thinking.</p>

                  <div className="flex items-center justify-between">
                    <span className="text-sm text-cyber-text">Overall</span>
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-cyber-border rounded-full overflow-hidden">
                        <div className="h-full bg-yellow-400 rounded-full" style={{ width: '10%' }} />
                      </div>
                      <span className="text-xs text-cyber-text-dim font-mono w-8">10%</span>
                    </div>
                  </div>
                  <p className="text-xs text-cyber-text-dim pl-0">Holistic impression. Depth of knowledge, experience signal.</p>
                </div>
              </div>
            )}
          </section>

          {/* Error */}
          {error && (
            <div className="bg-cyber-red/10 border border-cyber-red/30 rounded-lg px-4 py-3 text-sm text-cyber-red">
              {error}
            </div>
          )}

          {/* Start Button */}
          <div className="pt-4">
            <button
              onClick={startInterview}
              disabled={!canStart || loading}
              className="cyber-btn-primary w-full sm:w-auto flex items-center justify-center gap-2 text-base"
            >
              {loading ? (
                <span className="animate-pulse">Initializing session...</span>
              ) : (
                <>
                  Start Interview
                  <ChevronRight className="w-4 h-4" />
                </>
              )}
            </button>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-cyber-border px-6 py-3">
        <div className="max-w-5xl mx-auto text-center text-xs text-cyber-text-muted font-mono">
          Practice with an interviewer that never goes easy on you.
        </div>
      </footer>
    </div>
  );
}
