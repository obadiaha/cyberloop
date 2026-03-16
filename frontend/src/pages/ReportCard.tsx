import { useState, useEffect } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Shield,
  Award,
  TrendingUp,
  TrendingDown,
  BookOpen,
  ChevronDown,
  ChevronRight,
  RotateCcw,
  Loader2,
  Users,
  MessageSquare,
  Target,
  BarChart3,
  Video,
} from 'lucide-react';
import DomainScore, { DomainScoreData } from '../components/DomainScore';

interface BehavioralScores {
  star_structure: number;        // 1-10
  i_vs_we_ratio: number;         // 0-1 (percentage)
  depth_under_pressure: number;  // 1-10
  story_bank: string;            // assessment text
}

interface BodyLanguageData {
  overall_presence: string;
  confidence_trajectory: string;
  observations: string[];
  impact_on_score: string;
}

interface ReportData {
  session_id: string;
  overall_level: string;
  technical_scores: DomainScoreData[];
  behavioral_scores?: BehavioralScores;
  strengths: string[];
  improvements: string[];
  study_recommendations: string[];
  transcript: { speaker: string; text: string; timestamp?: number }[];
  interview_duration?: number;
  company?: string;
  mode?: string;
  body_language?: BodyLanguageData;
}

function getLevelStyle(level: string): { bg: string; text: string; border: string } {
  switch (level.toLowerCase()) {
    case 'junior':
      return {
        bg: 'bg-cyber-amber/10',
        text: 'text-cyber-amber',
        border: 'border-cyber-amber/30',
      };
    case 'mid':
      return {
        bg: 'bg-cyber-cyan/10',
        text: 'text-cyber-cyan',
        border: 'border-cyber-cyan/30',
      };
    case 'senior':
      return {
        bg: 'bg-cyber-green/10',
        text: 'text-cyber-green',
        border: 'border-cyber-green/30',
      };
    case 'staff':
    case 'principal':
      return {
        bg: 'bg-purple-400/10',
        text: 'text-purple-400',
        border: 'border-purple-400/30',
      };
    default:
      return {
        bg: 'bg-cyber-card',
        text: 'text-cyber-text-dim',
        border: 'border-cyber-border',
      };
  }
}

// Mock reports for demo mode
const MOCK_BEHAVIORAL: ReportData = {
  session_id: 'demo-behavioral',
  overall_level: 'Senior',
  technical_scores: [
    {
      domain: 'Behavioral Assessment',
      score: 7.8,
      level: 'Senior',
      feedback:
        'Strong STAR structure across most answers. Demonstrated clear ownership of failures with specific remediation steps. Conflict resolution stories showed maturity and willingness to challenge senior engineers with data. Could improve on quantifying business impact of decisions.',
      missed_concepts: ['Cross-functional influence metrics', 'Stakeholder management at director level'],
      depth_reached: 3,
    },
  ],
  behavioral_scores: {
    star_structure: 8,
    i_vs_we_ratio: 0.72,
    depth_under_pressure: 7,
    story_bank: 'Strong story bank with 5 distinct scenarios spanning failure ownership, technical conflict, and cross-team influence. Used "I" language consistently when describing personal contributions. One story recycled across two questions. Prepare additional stories for prioritization under ambiguity.',
  },
  body_language: {
    overall_presence: 'confident',
    confidence_trajectory: 'improving',
    observations: [
      'Maintained steady eye contact throughout, especially when describing difficult decisions',
      'Natural hand gestures when explaining technical architecture choices',
      'Slight hesitation and gaze aversion when asked about personal contribution to project failure, recovered quickly with honest self-assessment',
      'Posture became more upright and engaged during depth probes, indicating comfort with pressure',
    ],
    impact_on_score: 'Strong physical presence reinforced verbal communication. Confidence trajectory improved across the interview, suggesting the candidate warms up well under pressure. Brief nervous moment during failure question was authentic, not evasive.',
  },
  strengths: [
    'Exceptional ownership of mistakes with specific, systemic fixes (detection testing framework, canary alerts)',
    'Clear "I vs we" separation when describing team outcomes versus personal contributions',
    'Maintained composure and provided deeper detail when pressed on uncomfortable topics',
  ],
  improvements: [
    'Quantify business impact more precisely. "Reduced false positives" is weaker than "Reduced false positives by 40%, saving 6 analyst-hours per week"',
    'Prepare a cross-functional influence story with measurable adoption metrics',
    'When describing failures, lead with the impact before the fix. Interviewers want to know you understand the blast radius.',
  ],
  study_recommendations: [
    'Practice STAR responses with a timer. Aim for 90-second Situation/Task and 2-minute Action/Result',
    'Record yourself answering behavioral questions and review body language',
    'Prepare a "story matrix" mapping 8-10 stories to common behavioral themes',
  ],
  transcript: [
    { speaker: 'agent', text: 'Tell me about a time you made a significant mistake at work. Not a small one. Something that had real impact.' },
    { speaker: 'candidate', text: 'At my last SOC role, I wrote a detection rule with a regex issue that suppressed real alerts for about 6 hours. We missed a phishing campaign...' },
    { speaker: 'agent', text: 'How quickly did you own the mistake versus trying to fix it quietly?' },
    { speaker: 'candidate', text: 'My first instinct was to fix it quietly. I had the regex fix ready in 20 minutes. But I realized the suppressed alerts meant we might have missed real incidents. So I walked into my manager\'s office and said I broke something...' },
    { speaker: 'agent', text: 'What process did you put in place to prevent this class of mistake?' },
    { speaker: 'candidate', text: 'I built a detection testing framework. Every new rule gets run against 30 days of historical data before going live. We also added a canary alert that fires every hour, so if a rule suppresses it, we know within 60 minutes instead of 6 hours. That framework is still running 2 years later.' },
  ],
  interview_duration: 1245,
  company: 'Amazon',
  mode: 'behavioral',
};

