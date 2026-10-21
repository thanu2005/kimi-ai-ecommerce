import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import ActionCards from './ActionCards.jsx';
import TracePanel from './TracePanel.jsx';
import ReportView from './ReportView.jsx';
import ActionEffectivenessPanel from './ActionEffectivenessPanel.jsx';

/* Extract <!--REPORT_DATA-->...<!--/REPORT_DATA--> block from formatted_response.
   Returns { narrative, reportData } — narrative has the block stripped,
   reportData is the parsed JSON (or null if absent / invalid). */
function parseReportData(text) {
  if (!text) return { narrative: text || '', reportData: null };
  const match = text.match(/<!--REPORT_DATA-->([\s\S]*?)<!--\/REPORT_DATA-->/);
  if (!match) return { narrative: text, reportData: null };
  const narrative = text.replace(/<!--REPORT_DATA-->[\s\S]*?<!--\/REPORT_DATA-->/, '').trim();
  try {
    return { narrative, reportData: JSON.parse(match[1].trim()) };
  } catch {
    return { narrative: text, reportData: null };
  }
}

/* ── Helpers ──────────────────────────────────────────── */

const DOMAIN_LABELS = {
  sales: 'Sales',
  inventory: 'Inventory',
  marketing: 'Marketing',
  support: 'Support',
  synthesis: 'Synthesis',
};

function WhiteboardSection({ whiteboard }) {
  if (!whiteboard || Object.keys(whiteboard).length === 0) return null;

  const entries = Object.entries(whiteboard).filter(([, v]) => v && typeof v === 'string' && v.trim());

  if (entries.length === 0) return null;

  return (
    <div className="space-y-3 mb-4">
      {entries.map(([key, value]) => (
        <div key={key} className="rounded-xl bg-surface-container border border-outline-variant/50 overflow-hidden">
          <div className="px-3 py-1.5 bg-surface-container-high border-b border-outline-variant/40">
            <span className="text-xs font-semibold text-primary uppercase tracking-wider">
              {DOMAIN_LABELS[key] ?? key}
            </span>
          </div>
          <div className="px-3 py-2.5">
            <div className="kimi-prose text-sm text-on-surface leading-relaxed">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{value}</ReactMarkdown>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function ExecutedActionsSection({ executedActions }) {
  if (!executedActions || executedActions.length === 0) return null;

  return (
    <div className="mt-3 rounded-xl bg-amber-100 border border-outline-variant/50 p-3">
      <p className="text-xs font-semibold text-primary uppercase tracking-wider mb-2">
        Executed Actions ({executedActions.length})
      </p>
      <ul className="space-y-1.5">
        {executedActions.map((action, i) => (
          <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
            <span className="mt-0.5 w-4 h-4 flex-shrink-0 rounded-full bg-green-300 flex items-center justify-center text-[10px] text-primary font-bold">
              ✓
            </span>
            <span className="leading-snug">
              {action.human_label ?? action.description ?? action.action_type ?? 'Action executed'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/* ── User bubble ──────────────────────────────────────── */
function UserMessage({ content }) {
  return (
    <div className="flex justify-end animate-fade-in py-2">
      <div className="max-w-[70%] px-4 py-2.5 rounded-2xl rounded-tr-sm bg-surface-container-high text-on-surface text-sm leading-relaxed shadow-sm">
        {content}
      </div>
    </div>
  );
}

/* ── Assistant message ────────────────────────────────── */
function AssistantMessage({ message, onApproval, gifMode }) {
  const {
    id, content, messageType, whiteboard, proposedActions,
    executedActions, actionsHandled, isHistory, trace, formattedResponse,
    actionEffectiveness,
  } = message;

  return (
    <div className="flex items-start gap-3 animate-fade-in py-2">
      {/* Avatar */}
      <div className="flex-shrink-0 w-7 h-7 rounded-full bg-surface-container-high border border-outline-variant flex items-center justify-center mt-0.5">
        <span className="text-xs text-primary font-chelsea-market leading-none">K</span>
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs text-on-surface-variant mb-1.5">
          {messageType === 'streaming' ? 'Kimi' : 'Response'}
        </p>

        {/* Live trace panel */}
        {trace && (
          <TracePanel trace={trace} gifMode={gifMode} />
        )}

        {/* History and live messages */}
        {isHistory ? (
          <>
            {/* Formatted response takes priority for history */}
            {formattedResponse ? (() => {
              const { narrative, reportData } = parseReportData(formattedResponse);
              return (
                <>
                  <div className="kimi-prose text-sm text-on-surface leading-relaxed mb-3">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{narrative}</ReactMarkdown>
                  </div>
                  <ReportView reportData={reportData} />
                </>
              );
            })() : content && content.trim() ? (
              <div className="kimi-prose text-sm text-on-surface leading-relaxed mb-3">
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
              </div>
            ) : null}

            {/* Executed actions summary for history */}
            {executedActions && executedActions.length > 0 && (
              <ExecutedActionsSection executedActions={executedActions} />
            )}

            <ActionEffectivenessPanel data={actionEffectiveness} />

            {/* Proposed actions (awaiting approval) — read-only display for history */}
            {proposedActions && proposedActions.length > 0 && !executedActions?.length && (
              <div className="mt-3 rounded-xl bg-primary/5 border border-primary/20 p-3">
                <p className="text-xs font-semibold text-primary uppercase tracking-wider mb-2">
                  Proposed Actions ({proposedActions.length})
                </p>
                <ul className="space-y-1.5">
                  {proposedActions.map((action, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm text-on-surface">
                      <span className="mt-0.5 w-4 h-4 flex-shrink-0 rounded-full bg-primary/20 flex items-center justify-center text-[10px] text-primary font-bold">
                        →
                      </span>
                      <span className="leading-snug">
                        {action.human_label ?? action.description ?? 'Action proposed'}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        ) : (
          <>
            {/* Formatted response — always preferred, no title, clean render */}
            {formattedResponse ? (() => {
              const { narrative, reportData } = parseReportData(formattedResponse);
              return (
                <>
                  <div className="kimi-prose text-sm text-on-surface leading-relaxed mb-3">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{narrative}</ReactMarkdown>
                  </div>
                  <ReportView reportData={reportData} />
                </>
              );
            })() : (
              /* Whiteboard fallback only while formatter hasn't run and no proposed actions yet */
              !proposedActions?.length && <WhiteboardSection whiteboard={whiteboard} />
            )}

            {/* Executed actions summary */}
            {executedActions && executedActions.length > 0 && (
              <ExecutedActionsSection executedActions={executedActions} />
            )}

            <ActionEffectivenessPanel data={actionEffectiveness} />

            {/* HITL Action cards — shown when awaiting human approval.
                Guard on messageType === 'analysis' (set when status === 'awaiting_approval')
                so the modal is never suppressed by a stale formattedResponse. */}
            {proposedActions && proposedActions.length > 0 && !actionsHandled && messageType === 'analysis' && (
              <ActionCards
                messageId={id}
                proposedActions={proposedActions}
                onApproval={onApproval}
              />
            )}

            {/* Already handled notice */}
            {proposedActions && proposedActions.length > 0 && actionsHandled && (
              <p className="text-xs text-on-surface-variant italic mt-1">
                Actions submitted for execution…
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}

/* ── Root ─────────────────────────────────────────────── */
export default function Message({ message, onApproval, gifMode }) {
  if (message.role === 'user') return <UserMessage content={message.content} />;
  return <AssistantMessage message={message} onApproval={onApproval} gifMode={gifMode} />;
}
