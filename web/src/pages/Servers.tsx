import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Agent, EnrollmentToken } from "../api/types";
import { Card, Empty, ErrorText, Field, Modal, OnlineBadge, PageHeader, Spinner } from "../components/ui";
import { fmtBps, fmtDuration, fmtNum, fmtRelative, fmtTime } from "../lib/format";
import { useAuth } from "../lib/auth";

export function CopyBox({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="relative">
      <pre className="mono overflow-x-auto whitespace-pre-wrap break-all rounded-lg border border-ink-700 bg-ink-950 p-3 pr-10 text-emerald-300">{text}</pre>
      <button
        className="absolute right-2 top-2 rounded-md p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100"
        onClick={() => navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })}
        aria-label="Copy"
      >
        {copied ? <span className="text-xs text-emerald-400">✓</span> : <Copy size={14} />}
      </button>
    </div>
  );
}

function EnrollModal({ open, onClose }: { open: boolean; onClose: () => void }) {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [ttl, setTtl] = useState(24);
  const [created, setCreated] = useState<EnrollmentToken | null>(null);
  const create = useMutation({
    mutationFn: () => api<EnrollmentToken>("/enrollment-tokens", { method: "POST", json: { note, ttl_hours: ttl } }),
    onSuccess: (t) => { setCreated(t); qc.invalidateQueries({ queryKey: ["enrollment-tokens"] }); },
  });
  const close = () => { setCreated(null); setNote(""); create.reset(); onClose(); };
  const origin = window.location.origin;
  return (
    <Modal open={open} onClose={close} title="Enroll a server" wide>
      {!created ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-300">
            Create a one-time enrollment token, then run the installer on the Ubuntu server. The token can be used once and
            expires automatically; the agent receives its own long-lived credential during enrollment.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Note"><input className="input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. fra1-edge-03" maxLength={255} /></Field>
            <Field label="Valid for (hours)"><input className="input" type="number" min={1} max={720} value={ttl} onChange={(e) => setTtl(+e.target.value)} /></Field>
          </div>
          <ErrorText error={create.error} />
          <div className="flex justify-end"><button className="btn-primary" onClick={() => create.mutate()} disabled={create.isPending}><KeyRound size={15} />Create token</button></div>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-amber-300">This token is shown only once. It expires {fmtTime(created.expires_at)}.</p>
          <CopyBox text={created.token ?? ""} />
          <p className="text-sm text-ink-300">
            On the new server (Ubuntu 22.04/24.04), run the installer and choose <b className="text-ink-100">3 — Add this server to an existing panel</b>.
            When asked, enter <span className="mono text-emerald-300">{origin}</span> and the token above.
          </p>
          <CopyBox text={`bash <(curl -fsSL https://raw.githubusercontent.com/amirali272/ipf3/claude/gracious-ramanujan-enb5r9/install.sh)`} />
          <p className="text-sm text-ink-300">Or non-interactively, from a checkout of the repository:</p>
          <CopyBox text={`sudo ./deploy/install-agent.sh --server ${origin} --token ${created.token} --name $(hostname -s)`} />
          <p className="text-xs text-ink-400">Add <span className="mono">--iperf3-server</span> to also run an iperf3 endpoint on that host, and <span className="mono">--ca-file /path/ca.pem</span> if this panel uses a self-signed certificate.</p>
          <div className="flex justify-end"><button className="btn-ghost" onClick={close}>Done</button></div>
        </div>
      )}
    </Modal>
  );
}

function TokensCard() {
  const qc = useQueryClient();
  const { data = [] } = useQuery({ queryKey: ["enrollment-tokens"], queryFn: () => api<EnrollmentToken[]>("/enrollment-tokens") });
  const del = useMutation({
    mutationFn: (id: number) => api(`/enrollment-tokens/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["enrollment-tokens"] }),
  });
  const now = Date.now();
  return (
    <Card title="Enrollment tokens" className="mt-6" bodyClass="overflow-x-auto">
      {data.length === 0 ? <Empty>No enrollment tokens.</Empty> : (
        <table className="table">
          <thead><tr><th>Note</th><th>Created</th><th>Expires</th><th>Status</th><th /></tr></thead>
          <tbody>
            {data.map((t) => {
              const status = t.used_at ? "used" : new Date(t.expires_at).getTime() < now ? "expired" : "active";
              return (
                <tr key={t.id}>
                  <td>{t.note || <span className="text-ink-500">—</span>}</td>
                  <td>{fmtTime(t.created_at)}</td>
                  <td>{fmtTime(t.expires_at)}</td>
                  <td><span className={`badge ${status === "active" ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`}>{status}</span></td>
                  <td className="text-right"><button className="text-ink-400 hover:text-red-300" onClick={() => del.mutate(t.id)} aria-label="Revoke"><Trash2 size={15} /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}

export default function Servers() {
  const { can } = useAuth();
  const [enroll, setEnroll] = useState(false);
  const { data, isLoading } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents"), refetchInterval: 10000 });
  return (
    <>
      <PageHeader
        title="Servers"
        subtitle="Ubuntu hosts running ipf3-agent"
        actions={can("admin") && <button className="btn-primary" onClick={() => setEnroll(true)}><Plus size={15} />Enroll server</button>}
      />
      <Card bodyClass="overflow-x-auto">
        {isLoading ? <Spinner /> : !data?.length ? <Empty>No servers enrolled.</Empty> : (
          <table className="table">
            <thead>
              <tr><th>Name</th><th>Status</th><th>OS / kernel</th><th>CPU</th><th>Mem</th><th>RX</th><th>TX</th><th>Uptime</th><th>Agent</th><th>Last seen</th></tr>
            </thead>
            <tbody>
              {data.map((a) => (
                <tr key={a.id}>
                  <td>
                    <Link className="font-medium text-ink-100 hover:text-emerald-300" to={`/servers/${a.id}`}>{a.name}</Link>
                    <div className="text-xs text-ink-500">{a.remote_addr}</div>
                  </td>
                  <td><OnlineBadge online={a.online} disabled={a.disabled} /></td>
                  <td className="text-xs">{a.os_name}<div className="text-ink-500">{a.kernel}</div></td>
                  <td className="tabular-nums">{fmtNum(a.latest?.cpu_percent, 0, "%")}</td>
                  <td className="tabular-nums">{fmtNum(a.latest?.mem_percent, 0, "%")}</td>
                  <td className="tabular-nums">{fmtBps(a.latest?.rx_bps, 1)}</td>
                  <td className="tabular-nums">{fmtBps(a.latest?.tx_bps, 1)}</td>
                  <td>{fmtDuration(a.latest?.uptime_seconds)}</td>
                  <td className="mono">{a.agent_version}</td>
                  <td>{fmtRelative(a.last_seen_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {can("admin") && <TokensCard />}
      <EnrollModal open={enroll} onClose={() => setEnroll(false)} />
    </>
  );
}
