import { useMutation, useQuery } from "@tanstack/react-query";
import { Play } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Agent, Job, JobStatus, JobType } from "../api/types";
import { Card, Empty, ErrorText, Field, JobStatusBadge, PageHeader, Tabs } from "../components/ui";
import { fmtBps, fmtMs, fmtNum, fmtRelative } from "../lib/format";
import { useAuth } from "../lib/auth";

type Params = Record<string, string | number | boolean | null>;

const DEFAULTS: Record<JobType, Params> = {
  iperf3: { target: "", port: 5201, protocol: "tcp", duration: 10, parallel: 1, direction: "forward", bitrate_mbps: "", omit: 0, ipv6: false },
  ping: { target: "", count: 20, interval: 1, packet_size: 56, ipv6: false },
  traceroute: { target: "", max_hops: 30, queries: 3, protocol: "udp", ipv6: false },
  mtr: { target: "", count: 10, max_hops: 30, protocol: "icmp", ipv6: false },
  dns: { name: "", record_type: "A", server: "", protocol: "udp", timeout: 5 },
};

/** Converts the form state into the API parameter object. */
export function toApiParams(type: JobType, p: Params): Record<string, unknown> {
  if (type === "iperf3") {
    const { direction, bitrate_mbps, ...rest } = p;
    const out: Record<string, unknown> = { ...rest, reverse: direction === "reverse", bidir: direction === "bidir" };
    if (bitrate_mbps !== "" && bitrate_mbps !== null) out.bitrate_bps = Math.round(Number(bitrate_mbps) * 1e6);
    return out;
  }
  if (type === "dns") return { ...p, server: p.server || null };
  return { ...p };
}

