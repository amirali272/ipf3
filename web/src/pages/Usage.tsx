import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Agent, Usage as UsageT } from "../api/types";
import { DailyBars } from "../components/charts";
import { Card, Empty, Field, PageHeader, StatTile } from "../components/ui";
import { fmtTraffic } from "../lib/format";

const PERIODS = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

const shortTraffic = (v: number) => fmtTraffic(v, v >= 1e9 ? 1 : 0);
const dayLabel = (d: string) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" });

/** Daily consumption for the fleet, one server, or one interface of a server. */
export function UsageView({ agentId, interfaces }: { agentId?: string; interfaces?: string[] }) {
  const [days, setDays] = useState(30);
  const [iface, setIface] = useState("*");
  const { data } = useQuery({
    queryKey: ["usage", days, agentId ?? "", iface],
    queryFn: () => api<UsageT>(`/analytics/usage${qs({ days, agent_id: agentId, iface })}`),
    refetchInterval: 30000,
  });
  const f = data?.fleet;
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-4">
        <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
          {PERIODS.map((p) => (
            <button key={p.days} onClick={() => setDays(p.days)} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${days === p.days ? "bg-emerald-700/40 text-emerald-200 ring-1 ring-emerald-600/60" : "text-ink-400 hover:text-ink-200"}`}>
              {p.label}
            </button>
          ))}
        </div>
        {interfaces && interfaces.length > 0 && (
          <div className="w-56">
            <Field label="Interface">
              <select className="input" value={iface} onChange={(e) => setIface(e.target.value)}>
                <option value="*">Host total (physical NICs)</option>
                {interfaces.map((i) => <option key={i} value={i}>{i}</option>)}
              </select>
            </Field>
          </div>
        )}
        {data && <span className="text-xs text-ink-500">Days follow the {data.timezone} calendar.</span>}
      </div>
      <div className="grid grid-cols-2 gap-4 xl:grid-cols-6">
        <StatTile label="Today ↓" value={fmtTraffic(f?.today_rx)} accent />
        <StatTile label="Today ↑" value={fmtTraffic(f?.today_tx)} />
        <StatTile label="This month ↓" value={fmtTraffic(f?.month_rx)} accent />
        <StatTile label="This month ↑" value={fmtTraffic(f?.month_tx)} />
        <StatTile label={`${days} days ↓`} value={fmtTraffic(f?.period_rx)} />
        <StatTile label={`${days} days ↑`} value={fmtTraffic(f?.period_tx)} />
      </div>
      <Card title="Daily consumption">
        <DailyBars
          data={data?.daily ?? []}
          xKey="day"
          series={[{ key: "rx_bytes", label: "Download (received)" }, { key: "tx_bytes", label: "Upload (sent)" }]}
          yFormat={shortTraffic}
          xFormat={dayLabel}
          tooltipX={(d) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { weekday: "short", year: "numeric", month: "short", day: "numeric" })}
          height={300}
        />
      </Card>
      {!agentId && (
        <Card title="Per server" bodyClass="overflow-x-auto">
          {!data?.agents.length ? <Empty>No consumption recorded yet. Totals start accumulating as soon as agents report.</Empty> : (
            <table className="table">
              <thead><tr><th>Server</th><th>Today ↓</th><th>Today ↑</th><th>Month ↓</th><th>Month ↑</th><th>Month total</th><th>{days} days total</th></tr></thead>
              <tbody>
                {data.agents.map((a) => (
                  <tr key={a.agent_id}>
                    <td><Link className="font-medium text-ink-100 hover:text-emerald-300" to={`/servers/${a.agent_id}`}>{a.name}</Link></td>
                    <td className="tabular-nums">{fmtTraffic(a.today_rx)}</td>
                    <td className="tabular-nums">{fmtTraffic(a.today_tx)}</td>
                    <td className="tabular-nums">{fmtTraffic(a.month_rx)}</td>
                    <td className="tabular-nums">{fmtTraffic(a.month_tx)}</td>
                    <td className="font-semibold tabular-nums text-ink-100">{fmtTraffic(a.month_rx + a.month_tx)}</td>
                    <td className="tabular-nums">{fmtTraffic(a.period_rx + a.period_tx)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </div>
  );
}

export default function Usage() {
  const [agent, setAgent] = useState("");
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  return (
    <>
      <PageHeader
        title="Traffic usage"
        subtitle="Data actually transferred by your servers, measured from their network counters"
        actions={
          <select className="input w-56" value={agent} onChange={(e) => setAgent(e.target.value)}>
            <option value="">All servers</option>
            {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        }
      />
      <UsageView key={agent} agentId={agent || undefined} />
    </>
  );
}
