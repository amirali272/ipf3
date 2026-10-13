import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Bell, Server, Wifi, WifiOff, Zap } from "lucide-react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Agent, AlertEvent, Job, Overview } from "../api/types";
import { Sparkline, TimeChart } from "../components/charts";
import { Card, Empty, JobStatusBadge, Meter, OnlineBadge, PageHeader, SeverityBadge, StatTile } from "../components/ui";
import { fmtBps, fmtBpsShort, fmtMs, fmtRelative } from "../lib/format";
import { useLive } from "../lib/live";

export default function Dashboard() {
  const live = useLive();
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents"), refetchInterval: 15000 });
  const { data: overview } = useQuery({ queryKey: ["overview"], queryFn: () => api<Overview>("/analytics/overview"), refetchInterval: 15000 });
  const { data: events = [] } = useQuery({
    queryKey: ["alert-events", "firing"],
    queryFn: () => api<AlertEvent[]>("/alerts/events?state=firing&limit=8"),
    refetchInterval: 15000,
  });
  const { data: jobs = [] } = useQuery({ queryKey: ["jobs", "recent"], queryFn: () => api<Job[]>("/jobs?limit=8"), refetchInterval: 10000 });

  // Fleet throughput from live samples: sum the latest real sample of each agent per tick timestamp bucket.
  const fleetSeries = (() => {
    const buckets = new Map<number, { t: number; rx: number; tx: number }>();
    for (const arr of Object.values(live.metrics)) {
      for (const m of arr) {
        const t = Math.floor(new Date(m.ts).getTime() / 10000) * 10000;
        const b = buckets.get(t) ?? { t, rx: 0, tx: 0 };
        b.rx += m.rx_bps ?? 0;
        b.tx += m.tx_bps ?? 0;
        buckets.set(t, b);
      }
    }
    return [...buckets.values()].sort((a, b) => a.t - b.t);
  })();

  const liveOnline = new Map(live.agents.map((a) => [a.id, a.online]));
  const firing = Object.values(overview?.alerts_firing ?? {}).reduce((a, b) => a + (b ?? 0), 0);
  const fmtClock = (t: number) => new Date(t).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });

  return (
    <>
      <PageHeader
        title="Dashboard"
        subtitle={
          <span className="inline-flex items-center gap-2">
            {live.connected ? <Wifi size={14} className="text-emerald-400" /> : <WifiOff size={14} className="text-red-400" />}
            {live.connected ? "Live feed connected" : "Live feed reconnecting…"}
          </span>
        }
      />
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Servers online" icon={<Server size={15} />} accent value={`${overview?.agents_online ?? "—"} / ${overview?.agents_total ?? "—"}`} sub={overview?.agents_disabled ? `${overview.agents_disabled} disabled` : "agents reporting"} />
        <StatTile label="Fleet receive" icon={<ArrowDown size={15} />} value={fmtBps(overview?.fleet_rx_bps)} sub="sum of latest samples" />
        <StatTile label="Fleet transmit" icon={<ArrowUp size={15} />} value={fmtBps(overview?.fleet_tx_bps)} sub="sum of latest samples" />
        <StatTile
          label="Active alerts"
          icon={<Bell size={15} />}
          value={<span className={firing ? "text-red-400" : ""}>{firing}</span>}
          sub={`${overview?.jobs_24h?.completed ?? 0} tests ok · ${overview?.jobs_24h?.failed ?? 0} failed (24h)`}
        />
      </div>

      <Card className="mt-6" title="Fleet bandwidth (live)" actions={<span className="text-xs text-ink-400">since page load · 10 s buckets</span>}>
        <TimeChart
          data={fleetSeries}
          xKey="t"
          area
          series={[{ key: "rx", label: "Receive" }, { key: "tx", label: "Transmit" }]}
          yFormat={fmtBpsShort}
          xFormat={fmtClock}
          tooltipX={fmtClock}
          height={240}
          empty="Waiting for the next samples from agents…"
        />
      </Card>

      <h2 className="mb-3 mt-8 text-sm font-semibold uppercase tracking-wider text-ink-400">Servers</h2>
      {agents.length === 0 ? (
        <Card><Empty>No servers enrolled yet. <Link to="/servers" className="text-emerald-400 hover:underline">Enroll your first server</Link>.</Empty></Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {agents.map((a) => {
            const series = live.metrics[a.id] ?? [];
            const last = series[series.length - 1];
            const online = liveOnline.get(a.id) ?? a.online;
            return (
              <Link key={a.id} to={`/servers/${a.id}`} className="card block p-4 transition hover:border-emerald-800/70">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate font-medium text-ink-100">{a.name}</div>
                    <div className="truncate text-xs text-ink-400">{a.hostname} · {a.os_name || "unknown OS"}</div>
                  </div>
                  <OnlineBadge online={online} disabled={a.disabled} />
                </div>
                <div className="mt-4 grid grid-cols-3 gap-3">
                  <Meter label="CPU" value={last?.cpu_percent ?? a.latest?.cpu_percent} />
                  <Meter label="Memory" value={last?.mem_percent ?? a.latest?.mem_percent} />
                  <Meter label="Disk" value={a.latest?.disk_percent} />
                </div>
                <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div>
                    <div className="flex items-center gap-1 text-ink-400"><ArrowDown size={12} className="text-[var(--series-1)]" />RX <span className="ml-auto tabular-nums text-ink-200">{fmtBps(last?.rx_bps ?? a.latest?.rx_bps, 1)}</span></div>
                    <Sparkline values={series.map((m) => m.rx_bps ?? 0)} color="var(--series-1)" />
                  </div>
                  <div>
                    <div className="flex items-center gap-1 text-ink-400"><ArrowUp size={12} className="text-[var(--series-2)]" />TX <span className="ml-auto tabular-nums text-ink-200">{fmtBps(last?.tx_bps ?? a.latest?.tx_bps, 1)}</span></div>
                    <Sparkline values={series.map((m) => m.tx_bps ?? 0)} color="var(--series-2)" />
                  </div>
                </div>
                <div className="mt-2 text-[11px] text-ink-500">last seen {fmtRelative(a.last_seen_at)}</div>
              </Link>
            );
          })}
        </div>
      )}

      <div className="mt-8 grid gap-6 xl:grid-cols-2">
        <Card title="Firing alerts" actions={<Link to="/alerts" className="text-xs text-emerald-400 hover:underline">View all</Link>} bodyClass="">
          {events.length === 0 ? <Empty>All clear — no alerts firing.</Empty> : (
            <ul className="divide-y divide-ink-800">
              {events.map((e) => (
                <li key={e.id} className="flex items-center gap-3 px-4 py-3 text-sm">
                  <SeverityBadge severity={e.severity} />
                  <span className="min-w-0 flex-1 truncate text-ink-200">{e.message}</span>
                  <span className="text-xs text-ink-500">{fmtRelative(e.started_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Recent tests" actions={<Link to="/tests" className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:underline"><Zap size={12} />Run a test</Link>} bodyClass="">
          {jobs.length === 0 ? <Empty>No tests have been run yet.</Empty> : (
            <table className="table">
              <tbody>
                {jobs.map((j) => (
                  <tr key={j.id}>
                    <td><Link to={`/jobs/${j.id}`} className="font-medium text-ink-100 hover:text-emerald-300">{j.type}</Link></td>
                    <td className="mono truncate text-ink-300">{j.agent_name} → {j.target}</td>
                    <td className="tabular-nums">{j.bps != null ? fmtBps(j.bps) : j.rtt_avg_ms != null ? fmtMs(j.rtt_avg_ms) : "—"}</td>
                    <td><JobStatusBadge status={j.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </>
  );
}
