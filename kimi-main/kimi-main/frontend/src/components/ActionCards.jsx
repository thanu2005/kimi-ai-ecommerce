import { useState } from 'react';
import { CheckIcon, XIcon, SendIcon } from 'lucide-react';

function ActionCard({ action, index, decision, onToggle }) {
  const isApproved = decision === 'approve';
  const isRejected = decision === 'reject';

  // Human-readable label from synthesizer enrichment, fallback to action name
  const label =
    action.human_label ??
    action.description ??
    (action.action ? action.action.replace(/_/g, ' ') : `Action ${index + 1}`);

  const reason = action.reason ?? action.rationale ?? null;

  return (
    <div
      className={`rounded-xl border transition-colors ${
        isApproved
          ? 'border-success/40 bg-success-container/60'
          : isRejected
          ? 'border-error/40 bg-error-container/60'
          : 'border-outline-variant bg-surface-container-low'
      }`}
    >
      <div className="px-3 py-2.5">
        <div className="flex items-start justify-between gap-3">
          <div className="flex-1 min-w-0">
            <p className="text-sm font-semibold text-on-surface leading-snug">{label}</p>
            {reason && (
              <p className="text-xs text-on-surface-variant mt-1 leading-snug">Reason: {reason}</p>
            )}
          </div>

          {/* Approve / Reject toggle */}
          <div className="flex gap-1 flex-shrink-0 mt-0.5">
            <button
              onClick={() => onToggle(index, 'approve')}
              title="Approve"
              className={`w-7 h-7 rounded-full flex items-center justify-center border transition-colors ${
                isApproved
                  ? 'bg-primary text-on-primary border-primary'
                  : 'border-outline-variant text-on-surface-variant hover:border-primary hover:text-primary'
              }`}
            >
              <CheckIcon size={13} strokeWidth={2.5} />
            </button>
            <button
              onClick={() => onToggle(index, 'reject')}
              title="Reject"
              className={`w-7 h-7 rounded-full flex items-center justify-center border transition-colors ${
                isRejected
                  ? 'bg-error text-white border-error'
                  : 'border-outline-variant text-on-surface-variant hover:border-error hover:text-error'
              }`}
            >
              <XIcon size={13} strokeWidth={2.5} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function ActionCards({ messageId, proposedActions, onApproval }) {
  const [decisions, setDecisions] = useState(() =>
    Object.fromEntries(proposedActions.map((_, i) => [i, 'approve']))
  );
  const [humanNote, setHumanNote] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const toggleDecision = (index, value) => {
    setDecisions((prev) => ({ ...prev, [index]: value }));
  };

  const handleSubmit = async () => {
    setSubmitting(true);
    const approvedActions = proposedActions.filter((_, i) => decisions[i] === 'approve');
    const rejectedActions = proposedActions.filter((_, i) => decisions[i] === 'reject');
    await onApproval(messageId, { approvedActions, rejectedActions, humanNote });
  };

  const approvedCount = Object.values(decisions).filter((d) => d === 'approve').length;
  const rejectedCount = Object.values(decisions).filter((d) => d === 'reject').length;

  return (
    <div className="mt-3 rounded-2xl border border-outline-variant bg-surface-container-low/60 p-3 space-y-3">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-primary uppercase tracking-wider">
          Proposed Actions ({proposedActions.length})
        </p>
        <p className="text-xs text-on-surface-variant">
          {approvedCount} approve · {rejectedCount} reject
        </p>
      </div>

      {/* Action cards */}
      <div className="space-y-2">
        {proposedActions.map((action, i) => (
          <ActionCard
            key={i}
            action={action}
            index={i}
            decision={decisions[i]}
            onToggle={toggleDecision}
          />
        ))}
      </div>

      {/* Human note */}
      <div>
        <label className="block text-xs text-on-surface-variant mb-1">
          Optional note to the agent
        </label>
        <textarea
          value={humanNote}
          onChange={(e) => setHumanNote(e.target.value)}
          placeholder="Add context or instructions…"
          rows={2}
          className="w-full resize-none rounded-lg border border-outline-variant bg-surface px-3 py-2 text-sm text-on-surface placeholder:text-on-surface-variant/50 focus:outline-none focus:border-primary transition-colors"
        />
      </div>

      {/* Submit */}
      <div className="flex justify-end">
        <button
          onClick={handleSubmit}
          disabled={submitting}
          className="flex items-center gap-2 px-4 py-2 rounded-full bg-primary text-on-primary text-sm font-medium hover:bg-primary/90 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <SendIcon size={13} strokeWidth={2.5} />
          {submitting ? 'Submitting…' : 'Submit Decision'}
        </button>
      </div>
    </div>
  );
}
