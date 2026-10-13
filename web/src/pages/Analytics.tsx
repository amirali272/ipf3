import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Agent, JobType, TestSeries } from "../api/types";
import { TimeChart } from "../components/charts";
import { Card, Empty, Field, PageHeader, RangePicker, StatTile } from "../components/ui";
import { axisTime, fmtBps, fmtBpsShort, fmtMs, fmtNum, fmtTime } from "../lib/format";

const RANGES = [
  { label: "24h", seconds: 86400 },
  { label: "7d", seconds: 7 * 86400 },
  { label: "30d", seconds: 30 * 86400 },
  { label: "90d", seconds: 90 * 86400 },
];

const axisMs = (v: number) => `${v < 1 ? +v.toFixed(3) : v < 10 ? +v.toFixed(2) : +v.toFixed(1)} ms`;

interface TargetRow { agent_id: string; type: JobType; target: string; count: number }
interface FleetRow { agent_id: string; name: string; cpu_avg: number; cpu_max: number; mem_avg: number; rx_avg: number; rx_max: number; tx_avg: number; tx_max: number; samples: number }

export default function Analytics() {
  const [sp, setSp] = useSearchParams();
  const [range, setRange] = useState(7 * 86400);
  const type = (sp.get("type") as JobType) || "ping";
  const agent = sp.get("agent") || "";
  const target = sp.get("target") || "";
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); v ? n.set(k, v) : n.delete(k); if (k !== "target") n.delete("target"); setSp(n, { replace: true }); };

  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  const { data: targets = [] } = useQuery({ queryKey: ["analytics-targets"], queryFn: () => api<TargetRow[]>("/analytics/targets?days=90") });
  const window = useMemo(() => { const to = new Date(); return { from: new Date(to.getTime() - range * 1000).toISOString(), to: to.toISOString() }; }, [range]);
  const { data } = useQuery({
    queryKey: ["analytics-tests", type, agent, target, window],
    queryFn: () => api<TestSeries>(`/analytics/tests${qs({ type, agent_id: agent, target, ...window })}`),
  });
  const { data: fleet } = useQuery({ queryKey: ["analytics-fleet", window], queryFn: () => api<{ agents: FleetRow[] }>(`/analytics/fleet${qs(window)}`) });

  const targetOpts = [...new Set(targets.filter((t) => t.type === type && (!agent || t.agent_id === agent)).map((t) => t.target))];
  const pts = data?.points ?? [];
  const xf = axisTime(range);
  const s = data?.summary;

  return (
    <>
      <PageHeader title="Historical analytics" subtitle="Aggregated from completed tests and stored telemetry" actions={<RangePicker value={range} onChange={setRange} options={RANGES} />} />
      <Card className="mb-6">
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Test type">
            <select className="input" value={type} onChange={(e) => set("type", e.target.value)}>
              {["ping", "iperf3", "mtr", "traceroute", "dns"].map((t) => <option key={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Server">
            <select className="input" value={agent} onChange={(e) => set("agent", e.target.value)}>
              <option value="">All servers</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="Target">
            <select className="input" value={target} onChange={(e) => set("target", e.target.value)}>
              <option value="">All targets</option>
              {targetOpts.map((t) => <option key={t}>{t}</option>)}
            </select>
          </Field>
        </div>
      </Card>
      <div className="mb-6 grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatTile label="Completed tests" value={s?.completed ?? "—"} sub={`${s?.failed ?? 0} failed / expired`} />
        {type === "iperf3" ? <StatTile label="Avg throughput" value={fmtBps(s?.bps_avg)} accent /> : <StatTile label="Avg RTT" value={fmtMs(s?.rtt_avg_ms)} accent />}
        <StatTile label="p95 RTT" value={fmtMs(s?.rtt_p95_ms)} />
        <StatTile label="Avg loss" value={fmtNum(s?.loss_percent, 2, "%")} />
        <StatTile label="Avg jitter" value={fmtMs(s?.jitter_ms)} />
      </div>
      {!pts.length ? <Card><Empty>No completed {type} tests match this selection. Create a schedule to collect history.</Empty></Card> : (
        <div className="grid gap-6 xl:grid-cols-2">
          {type === "iperf3" && (
            <Card title="Throughput" className="xl:col-span-2" actions={<span className="text-xs text-ink-400">{data?.bucket}s buckets</span>}>
              <TimeChart data={pts} xKey="t" series={[{ key: "bps_avg", label: "Average" }, { key: "bps_min", label: "Minimum" }, { key: "bps_max", label: "Maximum" }]} yFormat={fmtBpsShort} xFormat={xf} tooltipX={fmtTime} height={280} />
            </Card>
          )}
          {type !== "iperf3" && (
            <Card title={type === "dns" ? "Resolution time" : "Round-trip time"} className="xl:col-span-2">
              <TimeChart data={pts} xKey="t" series={[{ key: "rtt_avg_ms", label: "Average" }, { key: "rtt_max_ms", label: "Worst" }]} yFormat={axisMs} xFormat={xf} tooltipX={fmtTime} height={280} />
            </Card>
          )}
          {(type === "ping" || type === "mtr" || type === "iperf3") && (
            <Card title="Packet loss">
              <TimeChart data={pts} xKey="t" series={[{ key: "loss_percent", label: "Loss", color: "var(--series-3)" }]} yFormat={(v) => `${v.toFixed(1)}%`} xFormat={xf} tooltipX={fmtTime} />
            </Card>
          )}
          {(type === "ping" || type === "mtr" || type === "iperf3") && (
            <Card title={type === "mtr" ? "Last-hop RTT stdev" : "Jitter"}>
              <TimeChart data={pts} xKey="t" series={[{ key: "jitter_ms", label: "Jitter", color: "var(--series-2)" }]} yFormat={axisMs} xFormat={xf} tooltipX={fmtTime} />
            </Card>
          )}
          {type === "iperf3" && (
            <Card title="TCP retransmits">
              <TimeChart data={pts} xKey="t" series={[{ key: "retransmits", label: "Retransmits", color: "var(--series-3)" }]} yFormat={(v) => v.toFixed(0)} xFormat={xf} tooltipX={fmtTime} />
            </Card>
          )}
        </div>
      )}
      <Card title="Fleet utilisation over the period" className="mt-6" bodyClass="overflow-x-auto">
        {!fleet?.agents.length ? <Empty>No telemetry in this period.</Empty> : (
          <table className="table">
            <thead><tr><th>Server</th><th>CPU avg</th><th>CPU peak</th><th>Mem avg</th><th>RX avg</th><th>RX peak</th><th>TX avg</th><th>TX peak</th><th>Samples</th></tr></thead>
            <tbody>
              {fleet.agents.map((a) => (
                <tr key={a.agent_id}>
                  <td className="font-medium text-ink-100">{a.name}</td>
                  <td>{fmtNum(a.cpu_avg, 1, "%")}</td><td>{fmtNum(a.cpu_max, 1, "%")}</td><td>{fmtNum(a.mem_avg, 1, "%")}</td>
                  <td>{fmtBps(a.rx_avg)}</td><td>{fmtBps(a.rx_max)}</td><td>{fmtBps(a.tx_avg)}</td><td>{fmtBps(a.tx_max)}</td><td>{a.samples}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
