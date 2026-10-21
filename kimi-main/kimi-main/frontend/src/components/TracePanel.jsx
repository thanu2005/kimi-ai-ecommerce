import { useState } from 'react';
import { ChevronDownIcon, ChevronRightIcon } from 'lucide-react';

/* ── Constants ──────────────────────────────────────────────────────────── */

const DOMAIN_COLORS = {
  sales:     'bg-blue-100 text-blue-700 border-blue-200',
  inventory: 'bg-amber-100 text-amber-700 border-amber-200',
  marketing: 'bg-purple-100 text-purple-700 border-purple-200',
  support:   'bg-green-100 text-green-700 border-green-200',
};

const DOMAIN_DOT = {
  sales:     'bg-blue-500',
  inventory: 'bg-amber-500',
  marketing: 'bg-purple-500',
  support:   'bg-green-500',
};

// GIF URLs keyed by state — direct CDN links
const GIFS = {
  starting:  'https://media1.tenor.com/m/S-zb95RXbF8AAAAd/here-we-go-jk-simmons.gif',
  working:   'https://media1.tenor.com/m/AgRKMMEZ3c4AAAAd/ducklash-whiplash.gif',
  rejected:  'https://media1.tenor.com/m/QDdMxaJsZWUAAAAd/not-quite-my-tempo-jk-simmons.gif',
  hitl:      'https://media1.tenor.com/m/yTd8nh47-8IAAAAd/not-quite-my-tempo.gif',
  approved:  'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaHpibnpiMTMzY2R6eDI1d2gzaW13OWxnbDdmYnVid291djdtOTd0ZiZlcD12MV9naWZzX3NlYXJjaCZjdD1n/e7N9oNgRAEjII/giphy.gif',
  end:       'https://media1.tenor.com/m/_p2KSDzDQFwAAAAd/not-happy-jk-simmons.gif',
  off_topic: 'https://media.giphy.com/media/v1.Y2lkPWVjZjA1ZTQ3cXM2M2hvNnBzZm1kdmp1bmhid3FjZWQ5cjZzeTNmeHg3ZXRtMGNjdyZlcD12MV9naWZzX3NlYXJjaCZjdD1n/F4FhaevJVLJml91lln/giphy.gif',
};

/* ── Helpers ─────────────────────────────────────────────────────────────── */

function resolveGifState(trace) {
  const {
    selectedAgents = [],
    formatterDone   = false,
    isStreaming     = false,
    wasRejected     = false,
    wasApproved     = false,
    offTopic        = false,
  } = trace;

  if (offTopic)                      return 'off_topic';
  if (wasRejected)                   return 'rejected';
  if (wasApproved)                   return 'approved';
  if (!isStreaming && formatterDone) return 'end';
  if (!isStreaming)                  return 'hitl';
  if (selectedAgents.length === 0)  return 'starting';
  return 'working';
}

function resolveStepLabel(trace) {
  const {
    selectedAgents    = [],
    domainFindings    = {},
    retrospectionDone = false,
    synthesizerDone   = false,
    formatterDone     = false,
    isStreaming       = false,
    wasRejected       = false,
    wasApproved       = false,
    offTopic          = false,
  } = trace;

  const supervisorDone = selectedAgents.length > 0;
  const scanDone = (
    Object.keys(domainFindings).length === selectedAgents.length &&
    selectedAgents.length > 0
  );

  if (offTopic)                      return 'Not My Department';
  if (wasRejected)                   return 'Refining Recommendations';
  if (wasApproved)                   return 'Executing Approved Actions';
  if (!isStreaming && formatterDone)  return 'Analysis Complete';
  if (!isStreaming)                   return 'Awaiting Your Approval';
  if (!supervisorDone)              return 'Starting Analysis';
  if (!scanDone)                    return 'Scanning Domains';
  if (!retrospectionDone)           return 'Cross-Agent Reflection';
  if (!synthesizerDone)             return 'Synthesizing Report';
  return 'Formatting Response';
}

/* ── Sub-components (standard mode) ─────────────────────────────────────── */

function AgentChip({ agent }) {
  const cls = DOMAIN_COLORS[agent] ?? 'bg-surface-container text-on-surface border-outline-variant';
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-xs font-medium capitalize ${cls}`}>
      {agent}
    </span>
  );
}

function DomainFindingRow({ domain, findings, isStreaming }) {
  const [open, setOpen] = useState(true);
  const dotCls = DOMAIN_DOT[domain] ?? 'bg-outline';

  return (
    <div className="rounded-lg border border-outline-variant/40 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-3 py-2 text-left hover:bg-surface-container-low transition-colors"
      >
        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${dotCls}`} />
        <span className="flex-1 text-xs font-semibold text-on-surface capitalize">{domain} Agent</span>
        <span className="text-xs text-on-surface-variant">
          {findings.length} finding{findings.length !== 1 ? 's' : ''}
        </span>
        {open
          ? <ChevronDownIcon size={12} className="text-on-surface-variant flex-shrink-0" />
          : <ChevronRightIcon size={12} className="text-on-surface-variant flex-shrink-0" />}
      </button>

      {open && (
        <ul className="px-3 pb-2.5 space-y-1 border-t border-outline-variant/30 pt-2">
          {findings.map((f, i) => (
            <li
              key={i}
              className="flex items-start gap-2 text-xs text-on-surface leading-snug animate-fade-in"
              style={{ animationDelay: `${i * 80}ms`, animationFillMode: 'both' }}
            >
              <span className="mt-1 flex-shrink-0 w-1 h-1 rounded-full bg-on-surface-variant/50" />
              <span>{f}</span>
            </li>
          ))}
          {isStreaming && (
            <li className="flex items-center gap-1 pt-0.5">
              <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-1" />
              <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-2" />
              <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-3" />
            </li>
          )}
        </ul>
      )}
    </div>
  );
}

