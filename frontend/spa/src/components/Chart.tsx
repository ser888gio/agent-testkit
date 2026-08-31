// Recharts wrappers for the Analytics page. Colours come from the stylesheet
// tokens so charts follow the theme instead of hardcoding a palette.

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

const AXIS = { stroke: "var(--ink-tertiary)", fontSize: 11 };
const TOOLTIP = {
  contentStyle: {
    background: "var(--surface-1)",
    border: "1px solid var(--hairline-strong)",
    borderRadius: "var(--radius-sm)",
    fontSize: 12,
    color: "var(--ink)",
  },
  labelStyle: { color: "var(--ink-muted)" },
};

/** Score over time. Fixed 0-100 axis: a 90 must not read as a disaster next to a 95. */
export function ScoreAreaChart({
  data,
  height = 240,
}: {
  data: { label: string; score: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
        <defs>
          <linearGradient id="score-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--accent)" stopOpacity={0.35} />
            <stop offset="100%" stopColor="var(--accent)" stopOpacity={0} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="var(--hairline)" vertical={false} />
        <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} minTickGap={24} />
        <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} width={40} />
        <Tooltip {...TOOLTIP} formatter={(v) => [`${v}%`, "Score"]} />
        <Area
          type="monotone"
          dataKey="score"
          stroke="var(--accent)"
          strokeWidth={2}
          fill="url(#score-fill)"
          dot={false}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Passed vs failed per bucket, stacked — the Testmo daily-run bar. */
export function PassFailBarChart({
  data,
  height = 240,
}: {
  data: { label: string; passed: number; failed: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid stroke="var(--hairline)" vertical={false} />
        <XAxis dataKey="label" tick={AXIS} tickLine={false} axisLine={false} minTickGap={16} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={40} allowDecimals={false} />
        <Tooltip {...TOOLTIP} cursor={{ fill: "var(--surface-2)" }} />
        <Legend iconType="circle" iconSize={8} wrapperStyle={{ fontSize: 12 }} />
        <Bar dataKey="passed" stackId="r" name="Passed" fill="var(--pass-text)" />
        <Bar dataKey="failed" stackId="r" name="Failed" fill="var(--fail-text)" radius={[3, 3, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Horizontal ranked bars — failure rate by category. */
export function RateBarChart({
  data,
  height = 240,
}: {
  data: { label: string; percent: number }[];
  height?: number;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, bottom: 0, left: 8 }}>
        <CartesianGrid stroke="var(--hairline)" horizontal={false} />
        <XAxis type="number" domain={[0, 100]} unit="%" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="label" tick={AXIS} tickLine={false} axisLine={false} width={110} />
        <Tooltip {...TOOLTIP} cursor={{ fill: "var(--surface-2)" }} formatter={(v) => [`${v}%`, "Failure rate"]} />
        <Bar dataKey="percent" radius={[0, 3, 3, 0]}>
          {data.map((row) => (
            // A failure rate has no "good" band: only zero is good.
            <Cell
              key={row.label}
              fill={
                row.percent >= 35
                  ? "var(--fail-text)"
                  : row.percent > 0
                    ? "var(--warn-text)"
                    : "var(--pass-text)"
              }
            />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Donut with a centred figure — the Testmo "runs this week" ring. */
export function DonutChart({
  data,
  centerValue,
  centerLabel,
  height = 220,
}: {
  data: { label: string; value: number; color: string }[];
  centerValue: React.ReactNode;
  centerLabel: string;
  height?: number;
}) {
  return (
    <div className="donut-wrap" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <PieChart>
          <Tooltip {...TOOLTIP} />
          <Pie
            data={data}
            dataKey="value"
            nameKey="label"
            innerRadius="68%"
            outerRadius="92%"
            paddingAngle={2}
            stroke="none"
          >
            {data.map((slice) => (
              <Cell key={slice.label} fill={slice.color} />
            ))}
          </Pie>
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-center">
        <strong>{centerValue}</strong>
        <span>{centerLabel}</span>
      </div>
    </div>
  );
}
