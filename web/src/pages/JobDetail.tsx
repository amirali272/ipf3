import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Job, JobDetail as JobDetailT } from "../api/types";
import { TimeChart } from "../components/charts";
import { Card, ErrorText, JobStatusBadge, PageHeader, Spinner, StatTile } from "../components/ui";
import { fmtBps, fmtBpsShort, fmtBytes, fmtMs, fmtNum, fmtTime } from "../lib/format";
import { useAuth } from "../lib/auth";

function Iperf({ r }: { r: Record<string, any> }) {
  const udp = r.protocol === "udp";
  const merged = (r.intervals as any[]).map((itv, i) => ({
    t: itv.end,
    bps: itv.bps,
    rev: r.reverse_intervals?.[i]?.bps ?? null,
  }));
  const series = r.bidir
    ? [{ key: "bps", label: "Forward" }, { key: "rev", label: "Reverse" }]
    : [{ key: "bps", label: r.reverse ? "Download" : "Upload" }];
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Receiver throughput" value={fmtBps(r.received_bps)} accent />
        <StatTile label="Sender throughput" value={fmtBps(r.sent_bps)} />
        {udp ? (
          <>
            <StatTile label="Jitter" value={fmtMs(r.jitter_ms)} />
            <StatTile label="Packet loss" value={fmtNum(r.lost_percent, 3, "%")} sub={`${r.lost_packets ?? 0} of ${r.packets ?? 0} datagrams`} />
          </>
        ) : (
          <>
            <StatTile label="Retransmits" value={r.retransmits ?? "—"} />
            <StatTile label="Transferred" value={fmtBytes(r.received_bytes)} sub={`MSS ${r.tcp_mss ?? "?"}`} />
          </>
        )}
      </div>
      {r.bidir && (
        <div className="mt-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
          <StatTile label="Reverse receiver" value={fmtBps(r.reverse_received_bps)} />
          <StatTile label="Reverse retransmits" value={r.reverse_retransmits ?? "—"} />
        </div>
      )}
      <Card title="Throughput per interval" className="mt-6">
        <TimeChart data={merged} xKey="t" area series={series} yFormat={fmtBpsShort} xFormat={(t) => `${Number(t).toFixed(0)}s`} tooltipX={(t) => `t = ${Number(t).toFixed(1)} s`} height={260} />
      </Card>
      <Card title="Connection" className="mt-6">
        <dl className="grid gap-3 text-sm sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Local", `${r.local_host}:${r.local_port}`],
            ["Remote", `${r.remote_host}:${r.remote_port}`],
            ["Protocol", `${r.protocol?.toUpperCase()} × ${r.parallel ?? 1} stream(s)`],
            ["Version", r.version],
            ["CPU local", fmtNum(r.cpu_local_percent, 1, "%")],
            ["CPU remote", fmtNum(r.cpu_remote_percent, 1, "%")],
          ].map(([k, v]) => (
            <div key={k}><dt className="text-xs uppercase tracking-wider text-ink-400">{k}</dt><dd className="mono mt-0.5 text-ink-100">{v ?? "—"}</dd></div>
          ))}
        </dl>
      </Card>
    </>
  );
}

function Ping({ r }: { r: Record<string, any> }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <StatTile label="Average RTT" value={fmtMs(r.avg_ms)} accent />
        <StatTile label="Min / max" value={<span className="text-lg">{fmtMs(r.min_ms)} / {fmtMs(r.max_ms)}</span>} />
        <StatTile label="Jitter" value={fmtMs(r.jitter_ms)} sub="mean |ΔRTT|" />
        <StatTile label="Packet loss" value={<span className={r.loss_percent > 0 ? "text-amber-300" : ""}>{fmtNum(r.loss_percent, 1, "%")}</span>} sub={`${r.received}/${r.transmitted} received`} />
        <StatTile label="Address" value={<span className="mono text-base">{r.address ?? "—"}</span>} />
      </div>
      <Card title="Round-trip time per probe" className="mt-6">
        <TimeChart data={r.replies ?? []} xKey="seq" series={[{ key: "rtt_ms", label: "RTT" }]} yFormat={(v) => `${v.toFixed(1)}`} xFormat={(s) => `#${s}`} tooltipX={(s) => `icmp_seq ${s}`} height={240} empty="No replies received." />
      </Card>
    </>
  );
}