function StepRow({ icon, label, done, active }) {
  return (
    <div className={`flex items-center gap-2 text-xs transition-opacity ${done || active ? 'opacity-100' : 'opacity-35'}`}>
      <span className={`flex-shrink-0 w-4 h-4 rounded-full flex items-center justify-center text-[10px] font-bold
        ${done ? 'bg-primary/20 text-primary' : active ? 'bg-surface-container-high text-on-surface-variant' : 'bg-surface-container text-on-surface-variant/40'}`}>
        {done ? '✓' : icon}
      </span>
      <span className={done ? 'text-on-surface font-medium' : active ? 'text-on-surface-variant' : 'text-on-surface-variant/50'}>
        {label}
      </span>
      {active && (
        <span className="flex items-center gap-0.5 ml-1">
          <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-1" />
          <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-2" />
          <span className="w-1 h-1 rounded-full bg-primary/60 animate-dot-3" />
        </span>
      )}
    </div>
  );
}

/* ── GIF mode body ───────────────────────────────────────────────────────── */

function GifBody({ trace }) {
  const gifState = resolveGifState(trace);
  const stepLabel = resolveStepLabel(trace);
  const gifUrl = GIFS[gifState];

  return (
    <div className="flex flex-col items-center gap-3 py-4 px-3">
      {/* Step name */}
      <span className="text-xs font-semibold text-primary uppercase tracking-widest">
        {stepLabel}
      </span>
      {/* GIF */}
      <img
        key={gifUrl}
        src={gifUrl}
        alt={stepLabel}
        className="w-36 h-36 object-contain rounded-2xl"
        loading="eager"
      />
    </div>
  );
}

/* ── Standard mode body ──────────────────────────────────────────────────── */

function StandardBody({ trace }) {
  const {
    selectedAgents    = [],
    domainFindings    = {},
    retrospectionDone = false,
    synthesizerDone   = false,
    formatterDone     = false,
    isStreaming       = false,
  } = trace;

  const supervisorDone = selectedAgents.length > 0;
  const scanDone = (
    Object.keys(domainFindings).length === selectedAgents.length &&
    selectedAgents.length > 0
  );
  const scanActive          = supervisorDone && !scanDone;
  const retrospectionActive = scanDone && !retrospectionDone;
  const synthesizerActive   = retrospectionDone && !synthesizerDone;
  const formatterActive     = synthesizerDone && !formatterDone;

  return (
    <div className="px-3 pb-3 space-y-2.5 border-t border-outline-variant/30">
      {/* Step timeline */}
      <div className="pt-2.5 space-y-1.5">
        <StepRow icon="1" label="Intent understood"          done={supervisorDone}    active={!supervisorDone && isStreaming} />
        <StepRow icon="2" label="Parallel domain scan"       done={scanDone}          active={scanActive} />
        <StepRow icon="3" label="Cross-agent retrospection"  done={retrospectionDone} active={retrospectionActive} />
        <StepRow icon="4" label="Synthesizing report"        done={synthesizerDone}   active={synthesizerActive} />
        <StepRow icon="5" label="Formatting response"        done={formatterDone}     active={formatterActive} />
      </div>

      {/* Selected agent chips */}
      {selectedAgents.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {selectedAgents.map((a) => <AgentChip key={a} agent={a} />)}
        </div>
      )}

      {/* Per-domain findings */}
      {Object.entries(domainFindings).length > 0 && (
        <div className="space-y-1.5">
          {Object.entries(domainFindings).map(([domain, findings]) => (
            <DomainFindingRow
              key={domain}
              domain={domain}
              findings={findings}
              isStreaming={isStreaming && !scanDone}
            />
          ))}
        </div>
      )}
    </div>
  );
}

/* ── Root ────────────────────────────────────────────────────────────────── */

/**
 * TracePanel — renders live agent traces from SSE events.
 *
 * trace shape:
 *   selectedAgents    : string[]
 *   agentGoals        : {[domain]: string}
 *   domainFindings    : {[domain]: string[]}
 *   retrospectionDone : boolean
 *   synthesizerDone   : boolean
 *   formatterDone     : boolean
 *   isStreaming       : boolean
 *   wasRejected       : boolean  — set when user submitted rejections
 */
export default function TracePanel({ trace, gifMode = false }) {
  const [collapsed, setCollapsed] = useState(false);
  const { isStreaming = false } = trace;

  return (
    <div className="mt-1 mb-3 rounded-xl border border-outline-variant/50 bg-surface-container-low/40 overflow-hidden text-xs">
      {/* Header */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className="w-full flex items-center gap-2 px-3 py-2 hover:bg-surface-container-low transition-colors"
      >
        {collapsed
          ? <ChevronRightIcon size={12} className="flex-shrink-0 text-on-surface-variant" />
          : <ChevronDownIcon  size={12} className="flex-shrink-0 text-on-surface-variant" />}
        <span className="flex-1 text-left text-xs font-medium text-on-surface-variant">
          {isStreaming ? 'Thinking' : 'Agent Trace'}
        </span>
        {isStreaming && (
          <span className="flex items-center gap-0.5">
            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-1" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-2" />
            <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-dot-3" />
          </span>
        )}
      </button>

      {!collapsed && (
        gifMode
          ? <GifBody trace={trace} />
          : <StandardBody trace={trace} />
      )}
    </div>
  );
}
