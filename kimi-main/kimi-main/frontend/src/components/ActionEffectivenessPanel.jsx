function scoreTone(rate) {
  if (rate >= 70) return 'bg-emerald-500';
  if (rate >= 50) return 'bg-amber-500';
  return 'bg-rose-500';
}

function confidenceBadge(confidence) {
  if (confidence === 'HIGH') return 'bg-emerald-100 text-emerald-700';
  if (confidence === 'MEDIUM') return 'bg-amber-100 text-amber-700';
  return 'bg-slate-100 text-slate-700';
}

function rowLabel(action) {
  return action
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (s) => s.toUpperCase());
}

export default function ActionEffectivenessPanel({ data }) {
  const rows = data?.top_actions ?? [];
  if (!rows.length) return null;

  return (
    <section className="mt-4 rounded-2xl border border-outline-variant/50 bg-gradient-to-br from-surface-container to-surface-container-high overflow-hidden">
      <header className="px-4 py-3 border-b border-outline-variant/40 flex items-center justify-between">
        <div>
          <p className="text-xs font-semibold text-primary uppercase tracking-wider">Historical Action Leaderboard</p>
          <p className="text-[11px] text-on-surface-variant mt-0.5">Cross-thread memory evidence from similar incidents</p>
        </div>
        <span className="text-[11px] text-on-surface-variant">
          Distinct actions: {data.total_distinct_actions ?? rows.length}
        </span>
      </header>

      <div className="p-3 space-y-2">
        {rows.map((row, idx) => {
          const pct = Math.max(0, Math.min(100, Number(row.success_rate || 0)));
          return (
            <div key={`${row.action}-${idx}`} className="rounded-xl bg-surface border border-outline-variant/40 p-3">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-sm font-semibold text-on-surface">{rowLabel(row.action)}</p>
                  <p className="text-[11px] text-on-surface-variant mt-0.5">
                    {row.success_count}/{row.count} successful outcomes
                  </p>
                </div>
                <span className={`text-[10px] font-semibold px-2 py-1 rounded-full ${confidenceBadge(row.confidence)}`}>
                  {row.confidence}
                </span>
              </div>

              <div className="mt-2.5 h-2.5 w-full bg-surface-container-high rounded-full overflow-hidden">
                <div className={`h-full ${scoreTone(pct)}`} style={{ width: `${pct}%` }} />
              </div>

              <div className="mt-2 flex items-center justify-between">
                <span className="text-[11px] text-on-surface-variant">Success rate</span>
                <span className="text-xs font-semibold text-on-surface">{pct.toFixed(1)}%</span>
              </div>

              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="text-[10px] px-2 py-1 rounded-full bg-emerald-100 text-emerald-700">Improved {row.outcomes?.improved ?? 0}</span>
                <span className="text-[10px] px-2 py-1 rounded-full bg-sky-100 text-sky-700">Stable {row.outcomes?.stable ?? 0}</span>
                <span className="text-[10px] px-2 py-1 rounded-full bg-amber-100 text-amber-700">Mixed {row.outcomes?.mixed ?? 0}</span>
                <span className="text-[10px] px-2 py-1 rounded-full bg-rose-100 text-rose-700">Worsened {row.outcomes?.worsened ?? 0}</span>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
}