function Hops({ hops, mtr }: { hops: any[]; mtr: boolean }) {
  return (
    <Card title="Hops" bodyClass="overflow-x-auto">
      <table className="table">
        <thead>
          <tr><th>#</th><th>Host</th><th>Loss</th>{mtr ? <><th>Sent</th><th>Last</th><th>Avg</th><th>Best</th><th>Worst</th><th>StDev</th></> : <><th>Min</th><th>Avg</th><th>Max</th><th>Probes</th></>}</tr>
        </thead>
        <tbody>
          {hops.map((h) => (
            <tr key={h.hop}>
              <td className="tabular-nums">{h.hop}</td>
              <td className="mono text-ink-100">{mtr ? h.host : h.addresses.join(", ") || "*"}</td>
              <td className={h.loss_percent > 0 ? "text-amber-300" : ""}>{fmtNum(h.loss_percent, 1, "%")}</td>
              {mtr ? (
                <><td>{h.sent}</td><td>{fmtMs(h.last_ms)}</td><td>{fmtMs(h.avg_ms)}</td><td>{fmtMs(h.best_ms)}</td><td>{fmtMs(h.worst_ms)}</td><td>{fmtMs(h.stdev_ms)}</td></>
              ) : (
                <><td>{fmtMs(h.min_ms)}</td><td>{fmtMs(h.avg_ms)}</td><td>{fmtMs(h.max_ms)}</td>
                  <td className="mono text-xs">{h.probes.map((p: any) => (p.rtt_ms == null ? "*" : `${p.rtt_ms}${p.flag ? " " + p.flag : ""}`)).join("  ")}</td></>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function Dns({ r }: { r: Record<string, any> }) {
  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile label="Query time" value={fmtMs(r.time_ms)} accent />
        <StatTile label="Response code" value={<span className={r.rcode === "NOERROR" ? "" : "text-amber-300"}>{r.rcode}</span>} />
        <StatTile label="Resolver" value={<span className="mono text-base">{r.server}</span>} sub={r.protocol?.toUpperCase()} />
        <StatTile label="Answers" value={r.answers.length} />
      </div>
      <Card title="Answer section" className="mt-6" bodyClass="overflow-x-auto">
        <table className="table">
          <thead><tr><th>Name</th><th>TTL</th><th>Type</th><th>Value</th></tr></thead>
          <tbody>{r.answers.map((a: any, i: number) => <tr key={i}><td className="mono">{a.name}</td><td>{a.ttl}</td><td>{a.type}</td><td className="mono break-all">{a.value}</td></tr>)}</tbody>
        </table>
      </Card>
    </>
  );
}

export default function JobDetail() {
  const { id = "" } = useParams();
  const { can } = useAuth();
  const qc = useQueryClient();
  const nav = useNavigate();
  const [showRaw, setShowRaw] = useState(false);
  const { data: job, error } = useQuery({
    queryKey: ["job", id],
    queryFn: () => api<JobDetailT>(`/jobs/${id}`),
    refetchInterval: (q) => (q.state.data && ["queued", "running"].includes(q.state.data.status) ? 1500 : false),
  });
  const cancel = useMutation({
    mutationFn: () => api(`/jobs/${id}/cancel`, { method: "POST" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", id] }),
  });
  const rerun = useMutation({
    mutationFn: () => api<Job>("/jobs", { method: "POST", json: { agent_id: job!.agent_id, type: job!.type, params: job!.params } }),
    onSuccess: (j) => nav(`/jobs/${j.id}`),
  });
  if (error) return <ErrorText error={error} />;
  if (!job) return <Spinner />;
  const pending = job.status === "queued" || job.status === "running";
  const r = job.result;
  return (
    <>
      <Link to="/tests" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-400 hover:text-ink-200"><ArrowLeft size={14} />Tests</Link>
      <PageHeader
        title={`${job.type} → ${job.target}`}
        subtitle={<span className="inline-flex flex-wrap items-center gap-2"><JobStatusBadge status={job.status} />from <Link className="text-emerald-400 hover:underline" to={`/servers/${job.agent_id}`}>{job.agent_name}</Link> · created {fmtTime(job.created_at)}{job.finished_at && ` · finished ${fmtTime(job.finished_at)}`}</span>}
        actions={can("operator") && (
          <>
            {pending && <button className="btn-ghost" onClick={() => cancel.mutate()}><Ban size={15} />Cancel</button>}
            {!pending && <button className="btn-ghost" onClick={() => rerun.mutate()}><RotateCcw size={15} />Run again</button>}
          </>
        )}
      />
      <ErrorText error={cancel.error || rerun.error} />
      {pending && <Spinner label={job.status === "queued" ? "Waiting for the agent to pick up the job…" : "Test running on the agent…"} />}
      {job.error && <div className="mb-6"><ErrorText error={job.error} /></div>}
      {r && job.type === "iperf3" && <Iperf r={r} />}
      {r && job.type === "ping" && <Ping r={r} />}
      {r && job.type === "traceroute" && <><div className="mb-4 text-sm text-ink-300">Destination {r.destination} {r.reached ? <span className="text-emerald-400">reached</span> : <span className="text-amber-300">not reached</span>} in {r.hop_count} hops</div><Hops hops={r.hops} mtr={false} /></>}
      {r && job.type === "mtr" && <Hops hops={r.hops} mtr />}
      {r && job.type === "dns" && <Dns r={r} />}
      <Card title="Parameters" className="mt-6"><pre className="mono overflow-x-auto text-ink-300">{JSON.stringify(job.params, null, 2)}</pre></Card>
      {job.raw && (
        <Card title="Raw tool output" className="mt-6" actions={<button className="text-xs text-emerald-400" onClick={() => setShowRaw(!showRaw)}>{showRaw ? "Hide" : "Show"}</button>}>
          {showRaw ? <pre className="mono max-h-[500px] overflow-auto whitespace-pre text-ink-300">{job.raw}</pre> : <p className="text-sm text-ink-500">Exact output reported by the agent; results above are parsed from it on the server.</p>}
        </Card>
      )}
    </>
  );
}
