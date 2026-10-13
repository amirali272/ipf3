import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, RefreshCw, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, qs } from "../api/client";
import type { Agent, IfacePoint, Inventory, Job, MetricPoint, Series } from "../api/types";
import { TimeChart } from "../components/charts";
import { Card, Empty, ErrorText, Field, JobStatusBadge, OnlineBadge, PageHeader, RangePicker, Spinner, StatTile, Tabs } from "../components/ui";
import { axisTime, fmtBps, fmtBpsShort, fmtBytes, fmtDuration, fmtMs, fmtNum, fmtRelative, fmtTime } from "../lib/format";
import { useAuth } from "../lib/auth";
import { useLive } from "../lib/live";
import { CopyBox } from "./Servers";

type Tab = "overview" | "interfaces" | "routes" | "connections" | "dns" | "tests" | "settings";

function rangeParams(seconds: number) {
  const to = new Date();
  const from = new Date(to.getTime() - seconds * 1000);
  return { from: from.toISOString(), to: to.toISOString() };
}

function Overview({ agent, range }: { agent: Agent; range: number }) {
  const { data, isLoading } = useQuery({
    queryKey: ["metrics", agent.id, range],
    queryFn: () => api<Series<MetricPoint>>(`/agents/${agent.id}/metrics${qs(rangeParams(range))}`),
    refetchInterval: range <= 3600 ? 10000 : 60000,
  });
  const pts = data?.points ?? [];
  const xf = axisTime(range);
  const tip = (t: string) => fmtTime(t);
  if (isLoading) return <Spinner />;
  return (
    <div className="grid gap-6 xl:grid-cols-2">
      <Card title="Bandwidth (all interfaces)" className="xl:col-span-2" actions={<span className="text-xs text-ink-400">{data?.bucket}s average</span>}>
        <TimeChart data={pts} xKey="t" area series={[{ key: "rx_bps", label: "Receive" }, { key: "tx_bps", label: "Transmit" }]} yFormat={fmtBpsShort} xFormat={xf} tooltipX={tip} height={260} />
      </Card>
      <Card title="CPU & memory utilisation">
        <TimeChart data={pts} xKey="t" series={[{ key: "cpu_percent", label: "CPU" }, { key: "mem_percent", label: "Memory" }, { key: "disk_percent", label: "Disk" }]} yFormat={(v) => `${v.toFixed(0)}%`} xFormat={xf} tooltipX={tip} yDomain={[0, 100]} />
      </Card>
      <Card title="Load average">
        <TimeChart data={pts} xKey="t" series={[{ key: "load1", label: "1 min" }, { key: "load5", label: "5 min" }, { key: "load15", label: "15 min" }]} yFormat={(v) => v.toFixed(2)} xFormat={xf} tooltipX={tip} />
      </Card>
      <Card title="TCP sockets">
        <TimeChart data={pts} xKey="t" series={[{ key: "tcp_established", label: "Established" }, { key: "tcp_time_wait", label: "TIME_WAIT" }]} yFormat={(v) => v.toFixed(0)} xFormat={xf} tooltipX={tip} />
      </Card>
      <Card title="TCP retransmitted segments (per bucket)">
        <TimeChart data={pts} xKey="t" series={[{ key: "tcp_retrans", label: "Retransmits", color: "var(--series-3)" }]} yFormat={(v) => v.toFixed(0)} xFormat={xf} tooltipX={tip} />
      </Card>
    </div>
  );
}