const MOCK_CODING: ReportData = {
  session_id: 'demo-coding',
  overall_level: 'Senior',
  technical_scores: [
    {
      domain: 'detection_engineering',
      score: 8.2,
      level: 'Senior',
      feedback:
        'Strong code reading skills with immediate identification of the dictionary counting gotcha. Log parsing solution used appropriate data structures (Counter) and demonstrated security-first thinking by identifying the full attack chain without prompting. KQL lateral movement query showed practical experience with real-world detection engineering.',
      missed_concepts: ['Time-window correlation in KQL', 'False positive reduction techniques'],
      depth_reached: 3,
    },
  ],
  strengths: [
    'Identified the complete attack narrative in the logs: brute force, recon, exfiltration, persistence, anti-forensics across 67 seconds',
    'Clean, Pythonic code using Counter and most_common() rather than manual dictionary loops',
    'Thought out loud consistently, explaining reasoning before writing code',
  ],
  improvements: [
    'Add error handling for malformed log entries. Production logs are messy and your parser assumed clean input.',
    'KQL query would benefit from a time-window join rather than simple where clauses. Lateral movement detection needs temporal correlation.',
    'Consider detection evasion when writing rules. The brute force pattern is obvious, but what if the attacker spaces attempts over hours?',
  ],
  study_recommendations: [
    'Practice KQL joins and time-window correlations in Microsoft Defender Advanced Hunting',
    'Build 5 log parsers from scratch using different log formats (JSON, CEF, syslog, W3C)',
    'Study MITRE ATT&CK T1021 (Remote Services) sub-techniques for lateral movement detection patterns',
  ],
  transcript: [
    { speaker: 'agent', text: 'Before we get into the main challenge, tell me what this Python snippet outputs and explain your reasoning.' },
    { speaker: 'candidate', text: 'The output is 2. The first assignment sets count to 1, but the second line calls .get() again which now returns 1, adds 1, making it 2.' },
    { speaker: 'agent', text: 'Write me a Python script that parses these access logs, counts requests per IP, and tell me which IP looks suspicious and why.' },
    { speaker: 'candidate', text: '10.0.0.33 is clearly suspicious. 8 requests total. Three failed logins, success on the 4th try, then immediately hits admin config, exports the user database, creates a backdoor account, and clears the logs. Five stages of the kill chain in 67 seconds.' },
  ],
  interview_duration: 987,
  company: 'Amazon',
  mode: 'coding',
};

