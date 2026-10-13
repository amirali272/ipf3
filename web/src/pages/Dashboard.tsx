import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowDown,
  ArrowDownToLine,
  ArrowRight,
  ArrowUp,
  ArrowUpFromLine,
  Bell,
  Clock,
  Cpu,
  Gauge,
  Globe,
  HardDriveDownload,
  Maximize2,
  Minimize2,
  RefreshCw,
  Server,
  ServerCog,
} from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api, qs } from "../api/client";
import type { Agent, AlertEvent, FleetPoint, Overview, Series, Usage } from "../api/types";
import { Sparkline, TimeChart } from "../components/charts";
import { Empty, SeverityBadge } from "../components/ui";
import { fmtBps, fmtBpsShort, fmtDuration, fmtNum, fmtRelative, fmtTraffic, pctChange } from "../lib/format";
import { fleetRates, useLive, type LiveRatePoint } from "../lib/live";

const RANGES = [
  { id: "live", label: "Live", seconds: 0 },
  { id: "1h", label: "1H", seconds: 3600 },
  { id: "6h", label: "6H", seconds: 6 * 3600 },
  { id: "24h", label: "24H", seconds: 86400 },
  { id: "7d", label: "7D", seconds: 7 * 86400 },
] as const;
type RangeId = (typeof RANGES)[number]["id"];