export function JobForm({ type, params, setParams }: { type: JobType; params: Params; setParams: (p: Params) => void }) {
  const set = (k: string, v: string | number | boolean) => setParams({ ...params, [k]: v });
  const num = (k: string, label: string, min: number, max: number, step = 1, hint?: string) => (
    <Field label={label} hint={hint}>
      <input className="input" type="number" min={min} max={max} step={step} value={params[k] as number} onChange={(e) => set(k, e.target.value === "" ? "" : Number(e.target.value))} />
    </Field>
  );
  const sel = (k: string, label: string, opts: [string, string][]) => (
    <Field label={label}>
      <select className="input" value={params[k] as string} onChange={(e) => set(k, e.target.value)}>
        {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </Field>
  );
  const text = (k: string, label: string, placeholder: string, hint?: string) => (
    <Field label={label} hint={hint}>
      <input className="input mono" value={params[k] as string} placeholder={placeholder} onChange={(e) => set(k, e.target.value.trim())} />
    </Field>
  );
  const v6 = (
    <label className="flex items-center gap-2 pt-6 text-sm text-ink-300">
      <input type="checkbox" checked={!!params.ipv6} onChange={(e) => set("ipv6", e.target.checked)} className="accent-emerald-500" /> Force IPv6
    </label>
  );
  const grid = (children: ReactNode) => <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
  switch (type) {
    case "iperf3":
      return grid(<>
        {text("target", "iperf3 server", "10.0.0.3 or host.example.com", "Host running iperf3 -s")}
        {num("port", "Port", 1, 65535)}
        {sel("protocol", "Protocol", [["tcp", "TCP"], ["udp", "UDP"]])}
        {sel("direction", "Direction", [["forward", "Upload (client → server)"], ["reverse", "Download (server → client, -R)"], ["bidir", "Bidirectional"]])}
        {num("duration", "Duration (s)", 1, 300)}
        {num("parallel", "Parallel streams", 1, 32)}
        <Field label="Target bitrate (Mbit/s)" hint={params.protocol === "udp" ? "UDP default is 1 Mbit/s" : "Empty = unlimited"}>
          <input className="input" type="number" min={0.001} step="any" value={params.bitrate_mbps as string} onChange={(e) => set("bitrate_mbps", e.target.value)} />
        </Field>
        {num("omit", "Omit first (s)", 0, 10, 1, "Skip TCP slow-start")}
        {v6}
      </>);
    case "ping":
      return grid(<>
        {text("target", "Target", "1.1.1.1")}
        {num("count", "Count", 1, 1000)}
        {num("interval", "Interval (s)", 0.2, 10, 0.1)}
        {num("packet_size", "Payload (bytes)", 16, 65000)}
        {v6}
      </>);
    case "traceroute":
      return grid(<>
        {text("target", "Target", "example.com")}
        {num("max_hops", "Max hops", 1, 64)}
        {num("queries", "Probes per hop", 1, 5)}
        {sel("protocol", "Probe protocol", [["udp", "UDP"], ["icmp", "ICMP echo"], ["tcp", "TCP SYN"]])}
        {v6}
      </>);
    case "mtr":
      return grid(<>
        {text("target", "Target", "example.com")}
        {num("count", "Cycles", 1, 200)}
        {num("max_hops", "Max hops", 1, 64)}
        {sel("protocol", "Probe protocol", [["icmp", "ICMP"], ["udp", "UDP"], ["tcp", "TCP"]])}
        {v6}
      </>);
    case "dns":
      return grid(<>
        {text("name", "Name", "example.com", "IP address → PTR lookup")}
        {sel("record_type", "Record type", ["A", "AAAA", "MX", "TXT", "NS", "CNAME", "SOA", "PTR", "SRV", "CAA"].map((t) => [t, t]))}
        {text("server", "Resolver IP", "system default")}
        {sel("protocol", "Transport", [["udp", "UDP"], ["tcp", "TCP"]])}
        {num("timeout", "Timeout (s)", 0.5, 30, 0.5)}
      </>);
  }
}

export const TYPE_TABS: { id: JobType; label: string }[] = [
  { id: "iperf3", label: "Speed test (iperf3)" },
  { id: "ping", label: "Ping / loss / jitter" },
  { id: "traceroute", label: "Traceroute" },
  { id: "mtr", label: "MTR" },
  { id: "dns", label: "DNS" },
];

export function JobsTable({ jobs }: { jobs: Job[] }) {
  if (!jobs.length) return <Empty>No tests found.</Empty>;
  return (
    <table className="table">
      <thead><tr><th>Type</th><th>From</th><th>Target</th><th>Throughput</th><th>RTT</th><th>Loss</th><th>Jitter</th><th>Status</th><th>When</th></tr></thead>
      <tbody>
        {jobs.map((j) => (
          <tr key={j.id}>
            <td><Link className="font-medium text-ink-100 hover:text-emerald-300" to={`/jobs/${j.id}`}>{j.type}{j.schedule_id ? <span className="ml-1 text-[10px] text-ink-500">sched</span> : null}</Link></td>
            <td>{j.agent_name}</td>
            <td className="mono">{j.target}</td>
            <td className="tabular-nums">{fmtBps(j.bps)}</td>
            <td className="tabular-nums">{fmtMs(j.rtt_avg_ms)}</td>
            <td className="tabular-nums">{fmtNum(j.loss_percent, 1, "%")}</td>
            <td className="tabular-nums">{fmtMs(j.jitter_ms)}</td>
            <td><JobStatusBadge status={j.status} /></td>
            <td className="whitespace-nowrap">{fmtRelative(j.created_at)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function Tests() {
  const { can } = useAuth();
  const nav = useNavigate();
  const [type, setType] = useState<JobType>("iperf3");
  const [params, setParams] = useState<Record<JobType, Params>>(DEFAULTS);
  const [agentId, setAgentId] = useState("");
  const [filterType, setFilterType] = useState("");
  const [filterStatus, setFilterStatus] = useState<JobStatus | "">("");
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  const { data: jobs = [] } = useQuery({
    queryKey: ["jobs", filterType, filterStatus],
    queryFn: () => api<Job[]>(`/jobs${qs({ type: filterType, status: filterStatus, limit: 100 })}`),
    refetchInterval: 5000,
  });
  const usable = agents.filter((a) => !a.disabled);
  const selected = agentId || usable[0]?.id || "";
  const selectedAgent = agents.find((a) => a.id === selected);
  const missingTool = selectedAgent?.capabilities.tools && selectedAgent.capabilities.tools[type] === false;
  const run = useMutation({
    mutationFn: () => api<Job>("/jobs", { method: "POST", json: { agent_id: selected, type, params: toApiParams(type, params[type]) } }),
    onSuccess: (j) => nav(`/jobs/${j.id}`),
  });

  return (
    <>
      <PageHeader title="Speed & Diagnostics" subtitle="Run iperf3 bandwidth tests and network diagnostics from any enrolled server" />
      {can("operator") ? (
        <Card className="mb-6" bodyClass="">
          <div className="px-4 pt-2"><Tabs tabs={TYPE_TABS} value={type} onChange={setType} /></div>
          <div className="space-y-4 p-4">
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <Field label="Run from server">
                <select className="input" value={selected} onChange={(e) => setAgentId(e.target.value)}>
                  {usable.map((a) => <option key={a.id} value={a.id}>{a.name}{a.online ? "" : " (offline)"}</option>)}
                </select>
              </Field>
            </div>
            <JobForm type={type} params={params[type]} setParams={(p) => setParams({ ...params, [type]: p })} />
            {missingTool && <div className="text-sm text-amber-300">{type} is not installed on {selectedAgent?.name}. Install it with apt and restart the agent.</div>}
            <ErrorText error={run.error} />
            <div className="flex justify-end">
              <button className="btn-primary" disabled={!selected || run.isPending || !!missingTool} onClick={() => run.mutate()}>
                <Play size={15} /> {run.isPending ? "Queuing…" : "Run test"}
              </button>
            </div>
          </div>
        </Card>
      ) : (
        <div className="mb-6 rounded-lg border border-ink-700 bg-ink-850 px-4 py-3 text-sm text-ink-400">Your role is read-only. Operators and admins can run tests.</div>
      )}
      <Card
        title="Test history"
        bodyClass="overflow-x-auto"
        actions={
          <div className="flex gap-2">
            <select className="input w-36" value={filterType} onChange={(e) => setFilterType(e.target.value)}>
              <option value="">All types</option>
              {TYPE_TABS.map((t) => <option key={t.id} value={t.id}>{t.id}</option>)}
            </select>
            <select className="input w-36" value={filterStatus} onChange={(e) => setFilterStatus(e.target.value as JobStatus)}>
              <option value="">All statuses</option>
              {["queued", "running", "completed", "failed", "cancelled", "expired"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        }
      >
        <JobsTable jobs={jobs} />
      </Card>
    </>
  );
}