const MOCK_TECHNICAL: ReportData = {
  session_id: 'demo-technical',
  overall_level: 'Mid-Level',
  technical_scores: [
    {
      domain: 'Incident Response',
      score: 6.5,
      level: 'Mid-Level',
      feedback:
        'Demonstrated solid foundational knowledge of IR frameworks and containment procedures. Correctly identified the need for evidence preservation before remediation. Could strengthen architectural thinking around IR automation and cross-team escalation protocols. Depth probes revealed gaps in memory forensics and cloud-specific IR procedures.',
      missed_concepts: ['Memory forensics with Volatility', 'Cloud IR - AWS GuardDuty/CloudTrail analysis', 'Executive communication during incidents'],
      depth_reached: 2,
    },
  ],
  strengths: [
    'Clear understanding of NIST IR framework phases with practical examples from SOC experience',
    'Correctly prioritized containment over eradication, citing evidence preservation requirements',
    'Named specific tools (Splunk, CrowdStrike, TheHive) with context on how they integrate into IR workflows',
  ],
  improvements: [
    'Deepen memory forensics knowledge. When asked about volatile evidence collection, response stayed at the tool-naming level without explaining what artifacts to look for or why order matters.',
    'Develop cloud IR expertise. Could not articulate how IR differs in AWS/Azure environments vs on-prem, which is increasingly critical for senior roles.',
    'Practice executive communication. When asked how to brief a CISO during an active incident, the answer was too technical. Focus on business impact, timeline, and decisions needed.',
  ],
  study_recommendations: [
    'Complete the SANS FOR508 (Advanced Incident Response) course for memory and timeline forensics',
    'Build a home lab with Velociraptor for remote triage and practice evidence collection workflows',
    'Study AWS IR: GuardDuty findings, CloudTrail log analysis, and S3 bucket forensics',
  ],
  transcript: [
    { speaker: 'agent', text: 'You get paged at 2 AM. A domain controller is making outbound C2 requests. Walk me through your first 30 minutes.' },
    { speaker: 'candidate', text: 'First, I would validate the alert in our SIEM to confirm it is not a false positive. Check the source IP, destination, and frequency. If confirmed, I would isolate the host from the network but keep it powered on to preserve volatile evidence...' },
    { speaker: 'agent', text: 'Good. The DNS logs show 6 hours of C2 contact with base64-encoded subdomains. What does that tell you about the exfiltration method?' },
    { speaker: 'candidate', text: 'That sounds like DNS tunneling. The base64 subdomains are likely encoding data being exfiltrated through DNS queries. I would look at the query volume and subdomain entropy to estimate how much data was extracted...' },
    { speaker: 'agent', text: 'How would you determine what data was exfiltrated if the attacker used encrypted DNS tunneling?' },
    { speaker: 'candidate', text: 'That is a tough one. I would start by looking at what the compromised host had access to. Check file access logs, database query logs if applicable. Also look at the volume of DNS traffic to estimate the size of exfiltration...' },
  ],
  interview_duration: 1102,
  company: 'generic',
  mode: 'technical',
};

// Select mock based on session ID prefix
function getMockReport(sessionId: string): ReportData {
  if (sessionId?.includes('coding')) return MOCK_CODING;
  if (sessionId?.includes('behavioral')) return MOCK_BEHAVIORAL;
  if (sessionId?.includes('technical')) return MOCK_TECHNICAL;
  return MOCK_TECHNICAL; // default
}

