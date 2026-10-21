import {
  BarChart, Bar,
  LineChart, Line,
  PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts';

const CHART_COLORS = ['#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e', '#8b5cf6'];

const TOOLTIP_STYLE = {
  backgroundColor: 'var(--md-sys-color-surface-container-high, #1e1e2e)',
  border: '1px solid rgba(202, 196, 208, 0.2)',
  borderRadius: '8px',
  color: 'var(--md-sys-color-on-surface, #e6e0e9)',
  fontSize: '12px',
  padding: '6px 10px',
};

const AXIS_TICK = { fontSize: 10, fill: '#9494a8' };

/* ── Table ── */
function DataTable({ title, columns = [], rows = [] }) {
  if (!columns.length || !rows.length) return null;
  return (
    <div className="rounded-xl bg-surface-container border border-outline-variant/50 overflow-hidden">
      {title && (
        <div className="px-4 py-2 bg-surface-container-high border-b border-outline-variant/40">
          <span className="text-xs font-semibold text-primary uppercase tracking-wider">{title}</span>
        </div>
      )}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-outline-variant/40 bg-surface-container-high/50">
              {columns.map((col, i) => (
                <th key={i} className="px-4 py-2 text-left text-xs font-semibold text-on-surface-variant uppercase tracking-wide whitespace-nowrap">
                  {col}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => (
              <tr key={ri} className={`border-b border-outline-variant/20 ${ri % 2 !== 0 ? 'bg-surface-container-high/20' : ''}`}>
                {row.map((cell, ci) => (
                  <td key={ci} className="px-4 py-2.5 text-on-surface whitespace-nowrap">{cell}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Shared chart card wrapper ── */
function ChartCard({ title, children }) {
  return (
    <div className="rounded-xl bg-surface-container border border-outline-variant/50 overflow-hidden">
      {title && (
        <div className="px-4 py-2 bg-surface-container-high border-b border-outline-variant/40">
          <span className="text-xs font-semibold text-primary uppercase tracking-wider">{title}</span>
        </div>
      )}
      <div className="p-3" style={{ height: 220 }}>
        {children}
      </div>
    </div>
  );
}

/* ── Bar chart (single or multi-series) ── */
function BarChartCard({ chart }) {
  const { title, xKey, yKey, yLabel, color = CHART_COLORS[0], data = [], series } = chart;
  const isMulti = Array.isArray(series) && series.length > 0;
  return (
    <ChartCard title={title}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(202,196,208,0.12)" />
          <XAxis dataKey={xKey} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft', fill: '#9494a8', fontSize: 10, dx: 10 } : undefined}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: 'rgba(99,102,241,0.08)' }} />
          {isMulti && <Legend iconSize={8} wrapperStyle={{ fontSize: 10, color: '#9494a8' }} />}
          {isMulti
            ? series.map((s, i) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color || CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} maxBarSize={32} />
              ))
            : <Bar dataKey={yKey} fill={color} radius={[4, 4, 0, 0]} maxBarSize={40} />
          }
        </BarChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

/* ── Line chart (single or multi-series) ── */
function LineChartCard({ chart }) {
  const { title, xKey, yKey, yLabel, color = CHART_COLORS[1], data = [], series } = chart;
  const isMulti = Array.isArray(series) && series.length > 0;
  return (
    <ChartCard title={title}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, left: -10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(202,196,208,0.12)" />
          <XAxis dataKey={xKey} tick={AXIS_TICK} axisLine={false} tickLine={false} />
          <YAxis
            tick={AXIS_TICK}
            axisLine={false}
            tickLine={false}
            label={yLabel ? { value: yLabel, angle: -90, position: 'insideLeft', fill: '#9494a8', fontSize: 10, dx: 10 } : undefined}
          />
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          {isMulti && <Legend iconSize={8} wrapperStyle={{ fontSize: 10, color: '#9494a8' }} />}
          {isMulti
            ? series.map((s, i) => (
                <Line
                  key={s.key}
                  type="monotone"
                  dataKey={s.key}
                  name={s.label}
                  stroke={s.color || CHART_COLORS[i % CHART_COLORS.length]}
                  strokeWidth={2}
                  dot={{ r: 3, strokeWidth: 0 }}
                  activeDot={{ r: 5, strokeWidth: 0 }}
                />
              ))
            : <Line
                type="monotone"
                dataKey={yKey}
                stroke={color}
                strokeWidth={2}
                dot={{ r: 3, fill: color, strokeWidth: 0 }}
                activeDot={{ r: 5, strokeWidth: 0 }}
              />
          }
        </LineChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

/* ── Pie chart ── */
const RADIAN = Math.PI / 180;
function renderPieLabel({ cx, cy, midAngle, innerRadius, outerRadius, percent }) {
  if (percent < 0.05) return null;
  const r = innerRadius + (outerRadius - innerRadius) * 0.55;
  const x = cx + r * Math.cos(-midAngle * RADIAN);
  const y = cy + r * Math.sin(-midAngle * RADIAN);
  return (
    <text x={x} y={y} fill="white" textAnchor="middle" dominantBaseline="central" fontSize={10}>
      {`${(percent * 100).toFixed(0)}%`}
    </text>
  );
}

function PieChartCard({ chart }) {
  const { title, xKey, yKey, data = [] } = chart;
  return (
    <ChartCard title={title}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Pie
            data={data}
            dataKey={yKey}
            nameKey={xKey}
            cx="50%"
            cy="50%"
            outerRadius={75}
            labelLine={false}
            label={renderPieLabel}
          >
            {data.map((_, i) => (
              <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
            ))}
          </Pie>
          <Tooltip contentStyle={TOOLTIP_STYLE} />
          <Legend iconSize={8} wrapperStyle={{ fontSize: 10, color: '#9494a8' }} />
        </PieChart>
      </ResponsiveContainer>
    </ChartCard>
  );
}

/* ── Root export ── */
export default function ReportView({ reportData }) {
  if (!reportData) return null;
  const { tables = [], charts = [] } = reportData;
  if (!tables.length && !charts.length) return null;

  return (
    <div className="mt-4 space-y-4">
      {tables.map((t, i) => (
        <DataTable key={i} title={t.title} columns={t.columns} rows={t.rows} />
      ))}
      {charts.length > 0 && (
        <div className={`grid gap-4 ${charts.length === 1 ? 'grid-cols-1' : 'grid-cols-1 sm:grid-cols-2'}`}>
          {charts.map((c, i) => {
            if (c.type === 'bar')  return <BarChartCard  key={i} chart={c} />;
            if (c.type === 'line') return <LineChartCard key={i} chart={c} />;
            if (c.type === 'pie')  return <PieChartCard  key={i} chart={c} />;
            return null;
          })}
        </div>
      )}
    </div>
  );
}