function Interfaces({ agent, inv, range }: { agent: Agent; inv?: Inventory; range: number }) {
  const candidates = inv?.interfaces.filter((i) => i.name !== "lo") ?? [];
  const preferred = candidates.find((i) => (i.state ?? "").toUpperCase() === "UP" && i.addresses.length) ?? candidates[0];
  const [iface, setIface] = useState<string>("");
  const selected = iface || preferred?.name || "";
  const live = useLive(agent.id);
  const { data } = useQuery({
    queryKey: ["iface-metrics", agent.id, selected, range],
    queryFn: () => api<Series<IfacePoint>>(`/agents/${agent.id}/interfaces/metrics${qs({ ...rangeParams(range), iface: selected })}`),
    enabled: !!selected,
    refetchInterval: range <= 3600 ? 10000 : 60000,
  });
  const livePts = live.ifaces.filter((p) => p.iface === selected).map((p) => ({ ...p, t: p.ts }));
  const clock = (t: string) => new Date(t).toLocaleTimeString();
  return (
    <div className="space-y-6">
      <Card title="Interfaces" bodyClass="overflow-x-auto">
        {!inv?.interfaces.length ? <Empty>No interface inventory reported yet.</Empty> : (
          <table className="table">
            <thead><tr><th>Name</th><th>State</th><th>Addresses</th><th>MAC</th><th>MTU</th><th>Speed</th></tr></thead>
            <tbody>
              {inv.interfaces.map((i) => (
                <tr key={i.name} className={i.name === selected ? "bg-emerald-950/20" : ""} onClick={() => i.name !== "lo" && setIface(i.name)} style={{ cursor: "pointer" }}>
                  <td className="mono font-medium text-ink-100">{i.name}</td>
                  <td><span className={`badge ${i.state === "UP" || i.state === "up" ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`}>{i.state ?? "?"}</span></td>
                  <td className="mono text-xs">{i.addresses.join(", ") || "—"}</td>
                  <td className="mono text-xs">{i.mac ?? "—"}</td>
                  <td>{i.mtu ?? "—"}</td>
                  <td>{i.speed_mbps ? `${i.speed_mbps} Mb/s ${i.duplex ?? ""}` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {selected && (
        <div className="grid gap-6 xl:grid-cols-2">
          <Card title={<>Live throughput · <span className="mono text-emerald-300">{selected}</span></>} actions={<span className="text-xs text-ink-400">{live.connected ? "streaming" : "connecting…"}</span>}>
            <TimeChart data={livePts} xKey="t" area series={[{ key: "rx_bps", label: "Receive" }, { key: "tx_bps", label: "Transmit" }]} yFormat={fmtBpsShort} xFormat={clock} empty="Waiting for the next sample…" />
          </Card>
          <Card title={<>Packets per second · <span className="mono text-emerald-300">{selected}</span></>}>
            <TimeChart data={livePts} xKey="t" series={[{ key: "rx_pps", label: "RX pps" }, { key: "tx_pps", label: "TX pps" }]} yFormat={(v) => fmtBpsShort(v)} xFormat={clock} empty="Waiting for the next sample…" />
          </Card>
          <Card title={<>History · <span className="mono text-emerald-300">{selected}</span></>} className="xl:col-span-2">
            <TimeChart data={data?.points ?? []} xKey="t" area series={[{ key: "rx_bps", label: "Receive (avg)" }, { key: "tx_bps", label: "Transmit (avg)" }]} yFormat={fmtBpsShort} xFormat={axisTime(range)} tooltipX={fmtTime} height={240} />
          </Card>
          <Card title="Errors & drops (per bucket)" className="xl:col-span-2">
            <TimeChart data={data?.points ?? []} xKey="t" series={[{ key: "errors", label: "Errors" }, { key: "drops", label: "Drops", color: "var(--series-3)" }]} yFormat={(v) => v.toFixed(0)} xFormat={axisTime(range)} tooltipX={fmtTime} height={180} />
          </Card>
        </div>
      )}
    </div>
  );
}

function Routes({ inv }: { inv?: Inventory }) {
  const table = (routes: Inventory["routes"], title: string) => (
    <Card title={title} bodyClass="overflow-x-auto">
      {!routes.length ? <Empty>No routes reported.</Empty> : (
        <table className="table">
          <thead><tr><th>Destination</th><th>Gateway</th><th>Device</th><th>Protocol</th><th>Scope</th><th>Metric</th><th>Source</th><th>Table</th></tr></thead>
          <tbody>
            {routes.map((r, i) => (
              <tr key={i}>
                <td className="mono text-ink-100">{r.dst}</td>
                <td className="mono">{r.gateway ?? "—"}</td>
                <td className="mono">{r.dev ?? "—"}</td>
                <td>{r.protocol ?? "—"}</td>
                <td>{r.scope ?? "—"}</td>
                <td>{r.metric ?? "—"}</td>
                <td className="mono">{r.prefsrc ?? "—"}</td>
                <td>{r.table ?? "main"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
  return <div className="space-y-6">{table(inv?.routes ?? [], "IPv4 routes")}{table(inv?.routes6 ?? [], "IPv6 routes")}</div>;
}

function Connections({ inv }: { inv?: Inventory }) {
  const [filter, setFilter] = useState("");
  const [state, setState] = useState("");
  const conns = inv?.connections ?? [];
  const states = useMemo(() => {
    const m = new Map<string, number>();
    conns.forEach((c) => m.set(c.state, (m.get(c.state) ?? 0) + 1));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [conns]);
  const shown = conns.filter((c) => (!state || c.state === state) && (!filter || `${c.local} ${c.peer} ${c.proto}`.includes(filter)));
  return (
    <Card
      title={`Sockets (${conns.length})`}
      actions={
        <div className="flex gap-2">
          <select className="input w-36" value={state} onChange={(e) => setState(e.target.value)}>
            <option value="">All states</option>
            {states.map(([s, n]) => <option key={s} value={s}>{s} ({n})</option>)}
          </select>
          <input className="input w-56" placeholder="Filter address / port" value={filter} onChange={(e) => setFilter(e.target.value)} />
        </div>
      }
      bodyClass="max-h-[640px] overflow-auto"
    >
      {!shown.length ? <Empty>No sockets match.</Empty> : (
        <table className="table">
          <thead className="sticky top-0 bg-ink-850"><tr><th>Proto</th><th>State</th><th>Local</th><th>Peer</th><th>Recv-Q</th><th>Send-Q</th></tr></thead>
          <tbody>
            {shown.slice(0, 1000).map((c, i) => (
              <tr key={i}>
                <td>{c.proto}</td><td>{c.state}</td><td className="mono">{c.local}</td><td className="mono">{c.peer}</td><td>{c.recv_q}</td><td>{c.send_q}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function Dns({ inv }: { inv?: Inventory }) {
  const d = inv?.dns ?? {};
  const row = (k: string, v?: string[] | string) => (
    <div className="flex gap-4 border-b border-ink-800 py-2 text-sm last:border-0">
      <div className="w-48 text-ink-400">{k}</div>
      <div className="mono text-ink-100">{Array.isArray(v) ? v.join(", ") || "—" : v ?? "—"}</div>
    </div>
  );
  return (
    <Card title="Resolver configuration">
      {row("Resolver", d.resolver ?? "glibc (/etc/resolv.conf)")}
      {row("Nameservers", d.nameservers)}
      {d.upstream_nameservers && row("Upstream nameservers", d.upstream_nameservers)}
      {row("Search domains", d.search)}
      {row("Options", d.options)}
      <p className="mt-4 text-xs text-ink-500">Run DNS resolution tests from <Link className="text-emerald-400 hover:underline" to="/tests">Speed & Diagnostics</Link>.</p>
    </Card>
  );
}

function Tests({ agent }: { agent: Agent }) {
  const { data = [] } = useQuery({ queryKey: ["jobs", "agent", agent.id], queryFn: () => api<Job[]>(`/jobs?agent_id=${agent.id}&limit=100`), refetchInterval: 10000 });
  return (
    <Card bodyClass="overflow-x-auto">
      {!data.length ? <Empty>No tests run from this server yet.</Empty> : (
        <table className="table">
          <thead><tr><th>Type</th><th>Target</th><th>Throughput</th><th>RTT</th><th>Loss</th><th>Jitter</th><th>Status</th><th>When</th></tr></thead>
          <tbody>
            {data.map((j) => (
              <tr key={j.id}>
                <td><Link className="font-medium text-ink-100 hover:text-emerald-300" to={`/jobs/${j.id}`}>{j.type}</Link></td>
                <td className="mono">{j.target}</td>
                <td>{fmtBps(j.bps)}</td><td>{fmtMs(j.rtt_avg_ms)}</td><td>{fmtNum(j.loss_percent, 1, "%")}</td><td>{fmtMs(j.jitter_ms)}</td>
                <td><JobStatusBadge status={j.status} /></td><td>{fmtRelative(j.created_at)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

function Settings({ agent }: { agent: Agent }) {
  const qc = useQueryClient();
  const nav = useNavigate();
  const [name, setName] = useState(agent.name);
  const [tags, setTags] = useState(agent.tags.join(", "));
  const [rotated, setRotated] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (body: object) => api<Agent>(`/agents/${agent.id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agent", agent.id] }),
  });
  const rotate = useMutation({
    mutationFn: () => api<{ agent_token: string }>(`/agents/${agent.id}/rotate-token`, { method: "POST" }),
    onSuccess: (r) => setRotated(r.agent_token),
  });
  const del = useMutation({
    mutationFn: () => api(`/agents/${agent.id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["agents"] }); nav("/servers"); },
  });
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <Card title="General">
        <div className="space-y-4">
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
          <Field label="Tags" hint="Comma separated"><input className="input" value={tags} onChange={(e) => setTags(e.target.value)} /></Field>
          <ErrorText error={save.error} />
          <div className="flex gap-2">
            <button className="btn-primary" onClick={() => save.mutate({ name, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) })}>Save</button>
            <button className="btn-ghost" onClick={() => save.mutate({ disabled: !agent.disabled })}>{agent.disabled ? "Enable agent" : "Disable agent"}</button>
          </div>
        </div>
      </Card>
      <Card title="Credentials & removal">
        <div className="space-y-4 text-sm text-ink-300">
          <p>Rotating the credential immediately invalidates the current one. Update <span className="mono">agent_token</span> in <span className="mono">/etc/ipf3/agent.json</span> on the host and restart <span className="mono">ipf3-agent</span>.</p>
          <button className="btn-ghost" onClick={() => confirm("Rotate the agent credential?") && rotate.mutate()}><RefreshCw size={15} />Rotate credential</button>
          {rotated && <CopyBox text={rotated} />}
          <hr className="border-ink-700" />
          <p>Deleting removes the server and all of its metrics, inventory, and test history.</p>
          <button className="btn-danger" onClick={() => confirm(`Delete ${agent.name} and all its data?`) && del.mutate()}><Trash2 size={15} />Delete server</button>
          <ErrorText error={rotate.error || del.error} />
        </div>
      </Card>
    </div>
  );
}

export default function ServerDetail() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const [tab, setTab] = useState<Tab>("overview");
  const [range, setRange] = useState(3600);
  const { data: agent, error } = useQuery({ queryKey: ["agent", id], queryFn: () => api<Agent>(`/agents/${id}`), refetchInterval: 10000 });
  const { data: inv } = useQuery({ queryKey: ["inventory", id], queryFn: () => api<Inventory>(`/agents/${id}/inventory`), refetchInterval: 30000 });
  if (error) return <ErrorText error={error} />;
  if (!agent) return <Spinner />;
  const tabs: { id: Tab; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "interfaces", label: "Interfaces" },
    { id: "routes", label: "Routes" },
    { id: "connections", label: "Connections" },
    { id: "dns", label: "DNS" },
    { id: "tests", label: "Tests" },
    ...(can("admin") ? [{ id: "settings" as Tab, label: "Settings" }] : []),
  ];
  const tools = agent.capabilities.tools ?? {};
  return (
    <>
      <Link to="/servers" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-400 hover:text-ink-200"><ArrowLeft size={14} />Servers</Link>
      <PageHeader
        title={agent.name}
        subtitle={<span className="inline-flex flex-wrap items-center gap-2"><OnlineBadge online={agent.online} disabled={agent.disabled} />{agent.hostname} · {agent.os_name} · kernel {agent.kernel} · agent {agent.agent_version}</span>}
        actions={(tab === "overview" || tab === "interfaces") && <RangePicker value={range} onChange={setRange} />}
      />
      <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 2xl:grid-cols-6">
        <StatTile label="CPU" value={fmtNum(agent.latest?.cpu_percent, 1, "%")} sub={`${agent.cpu_count ?? "?"} vCPU`} />
        <StatTile label="Memory" value={fmtNum(agent.latest?.mem_percent, 1, "%")} sub={fmtBytes(Number(inv?.system?.mem_total ?? 0) || null)} />
        <StatTile label="Receive" value={fmtBps(agent.latest?.rx_bps, 1)} accent />
        <StatTile label="Transmit" value={fmtBps(agent.latest?.tx_bps, 1)} />
        <StatTile label="TCP established" value={agent.latest?.tcp_established ?? "—"} />
        <StatTile label="Uptime" value={fmtDuration(agent.latest?.uptime_seconds)} sub={`seen ${fmtRelative(agent.last_seen_at)}`} />
      </div>
      <div className="mb-4 flex flex-wrap gap-2 text-xs">
        {Object.entries(tools).filter(([k]) => ["iperf3", "ping", "traceroute", "mtr", "dns"].includes(k)).map(([k, v]) => (
          <span key={k} className={`badge ${v ? "bg-ink-750 text-ink-200" : "bg-red-950/40 text-red-300 line-through"}`}>{k}</span>
        ))}
      </div>
      <Tabs tabs={tabs} value={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === "overview" && <Overview agent={agent} range={range} />}
        {tab === "interfaces" && <Interfaces agent={agent} inv={inv} range={range} />}
        {tab === "routes" && <Routes inv={inv} />}
        {tab === "connections" && <Connections inv={inv} />}
        {tab === "dns" && <Dns inv={inv} />}
        {tab === "tests" && <Tests agent={agent} />}
        {tab === "settings" && <Settings agent={agent} />}
      </div>
      {inv?.updated_at && <p className="mt-6 text-xs text-ink-500">Inventory updated {fmtRelative(inv.updated_at)}</p>}
    </>
  );
}
