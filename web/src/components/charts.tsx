import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ReactNode } from "react";

export const SERIES = ["var(--series-1)", "var(--series-2)", "var(--series-3)"];

export interface SeriesDef {
  key: string;
  label: string;
  color?: string;
}

interface Props<T> {
  data: T[];
  xKey: keyof T & string;
  series: SeriesDef[];
  yFormat: (v: number) => string;
  xFormat: (v: any) => string;
  tooltipX?: (v: any) => string;
  height?: number;
  area?: boolean;
  yDomain?: [number | string, number | string];
  empty?: ReactNode;
  /** Show point markers; default: only when there are few points. */
  dots?: boolean;
}

function ChartTooltip({ active, payload, label, yFormat, tooltipX }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-ink-600 bg-ink-900/95 px-3 py-2 text-xs shadow-lg">
      <div className="mb-1 text-ink-400">{tooltipX ? tooltipX(label) : String(label)}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2 text-ink-100">
          <span className="h-2 w-2 rounded-full" style={{ background: p.color }} />
          <span className="text-ink-300">{p.name}</span>
          <span className="ml-auto pl-3 font-medium tabular-nums">{p.value == null ? "—" : yFormat(p.value)}</span>
        </div>
      ))}
    </div>
  );
}

function Legend({ series }: { series: SeriesDef[] }) {
  if (series.length < 2) return null;
  return (
    <div className="mb-2 flex flex-wrap gap-4 text-xs text-ink-300">
      {series.map((s, i) => (
        <span key={s.key} className="inline-flex items-center gap-1.5">
          <span className="h-0.5 w-4 rounded-full" style={{ background: s.color ?? SERIES[i] }} />
          {s.label}
        </span>
      ))}
    </div>
  );
}

/** Single-axis time series chart (never dual-axis). Draws only the points it is
 *  given; gaps in reported data stay gaps. */
export function TimeChart<T extends object>({
  data,
  xKey,
  series,
  yFormat,
  xFormat,
  tooltipX,
  height = 220,
  area = false,
  yDomain,
  empty = "No data reported in this period.",
  dots,
}: Props<T>) {
  if (!data.length) return <div className="flex items-center justify-center text-sm text-ink-500" style={{ height }}>{empty}</div>;
  const dotsFor = (color: string) => ((dots ?? data.length <= 40) ? { r: 3, strokeWidth: 0, fill: color } : false);
  const common = {
    data,
    margin: { top: 6, right: 8, bottom: 0, left: 0 },
  };
  const axes = [
    <CartesianGrid key="g" stroke="var(--grid)" strokeDasharray="0" vertical={false} />,
    <XAxis
      key="x"
      dataKey={xKey}
      tickFormatter={xFormat}
      stroke="var(--axis)"
      tick={{ fontSize: 11 }}
      tickLine={false}
      axisLine={{ stroke: "var(--grid)" }}
      minTickGap={40}
    />,
    <YAxis
      key="y"
      tickFormatter={yFormat}
      stroke="var(--axis)"
      tick={{ fontSize: 11 }}
      tickLine={false}
      axisLine={false}
      width={64}
      domain={yDomain ?? [0, "auto"]}
    />,
    <Tooltip
      key="t"
      content={<ChartTooltip yFormat={yFormat} tooltipX={tooltipX ?? xFormat} />}
      cursor={{ stroke: "var(--axis)", strokeWidth: 1, strokeDasharray: "3 3" }}
      isAnimationActive={false}
    />,
  ];
  return (
    <div>
      <Legend series={series} />
      <ResponsiveContainer width="100%" height={height}>
        {area ? (
          <AreaChart {...common}>
            <defs>
              {series.map((s, i) => (
                <linearGradient key={s.key} id={`grad-${s.key}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={s.color ?? SERIES[i]} stopOpacity={0.28} />
                  <stop offset="100%" stopColor={s.color ?? SERIES[i]} stopOpacity={0.02} />
                </linearGradient>
              ))}
            </defs>
            {axes}
            {series.map((s, i) => (
              <Area
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color ?? SERIES[i]}
                strokeWidth={2}
                fill={`url(#grad-${s.key})`}
                dot={dotsFor(s.color ?? SERIES[i])}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          </AreaChart>
        ) : (
          <LineChart {...common}>
            {axes}
            {series.map((s, i) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={s.color ?? SERIES[i]}
                strokeWidth={2}
                dot={dotsFor(s.color ?? SERIES[i])}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "var(--surface)" }}
                isAnimationActive={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}

/** Tiny trend line for tiles; no axes, hover shows nothing (the tile shows the value). */
export function Sparkline({ values, color = "var(--series-1)", height = 32 }: { values: number[]; color?: string; height?: number }) {
  if (values.length < 2) return <div style={{ height }} />;
  const data = values.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <YAxis hide domain={[0, "auto"]} />
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={2} dot={false} isAnimationActive={false} />
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Grouped daily bars (download / upload). Single y-axis, 2 px gap between bars. */
export function DailyBars<T extends object>({
  data,
  xKey,
  series,
  yFormat,
  xFormat,
  tooltipX,
  height = 240,
}: {
  data: T[];
  xKey: keyof T & string;
  series: SeriesDef[];
  yFormat: (v: number) => string;
  xFormat: (v: any) => string;
  tooltipX?: (v: any) => string;
  height?: number;
}) {
  if (!data.length) return <div className="flex items-center justify-center text-sm text-ink-500" style={{ height }}>No usage recorded yet.</div>;
  return (
    <div>
      <Legend series={series} />
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: 0 }} barGap={2} barCategoryGap="20%">
          <CartesianGrid stroke="var(--grid)" vertical={false} />
          <XAxis dataKey={xKey} tickFormatter={xFormat} stroke="var(--axis)" tick={{ fontSize: 11 }} tickLine={false} axisLine={{ stroke: "var(--grid)" }} minTickGap={16} />
          <YAxis tickFormatter={yFormat} stroke="var(--axis)" tick={{ fontSize: 11 }} tickLine={false} axisLine={false} width={64} />
          <Tooltip
            content={<ChartTooltip yFormat={yFormat} tooltipX={tooltipX ?? xFormat} />}
            cursor={{ fill: "rgba(255,255,255,0.04)" }}
            isAnimationActive={false}
          />
          {series.map((s, i) => (
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={s.color ?? SERIES[i]} radius={[4, 4, 0, 0]} maxBarSize={22} isAnimationActive={false} />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