export default function ReportCard() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const [report, setReport] = useState<ReportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showTranscript, setShowTranscript] = useState(false);

  useEffect(() => {
    async function fetchReport() {
      try {
        const res = await fetch(`/api/report/${sessionId}`);
        if (res.ok) {
          const data = await res.json();
          setReport(data);
        } else {
          // Use mock data in development
          setReport(getMockReport(sessionId || ''));
        }
      } catch {
        // Fallback to mock data
        setReport(getMockReport(sessionId || ''));
      } finally {
        setLoading(false);
      }
    }
    fetchReport();
  }, [sessionId]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <Loader2 className="w-8 h-8 text-cyber-cyan animate-spin mx-auto" />
          <div>
            <p className="text-sm font-semibold">Generating Report Card</p>
            <p className="text-xs text-cyber-text-dim mt-1">
              Analyzing your interview performance...
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (error || !report) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-cyber-red">{error || 'Failed to load report'}</p>
          <button onClick={() => navigate('/')} className="cyber-btn-secondary">
            Back to Setup
          </button>
        </div>
      </div>
    );
  }

  const levelStyle = getLevelStyle(report.overall_level);

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-cyber-border px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center gap-3">
          <Link to="/" className="flex items-center gap-3 hover:opacity-80 transition-opacity">
            <Shield className="w-6 h-6 text-cyber-cyan" />
            <h1 className="text-lg font-semibold tracking-tight">CyberLoop</h1>
          </Link>
          <span className="text-cyber-text-muted text-sm font-mono ml-auto">
            Report Card
          </span>
        </div>
      </header>

      <main className="flex-1 px-6 py-8">
        <div className="max-w-4xl mx-auto space-y-8">
          {/* Overall Assessment */}
          <section className="cyber-card space-y-4">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                <Award className="w-6 h-6 text-cyber-cyan" />
                <div>
                  <h2 className="text-lg font-bold">Overall Assessment</h2>
                  {report.company && (
                    <p className="text-xs text-cyber-text-dim font-mono">
                      {report.company} Style &bull; {report.mode === 'coding' ? 'Live Coding' : report.mode === 'technical' ? 'Technical Depth' : 'Behavioral'}
                    </p>
                  )}
                </div>
              </div>
              <div
                className={`px-4 py-2 rounded-lg border text-lg font-bold font-mono ${levelStyle.bg} ${levelStyle.text} ${levelStyle.border}`}
              >
                {report.overall_level}
              </div>
            </div>

            {report.interview_duration && (
              <p className="text-xs text-cyber-text-muted font-mono">
                Duration: {Math.floor(report.interview_duration / 60)}m {report.interview_duration % 60}s
              </p>
            )}
          </section>

          {/* Technical Domain Scores */}
          {report.technical_scores.length > 0 && (
            <section className="space-y-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-cyber-cyan" />
                <h3 className="text-base font-semibold">Technical Domain Scores</h3>
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                {report.technical_scores.map((ds) => (
                  <DomainScore key={ds.domain} data={ds} />
                ))}

                {/* Interview Stats - fills blank space when only 1 domain */}
                {report.technical_scores.length < 2 && (
                  <div className="cyber-card space-y-4">
                    <div className="flex items-center gap-2 mb-1">
                      <Target className="w-4 h-4 text-cyber-cyan" />
                      <span className="text-sm font-semibold">Interview Stats</span>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                        <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Questions</div>
                        <div className="text-xl font-bold font-mono text-cyber-cyan">{report.transcript ? Math.ceil(report.transcript.length / 2) : '—'}</div>
                      </div>
                      <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                        <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Max Depth</div>
                        <div className="text-xl font-bold font-mono text-cyber-cyan">L{report.technical_scores[0]?.depth_reached || 1}</div>
                      </div>
                      <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                        <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Duration</div>
                        <div className="text-xl font-bold font-mono text-cyber-cyan">
                          {report.interview_duration ? `${Math.floor(report.interview_duration / 60)}m` : '—'}
                        </div>
                      </div>
                      <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                        <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Score</div>
                        <div className="text-xl font-bold font-mono text-cyber-green">{report.technical_scores[0]?.score || '—'}/10</div>
                      </div>
                    </div>

                    {/* Score Trajectory */}
                    <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                      <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Trajectory</div>
                      <div className="flex items-center gap-2">
                        <TrendingUp className="w-4 h-4 text-cyber-green" />
                        <span className="text-sm font-medium text-cyber-green">Improving</span>
                        <span className="text-xs text-cyber-text-dim ml-auto">Stronger answers in second half</span>
                      </div>
                    </div>

                    {/* Company Style */}
                    {report.company && (
                      <div className="bg-black/20 rounded-lg px-3 py-2 border border-white/5">
                        <div className="text-[10px] text-cyber-text-dim font-mono uppercase mb-1">Interview Style</div>
                        <div className="text-sm font-medium">{report.company} {report.mode === 'behavioral' ? 'Bar Raiser' : report.mode === 'coding' ? 'Live Coding' : 'Technical Deep Dive'}</div>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </section>
          )}

          {/* Behavioral Scores */}
          {report.behavioral_scores && (
            <section className="space-y-4">
              <div className="flex items-center gap-2">
                <Users className="w-5 h-5 text-cyber-cyan" />
                <h3 className="text-base font-semibold">Behavioral Assessment</h3>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {/* STAR Structure */}
                <div className="cyber-card space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <Target className="w-4 h-4 text-cyber-text-dim" />
                      <span className="text-sm font-medium">STAR Structure</span>
                    </div>
                    <span className="text-xl font-bold font-mono">
                      {report.behavioral_scores.star_structure}/10
                    </span>
                  </div>
                  <div className="h-2 bg-cyber-surface rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-cyber-cyan transition-all duration-700"
                      style={{
                        width: `${(report.behavioral_scores.star_structure / 10) * 100}%`,
                      }}
                    />
                  </div>
                </div>

                {/* I vs We Ratio */}
                <div className="cyber-card space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <MessageSquare className="w-4 h-4 text-cyber-text-dim" />
                      <span className="text-sm font-medium">I-vs-We Ratio</span>
                    </div>
                    <span className="text-xl font-bold font-mono">
                      {Math.round(report.behavioral_scores.i_vs_we_ratio * 100)}%
                    </span>
                  </div>
                  <div className="h-2 bg-cyber-surface rounded-full overflow-hidden relative">
                    <div
                      className={`h-full rounded-full transition-all duration-700 ${
                        report.behavioral_scores.i_vs_we_ratio >= 0.6
                          ? 'bg-cyber-green'
                          : 'bg-cyber-amber'
                      }`}
                      style={{
                        width: `${report.behavioral_scores.i_vs_we_ratio * 100}%`,
                      }}
                    />
                  </div>
                  <p className="text-[10px] text-cyber-text-muted font-mono">
                    Target: &gt;60% "I" statements for senior roles
                  </p>
                </div>

                {/* Depth Under Pressure */}
                <div className="cyber-card space-y-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <TrendingUp className="w-4 h-4 text-cyber-text-dim" />
                      <span className="text-sm font-medium">Depth Under Pressure</span>
                    </div>
                    <span className="text-xl font-bold font-mono">
                      {report.behavioral_scores.depth_under_pressure}/10
                    </span>
                  </div>
                  <div className="h-2 bg-cyber-surface rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-cyber-green transition-all duration-700"
                      style={{
                        width: `${(report.behavioral_scores.depth_under_pressure / 10) * 100}%`,
                      }}
                    />
                  </div>
                </div>

                {/* Story Bank */}
                <div className="cyber-card space-y-2">
                  <div className="flex items-center gap-2">
                    <BookOpen className="w-4 h-4 text-cyber-text-dim" />
                    <span className="text-sm font-medium">Story Bank</span>
                  </div>
                  <p className="text-xs text-cyber-text-dim leading-relaxed">
                    {report.behavioral_scores.story_bank}
                  </p>
                </div>
              </div>
            </section>
          )}

          {/* Performance Analysis */}
          <section className="space-y-4">
            <div className="flex items-center gap-2">
              <Award className="w-5 h-5 text-cyber-cyan" />
              <h3 className="text-base font-semibold">Performance Analysis</h3>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              {/* Strengths */}
              <div className="cyber-card space-y-3">
                <div className="flex items-center gap-2">
                  <TrendingUp className="w-4 h-4 text-cyber-green" />
                  <h4 className="text-sm font-semibold text-cyber-green">Top Strengths</h4>
                </div>
                <ol className="space-y-2">
                  {report.strengths.map((s, i) => (
                    <li key={i} className="flex gap-2 text-xs text-cyber-text-dim leading-relaxed">
                      <span className="text-cyber-green font-mono font-bold shrink-0">
                        {i + 1}.
                      </span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>

              {/* Areas to Improve */}
              <div className="cyber-card space-y-3">
                <div className="flex items-center gap-2">
                  <TrendingDown className="w-4 h-4 text-cyber-amber" />
                  <h4 className="text-sm font-semibold text-cyber-amber">Areas to Improve</h4>
                </div>
                <ol className="space-y-2">
                  {report.improvements.map((s, i) => (
                    <li key={i} className="flex gap-2 text-xs text-cyber-text-dim leading-relaxed">
                      <span className="text-cyber-amber font-mono font-bold shrink-0">
                        {i + 1}.
                      </span>
                      {s}
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          </section>

          {/* Body Language Analysis (behavioral mode with webcam) */}
          {report.body_language && (
            <section className="space-y-4">
              <div>
                <div className="flex items-center gap-2">
                  <Video className="w-5 h-5 text-cyber-cyan" />
                  <h3 className="text-base font-semibold">Body Language & Presence</h3>
                </div>
                <p className="text-xs text-cyber-text-muted mt-1">
                  Analyzed from webcam frames captured every 10 seconds during the interview. Gemini Vision evaluates posture, eye contact, confidence signals, and demeanor changes across the session. This section only appears in behavioral interviews with webcam enabled.
                </p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                {/* Overall Presence */}
                <div className="cyber-card space-y-2">
                  <span className="text-xs text-cyber-text-dim font-mono uppercase">Presence</span>
                  <div className={`text-lg font-bold ${
                    report.body_language.overall_presence === 'confident' ? 'text-cyber-green' :
                    report.body_language.overall_presence === 'nervous' ? 'text-cyber-amber' :
                    'text-cyber-cyan'
                  }`}>
                    {report.body_language.overall_presence?.charAt(0).toUpperCase() + report.body_language.overall_presence?.slice(1)}
                  </div>
                </div>

                {/* Confidence Trajectory */}
                <div className="cyber-card space-y-2">
                  <span className="text-xs text-cyber-text-dim font-mono uppercase">Trajectory</span>
                  <div className={`text-lg font-bold ${
                    report.body_language.confidence_trajectory === 'improving' ? 'text-cyber-green' :
                    report.body_language.confidence_trajectory === 'declining' ? 'text-cyber-red' :
                    'text-cyber-cyan'
                  }`}>
                    {report.body_language.confidence_trajectory?.charAt(0).toUpperCase() + report.body_language.confidence_trajectory?.slice(1)}
                  </div>
                </div>

                {/* Impact */}
                <div className="cyber-card space-y-2">
                  <span className="text-xs text-cyber-text-dim font-mono uppercase">Score Impact</span>
                  <p className="text-xs text-cyber-text-dim leading-relaxed">
                    {report.body_language.impact_on_score}
                  </p>
                </div>
              </div>

              {/* Observations */}
              {report.body_language.observations && report.body_language.observations.length > 0 && (
                <div className="cyber-card space-y-2">
                  <span className="text-xs text-cyber-text-dim font-mono uppercase">Observations</span>
                  <ul className="space-y-1">
                    {report.body_language.observations.map((obs, i) => (
                      <li key={i} className="flex gap-2 text-xs text-cyber-text-dim leading-relaxed">
                        <span className="text-cyber-cyan shrink-0">•</span>
                        {obs}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </section>
          )}

          {/* Study Recommendations */}
          {report.study_recommendations.length > 0 && (
            <section className="cyber-card space-y-3">
              <div className="flex items-center gap-2">
                <BookOpen className="w-4 h-4 text-cyber-cyan" />
                <h4 className="text-sm font-semibold">Study Recommendations</h4>
              </div>
              <ul className="space-y-2">
                {report.study_recommendations.map((rec, i) => (
                  <li key={i} className="flex gap-2 text-xs text-cyber-text-dim leading-relaxed">
                    <span className="text-cyber-cyan shrink-0">&#x25B8;</span>
                    {rec}
                  </li>
                ))}
              </ul>
            </section>
          )}

          {/* Transcript Accordion */}
          <section className="cyber-card">
            <button
              onClick={() => setShowTranscript(!showTranscript)}
              className="w-full flex items-center justify-between text-left"
            >
              <div className="flex items-center gap-2">
                <MessageSquare className="w-4 h-4 text-cyber-text-dim" />
                <h4 className="text-sm font-semibold">Full Transcript</h4>
                <span className="text-xs text-cyber-text-muted font-mono">
                  ({report.transcript.length} exchanges)
                </span>
              </div>
              {showTranscript ? (
                <ChevronDown className="w-4 h-4 text-cyber-text-dim" />
              ) : (
                <ChevronRight className="w-4 h-4 text-cyber-text-dim" />
              )}
            </button>

            {showTranscript && (
              <div className="mt-4 space-y-3 max-h-96 overflow-y-auto border-t border-cyber-border pt-4">
                {report.transcript.map((entry, i) => (
                  <div key={i} className="space-y-1">
                    <span
                      className={`text-[10px] font-mono uppercase tracking-widest ${
                        entry.speaker === 'agent'
                          ? 'text-cyber-cyan-dim'
                          : 'text-cyber-text-muted'
                      }`}
                    >
                      {entry.speaker === 'agent' ? 'Interviewer' : 'Candidate'}
                    </span>
                    <p
                      className={`text-xs leading-relaxed ${
                        entry.speaker === 'agent'
                          ? 'text-cyber-cyan/80'
                          : 'text-cyber-text-dim'
                      }`}
                    >
                      {entry.text}
                    </p>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Actions */}
          <div className="flex justify-center pt-4 pb-8">
            <button
              onClick={() => navigate('/')}
              className="cyber-btn-primary flex items-center gap-2 text-base"
            >
              <RotateCcw className="w-4 h-4" />
              Start New Interview
            </button>
          </div>
        </div>
      </main>
    </div>
  );
}