function Kpi({
  label,
  icon,
  value,
  sub,
  tone,
  spark,
  sparkColor,
}: {
  label: string;
  icon: ReactNode;
  value: ReactNode;
  sub?: ReactNode;
  tone: "green" | "blue" | "red" | "neutral";
  spark?: number[];
  sparkColor?: string;
}) {
  const ring = {
    green: "border-emerald-700/60 from-emerald-950/50",
    blue: "border-sky-700/60 from-sky-950/50",
    red: "border-red-700/70 from-red-950/50",
    neutral: "border-ink-700/70 from-ink-850",
  }[tone];
  const iconBox = {
    green: "bg-emerald-600/15 text-emerald-300 ring-emerald-600/40",
    blue: "bg-sky-600/15 text-sky-300 ring-sky-600/40",
    red: "bg-red-600/15 text-red-300 ring-red-600/40",
    neutral: "bg-ink-750 text-ink-300 ring-ink-600",
  }[tone];
  return (
    <div className={`relative overflow-hidden rounded-xl border bg-gradient-to-br to-ink-850 p-4 shadow-card ${ring}`}>
      <div className="flex items-start gap-3">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg ring-1 ${iconBox}`}>{icon}</div>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-300">{label}</div>
          <div className="mt-1 truncate text-[26px] font-bold leading-tight tabular-nums text-ink-100">{value}</div>
          {sub && <div className="mt-1 text-xs text-ink-400">{sub}</div>}
        </div>
      </div>
      {spark && spark.length > 1 && (
        <div className="pointer-events-none absolute bottom-2 right-3 w-28 opacity-90">
          <Sparkline values={spark} color={sparkColor} height={34} />
        </div>
      )}
    </div>
  );
}

function Delta({ value }: { value: number | null }) {
  if (value === null || !Number.isFinite(value)) return <span className="text-ink-500">collecting…</span>;
  const up = value >= 0;
  return (
    <span className={`inline-flex items-center gap-0.5 font-medium ${up ? "text-emerald-400" : "text-sky-300"}`}>
      {up ? <ArrowUp size={12} /> : <ArrowDown size={12} />}
      {Math.abs(value).toFixed(1)}%
      <span className="ml-1 font-normal text-ink-500">vs 1 min ago</span>
    </span>
  );
}

function Bar({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value ?? 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-xs">
        <span className="text-ink-300">{label}</span>
        <span className="tabular-nums text-ink-200">{value == null ? "—" : `${v.toFixed(0)}%`}</span>
      </div>
      <div className="h-1.5 rounded-full bg-ink-750">
        <div className={`h-full rounded-full ${v >= 90 ? "bg-red-400" : v >= 75 ? "bg-amber-400" : "bg-emerald-500"}`} style={{ width: `${Math.min(100, v)}%` }} />
      </div>
    </div>
  );
}

function ServerPanel({ a, rates, usage }: { a: Agent; rates: LiveRatePoint[]; usage?: { rx: number; tx: number } }) {
  const last = rates[rates.length - 1];
  const fresh = last && Date.now() - last.t < 15000;
  const rx = fresh ? last.rx : a.latest?.rx_bps;
  const tx = fresh ? last.tx : a.latest?.tx_bps;
  const window = rates.slice(-60);
  return (
    <Link
      to={`/servers/${a.id}`}
      className="block rounded-xl border border-ink-700/70 border-l-emerald-500 bg-gradient-to-br from-ink-800/60 to-ink-850 p-4 transition hover:border-emerald-700/70 [border-left-width:3px]"
    >
      <div className="flex flex-wrap items-start gap-3">
        <span className={`mt-1 flex h-7 w-7 items-center justify-center rounded-full ${a.online ? "bg-emerald-600/20" : "bg-red-600/20"}`}>
          <span className={`h-2.5 w-2.5 rounded-full ${a.online ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-red-400"}`} />
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold text-ink-100">{a.name}</div>
          <div className="truncate text-xs text-ink-400">{a.os_name || "unknown OS"}</div>
        </div>
        <div className="text-right">
          <span className={`badge ${a.disabled ? "bg-ink-750 text-ink-400" : a.online ? "bg-emerald-900/40 text-emerald-300" : "bg-red-950/50 text-red-300"}`}>
            <span className={`h-1.5 w-1.5 rounded-full ${a.disabled ? "bg-ink-500" : a.online ? "bg-emerald-400" : "bg-red-400"}`} />
            {a.disabled ? "Disabled" : a.online ? "Online" : "Offline"}
          </span>
          {a.remote_addr && (
            <div className="mt-1 flex items-center justify-end gap-1 font-mono text-[11px] text-ink-400"><Globe size={11} />{a.remote_addr}</div>
          )}
        </div>
      </div>
      <div className="mt-4 grid grid-cols-3 gap-4 border-t border-ink-700/60 pt-3">
        <Bar label="CPU" value={a.latest?.cpu_percent} />
        <Bar label="Memory" value={a.latest?.mem_percent} />
        <Bar label="Disk" value={a.latest?.disk_percent} />
      </div>
      <div className="mt-3 grid grid-cols-2 divide-x divide-ink-700/60 border-t border-ink-700/60 pt-3">
        <div className="pr-3">
          <div className="flex items-center gap-1.5 text-xs text-ink-300">
            <ArrowDownToLine size={13} className="text-[var(--series-1)]" /> RX
            <span className="ml-auto text-sm font-semibold tabular-nums text-ink-100">{fmtBps(rx, 1)}</span>
          </div>
          <Sparkline values={window.map((p) => p.rx)} color="var(--series-1)" height={38} />
        </div>
        <div className="pl-3">
          <div className="flex items-center gap-1.5 text-xs text-ink-300">
            <ArrowUpFromLine size={13} className="text-[var(--series-2)]" /> TX
            <span className="ml-auto text-sm font-semibold tabular-nums text-ink-100">{fmtBps(tx, 1)}</span>
          </div>
          <Sparkline values={window.map((p) => p.tx)} color="var(--series-2)" height={38} />
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-3 border-t border-ink-700/60 pt-3 text-xs sm:grid-cols-4">
        <div className="flex items-center gap-2"><Clock size={14} className="text-ink-500" /><div><div className="text-ink-500">Uptime</div><div className="text-ink-200">{fmtDuration(a.latest?.uptime_seconds)}</div></div></div>
        <div className="flex items-center gap-2"><Cpu size={14} className="text-ink-500" /><div className="min-w-0"><div className="text-ink-500">Kernel</div><div className="truncate text-ink-200">{a.kernel || "—"}</div></div></div>
        <div className="flex items-center gap-2"><Gauge size={14} className="text-ink-500" /><div><div className="text-ink-500">Load</div><div className="tabular-nums text-ink-200">{[a.latest?.load1, a.latest?.load5, a.latest?.load15].map((l) => fmtNum(l, 2)).join("  ")}</div></div></div>
        <div className="flex items-center gap-2"><HardDriveDownload size={14} className="text-ink-500" /><div><div className="text-ink-500">Used today</div><div className="tabular-nums text-ink-200">{usage ? fmtTraffic(usage.rx + usage.tx) : "—"}</div></div></div>
      </div>
    </Link>
  );
}

export default function Dashboard() {
  const qc = useQueryClient();
  const live = useLive();
  const [range, setRange] = useState<RangeId>("live");
  const [full, setFull] = useState(false);
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents"), refetchInterval: 10000 });
  const { data: overview, dataUpdatedAt } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/analytics/overview"), refetchInterval: 15000 });
  const { data: usage } = useQuery({ queryKey: ["usage", 30], queryFn: () => api<Usage>("/analytics/usage?days=30"), refetchInterval: 30000 });
  const { data: events = [] } = useQuery({
    queryKey: ["alert-events", "firing"],
    queryFn: () => api<AlertEvent[]>("/alerts/events?state=firing&limit=6"),
    refetchInterval: 15000,
  });
  const rangeSeconds = RANGES.find((r) => r.id === range)!.seconds;
  // History for the selected range; for Live it seeds the chart with the last 15 minutes.
  const histSeconds = range === "live" ? 900 : rangeSeconds;
  const { data: hist } = useQuery({
    queryKey: ["fleet-bandwidth", histSeconds],
    queryFn: () => {
      const to = new Date();
      return api<Series<FleetPoint>>(`/analytics/fleet-bandwidth${qs({ from: new Date(to.getTime() - histSeconds * 1000).toISOString(), to: to.toISOString(), bucket: range === "live" ? 10 : undefined })}`);
    },
    refetchInterval: range === "live" ? false : 60000,
  });

  const fleetLive = useMemo(() => fleetRates(live.rates), [live.rates]);
  const chartData = useMemo(() => {
    if (range !== "live") return (hist?.points ?? []).map((p) => ({ t: new Date(p.t).getTime(), rx: p.rx_bps, tx: p.tx_bps }));
    const firstLive = fleetLive[0]?.t ?? Infinity;
    const seed = (hist?.points ?? [])
      .map((p) => ({ t: new Date(p.t).getTime(), rx: p.rx_bps, tx: p.tx_bps }))
      .filter((p) => p.t < firstLive - 2000);
    return [...seed, ...fleetLive];
  }, [range, hist, fleetLive]);

  const nowRate = fleetLive[fleetLive.length - 1];
  const fresh = nowRate && Date.now() - nowRate.t < 15000;
  const rxNow = fresh ? nowRate.rx : overview?.fleet_rx_bps;
  const txNow = fresh ? nowRate.tx : overview?.fleet_tx_bps;
  const minuteAgo = nowRate ? [...fleetLive].reverse().find((p) => p.t <= nowRate.t - 60000) : undefined;
  const spark = fleetLive.slice(-45);
  const firing = Object.values(overview?.alerts_firing ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const usageBy = new Map((usage?.agents ?? []).map((u) => [u.agent_id, { rx: u.today_rx, tx: u.today_tx }]));
  const fmtClock = (t: number) =>
    new Date(t).toLocaleTimeString(undefined, rangeSeconds > 86400 ? { month: "short", day: "numeric", hour: "2-digit" } : { hour: "2-digit", minute: "2-digit", second: range === "live" ? "2-digit" : undefined });
  const lastUpdated = live.lastTick ?? dataUpdatedAt;

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink-100">Dashboard</h1>
          <p className="mt-1 flex items-center gap-2 text-sm text-ink-400">
            <span className={`h-2 w-2 rounded-full ${live.connected ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-red-400"}`} />
            {live.connected ? "Live traffic and consumption across your servers" : "Live feed reconnecting…"}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            className="rounded-lg border border-ink-700 bg-ink-850 p-2.5 text-emerald-400 hover:bg-ink-800"
            onClick={() => qc.invalidateQueries()}
            aria-label="Refresh"
          >
            <RefreshCw size={16} />
          </button>
          <div className="text-xs">
            <div className="text-ink-500">Last updated</div>
            <div className="tabular-nums text-ink-200">{lastUpdated ? new Date(lastUpdated).toLocaleString() : "—"}</div>
          </div>
          <span className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium ${live.connected ? "border-emerald-700/60 bg-emerald-950/40 text-emerald-300" : "border-ink-700 text-ink-400"}`}>
            <Activity size={15} /> {live.connected ? "Live" : "Offline"}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi
          label="Servers online"
          tone="green"
          icon={<Server size={20} />}
          value={<><span className="text-emerald-300">{overview?.agents_online ?? "—"}</span><span className="text-ink-500"> / </span>{overview?.agents_total ?? "—"}</>}
          sub={<span className="inline-flex items-center gap-1.5"><span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />agents reporting</span>}
        />
        <Kpi label="Fleet receive" tone="green" icon={<ArrowDownToLine size={20} />} value={fmtBps(rxNow)} sub={<Delta value={minuteAgo ? pctChange(nowRate.rx, minuteAgo.rx) : null} />} spark={spark.map((p) => p.rx)} sparkColor="var(--series-1)" />
        <Kpi label="Fleet transmit" tone="blue" icon={<ArrowUpFromLine size={20} />} value={fmtBps(txNow)} sub={<Delta value={minuteAgo ? pctChange(nowRate.tx, minuteAgo.tx) : null} />} spark={spark.map((p) => p.tx)} sparkColor="var(--series-2)" />
        <Kpi
          label="Active alerts"
          tone={firing ? "red" : "neutral"}
          icon={<Bell size={20} />}
          value={<span className={firing ? "text-red-400" : ""}>{firing}</span>}
          sub={firing ? `${overview?.alerts_firing?.critical ?? 0} critical · ${overview?.alerts_firing?.warning ?? 0} warning` : "All clear"}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Downloaded today" tone="neutral" icon={<ArrowDown size={20} />} value={fmtTraffic(usage?.fleet.today_rx)} sub={`since 00:00 · ${usage?.timezone ?? ""}`} />
        <Kpi label="Uploaded today" tone="neutral" icon={<ArrowUp size={20} />} value={fmtTraffic(usage?.fleet.today_tx)} sub={`total ${fmtTraffic((usage?.fleet.today_rx ?? 0) + (usage?.fleet.today_tx ?? 0))}`} />
        <Kpi label="Downloaded this month" tone="neutral" icon={<HardDriveDownload size={20} />} value={fmtTraffic(usage?.fleet.month_rx)} sub={usage ? `since ${new Date(usage.month_start).toLocaleDateString()}` : undefined} />
        <Kpi label="Uploaded this month" tone="neutral" icon={<ServerCog size={20} />} value={fmtTraffic(usage?.fleet.month_tx)} sub={`total ${fmtTraffic((usage?.fleet.month_rx ?? 0) + (usage?.fleet.month_tx ?? 0))}`} />
      </div>

      <section className={`card mt-6 ${full ? "fixed inset-4 z-50 flex flex-col" : ""}`}>
        <div className="card-header">
          <h2 className="flex items-center gap-2 text-base font-semibold text-ink-100">
            <Activity size={18} className="text-emerald-400" /> Fleet bandwidth <span className="font-normal text-ink-400">({range === "live" ? "live, every 2 s" : "average per bucket"})</span>
          </h2>
          <div className="flex items-center gap-2">
            <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
              {RANGES.map((r) => (
                <button
                  key={r.id}
                  onClick={() => setRange(r.id)}
                  className={`rounded-md px-3 py-1 text-xs font-semibold transition ${range === r.id ? "bg-emerald-700/40 text-emerald-200 ring-1 ring-emerald-600/60" : "text-ink-400 hover:text-ink-200"}`}
                >
                  {r.label}
                </button>
              ))}
            </div>
            <button onClick={() => setFull(!full)} className="rounded-md border border-ink-700 p-1.5 text-ink-400 hover:text-ink-100" aria-label={full ? "Exit full screen" : "Full screen"}>
              {full ? <Minimize2 size={15} /> : <Maximize2 size={15} />}
            </button>
          </div>
        </div>
        <div className={`p-4 ${full ? "flex-1" : ""}`}>
          <TimeChart
            data={chartData}
            xKey="t"
            area
            series={[{ key: "rx", label: "Receive" }, { key: "tx", label: "Transmit" }]}
            yFormat={fmtBpsShort}
            xFormat={fmtClock}
            tooltipX={(t) => new Date(t).toLocaleString()}
            height={full ? window.innerHeight - 180 : 300}
            empty="Waiting for the first samples from agents…"
            dots={range === "live" ? false : undefined}
          />
        </div>
      </section>
      {full && <div className="fixed inset-0 z-40 bg-black/70" onClick={() => setFull(false)} />}

      <div className="mt-6 grid gap-6 xl:grid-cols-[1.25fr_1fr]">
        <div className="space-y-6">
          <section className="card">
            <div className="card-header">
              <h2 className="flex items-center gap-2 text-base font-semibold text-ink-100"><Server size={18} className="text-emerald-400" />Servers</h2>
              <Link to="/servers" className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 hover:underline">View all <ArrowRight size={13} /></Link>
            </div>
            <div className="space-y-4 p-4">
              {agents.length === 0 ? (
                <Empty>No servers enrolled yet. <Link to="/servers" className="text-emerald-400 hover:underline">Enroll your first server</Link>.</Empty>
              ) : (
                agents.map((a) => <ServerPanel key={a.id} a={a} rates={live.rates[a.id] ?? []} usage={usageBy.get(a.id)} />)
              )}
            </div>
          </section>
          <section className="card">
            <div className="card-header">
              <h2 className="flex items-center gap-2 text-base font-semibold text-ink-100"><Bell size={18} className="text-emerald-400" />Firing alerts</h2>
              <Link to="/alerts" className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 hover:underline">View all <ArrowRight size={13} /></Link>
            </div>
            {events.length === 0 ? <Empty>All clear — no alerts firing.</Empty> : (
              <ul className="space-y-2 p-4">
                {events.map((e) => (
                  <li key={e.id} className={`flex items-center gap-3 rounded-lg border-l-4 bg-ink-800/60 px-3 py-2.5 text-sm ${e.severity === "critical" ? "border-red-500" : e.severity === "warning" ? "border-amber-400" : "border-sky-400"}`}>
                    <SeverityBadge severity={e.severity} />
                    <span className="min-w-0 flex-1 truncate text-ink-200">{e.message}</span>
                    <span className="whitespace-nowrap text-xs text-ink-500">{fmtRelative(e.started_at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="card self-start">
          <div className="card-header">
            <h2 className="flex items-center gap-2 text-base font-semibold text-ink-100"><HardDriveDownload size={18} className="text-emerald-400" />Traffic consumption</h2>
            <Link to="/usage" className="inline-flex items-center gap-1 text-xs font-medium text-emerald-400 hover:underline">Details <ArrowRight size={13} /></Link>
          </div>
          {!agents.length ? <Empty>No data yet.</Empty> : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr className="whitespace-nowrap"><th>Server</th><th>Now ↓ / ↑</th><th>Today</th><th>This month</th></tr>
                </thead>
                <tbody>
                  {agents.map((a) => {
                    const r = live.rates[a.id];
                    const last = r?.[r.length - 1];
                    const u = usage?.agents.find((x) => x.agent_id === a.id);
                    const freshRate = last && Date.now() - last.t < 15000;
                    return (
                      <tr key={a.id}>
                        <td>
                          <Link to={`/servers/${a.id}`} className="flex items-center gap-2 font-medium text-ink-100 hover:text-emerald-300">
                            <span className={`h-2 w-2 rounded-full ${a.online ? "bg-emerald-400" : "bg-red-400"}`} />{a.name}
                          </Link>
                        </td>
                        <td className="whitespace-nowrap text-xs tabular-nums">
                          <div className="text-[var(--series-1)]">↓ {fmtBps(freshRate ? last.rx : a.latest?.rx_bps, 1)}</div>
                          <div className="text-[var(--series-2)]">↑ {fmtBps(freshRate ? last.tx : a.latest?.tx_bps, 1)}</div>
                        </td>
                        <td className="whitespace-nowrap text-xs tabular-nums">
                          <div className="font-semibold text-ink-100">{fmtTraffic(u ? u.today_rx + u.today_tx : 0)}</div>
                          <div className="text-ink-500">↓ {fmtTraffic(u?.today_rx ?? 0)} · ↑ {fmtTraffic(u?.today_tx ?? 0)}</div>
                        </td>
                        <td className="whitespace-nowrap text-xs tabular-nums">
                          <div className="font-semibold text-ink-100">{fmtTraffic(u ? u.month_rx + u.month_tx : 0)}</div>
                          <div className="text-ink-500">↓ {fmtTraffic(u?.month_rx ?? 0)} · ↑ {fmtTraffic(u?.month_tx ?? 0)}</div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <p className="border-t border-ink-800 px-4 py-3 text-[11px] text-ink-500">
            Measured from the servers' own network counters (physical interfaces). No test traffic is generated.
          </p>
        </section>
      </div>
    </>
  );
}
