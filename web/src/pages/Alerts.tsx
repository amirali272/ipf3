import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { Agent, AlertEvent, AlertRule, Severity } from "../api/types";
import { Card, Empty, ErrorText, Field, Modal, PageHeader, SeverityBadge, Tabs } from "../components/ui";
import { fmtBps, fmtDuration, fmtRelative, fmtTime } from "../lib/format";
import { useAuth } from "../lib/auth";

type RuleForm = Omit<AlertRule, "id" | "created_at">;
const EMPTY: RuleForm = {
  name: "", metric: "cpu_percent", operator: ">", threshold: 90, for_seconds: 300, agent_id: null, iface: null, target: null,
  severity: "warning", enabled: true, webhook_url: null, email_to: null,
};

function fmtValue(metric: string | null, v: number | null) {
  if (v == null) return "—";
  if (metric?.endsWith("_bps")) return fmtBps(v);
  return v.toFixed(2);
}

function RuleModal({ rule, onClose, agents }: { rule: AlertRule | "new"; onClose: () => void; agents: Agent[] }) {
  const qc = useQueryClient();
  const { data: metrics = {} } = useQuery({ queryKey: ["alert-metrics"], queryFn: () => api<Record<string, string>>("/alerts/metrics") });
  const [f, setF] = useState<RuleForm>(rule === "new" ? EMPTY : { ...rule });
  const set = <K extends keyof RuleForm>(k: K, v: RuleForm[K]) => setF({ ...f, [k]: v });
  const save = useMutation({
    mutationFn: () =>
      rule === "new"
        ? api("/alerts/rules", { method: "POST", json: f })
        : api(`/alerts/rules/${rule.id}`, { method: "PATCH", json: f }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["alert-rules"] }); onClose(); },
  });
  const isIface = f.metric.startsWith("iface_");
  const isTest = /^(ping|iperf3|dns|job)_/.test(f.metric);
  const nullable = (v: string) => (v.trim() === "" ? null : v.trim());
  return (
    <Modal open onClose={onClose} title={rule === "new" ? "New alert rule" : `Edit ${rule.name}`} wide>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={f.name} onChange={(e) => set("name", e.target.value)} /></Field>
          <Field label="Metric">
            <select className="input" value={f.metric} onChange={(e) => set("metric", e.target.value)}>
              {Object.entries(metrics).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-4">
          <Field label="Condition">
            <select className="input" value={f.operator} onChange={(e) => set("operator", e.target.value)}>
              {[">", ">=", "<", "<=", "=="].map((o) => <option key={o}>{o}</option>)}
            </select>
          </Field>
          <Field label="Threshold" hint={f.metric.endsWith("_bps") ? "bits per second" : undefined}>
            <input className="input" type="number" step="any" value={f.threshold} onChange={(e) => set("threshold", Number(e.target.value))} />
          </Field>
          <Field label="Sustained for (s)" hint={isTest ? "Window (min 900 s for tests)" : "Must hold for every sample"}>
            <input className="input" type="number" min={0} value={f.for_seconds} onChange={(e) => set("for_seconds", Number(e.target.value))} />
          </Field>
          <Field label="Severity">
            <select className="input" value={f.severity} onChange={(e) => set("severity", e.target.value as Severity)}>
              {["info", "warning", "critical"].map((s) => <option key={s}>{s}</option>)}
            </select>
          </Field>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          <Field label="Server">
            <select className="input" value={f.agent_id ?? ""} onChange={(e) => set("agent_id", e.target.value || null)}>
              <option value="">All servers</option>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          {isIface && <Field label="Interface" hint="Empty = all interfaces"><input className="input mono" value={f.iface ?? ""} onChange={(e) => set("iface", nullable(e.target.value))} /></Field>}
          {isTest && <Field label="Test target" hint="Empty = any target"><input className="input mono" value={f.target ?? ""} onChange={(e) => set("target", nullable(e.target.value))} /></Field>}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Webhook URL" hint="JSON POST; Slack/Mattermost compatible 'text' field"><input className="input mono" value={f.webhook_url ?? ""} onChange={(e) => set("webhook_url", nullable(e.target.value))} placeholder="https://hooks.slack.com/…" /></Field>
          <Field label="Email recipients" hint="Comma separated; requires SMTP settings"><input className="input" value={f.email_to ?? ""} onChange={(e) => set("email_to", nullable(e.target.value))} /></Field>
        </div>
        <label className="flex items-center gap-2 text-sm text-ink-300"><input type="checkbox" className="accent-emerald-500" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} />Enabled</label>
        <ErrorText error={save.error} />
        <div className="flex justify-end"><button className="btn-primary" onClick={() => save.mutate()} disabled={!f.name || save.isPending}>Save rule</button></div>
      </div>
    </Modal>
  );
}

export default function Alerts() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"events" | "rules">("events");
  const [state, setState] = useState<"" | "firing" | "resolved">("firing");
  const [editing, setEditing] = useState<AlertRule | "new" | null>(null);
  const { data: events = [] } = useQuery({ queryKey: ["alert-events", state], queryFn: () => api<AlertEvent[]>(`/alerts/events?limit=300${state ? `&state=${state}` : ""}`), refetchInterval: 15000 });
  const { data: rules = [] } = useQuery({ queryKey: ["alert-rules"], queryFn: () => api<AlertRule[]>("/alerts/rules") });
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  const names = new Map(agents.map((a) => [a.id, a.name]));
  const ack = useMutation({ mutationFn: (id: number) => api(`/alerts/events/${id}/ack`, { method: "POST" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-events"] }) });
  const del = useMutation({ mutationFn: (id: number) => api(`/alerts/rules/${id}`, { method: "DELETE" }), onSuccess: () => qc.invalidateQueries({ queryKey: ["alert-rules"] }) });

  return (
    <>
      <PageHeader title="Alerts" subtitle="Rules are evaluated every 30 seconds against stored telemetry and test results"
        actions={tab === "rules" && can("admin") && <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} />New rule</button>} />
      <Tabs tabs={[{ id: "events", label: "Events" }, { id: "rules", label: `Rules (${rules.length})` }]} value={tab} onChange={setTab} />
      <div className="mt-6">
        {tab === "events" ? (
          <Card bodyClass="overflow-x-auto" actions={
            <select className="input w-36" value={state} onChange={(e) => setState(e.target.value as typeof state)}>
              <option value="firing">Firing</option><option value="resolved">Resolved</option><option value="">All</option>
            </select>} title="Alert events">
            {!events.length ? <Empty>{state === "firing" ? "No alerts firing." : "No events."}</Empty> : (
              <table className="table">
                <thead><tr><th>Severity</th><th>Message</th><th>Value</th><th>Started</th><th>Duration</th><th>State</th><th /></tr></thead>
                <tbody>
                  {events.map((e) => (
                    <tr key={e.id}>
                      <td><SeverityBadge severity={e.severity} /></td>
                      <td className="max-w-xl text-ink-100">{e.message}</td>
                      <td className="tabular-nums">{fmtValue(e.metric, e.value)}</td>
                      <td className="whitespace-nowrap">{fmtTime(e.started_at)}</td>
                      <td>{fmtDuration(((e.resolved_at ? new Date(e.resolved_at).getTime() : Date.now()) - new Date(e.started_at).getTime()) / 1000)}</td>
                      <td>
                        <span className={`badge ${e.state === "firing" ? "bg-red-950/60 text-red-300" : "bg-ink-750 text-ink-300"}`}>{e.state}</span>
                        {e.acknowledged_at && <span className="ml-1 badge bg-ink-750 text-ink-400" title={fmtTime(e.acknowledged_at)}>ack</span>}
                      </td>
                      <td className="text-right">
                        {can("operator") && !e.acknowledged_at && e.state === "firing" && (
                          <button className="btn-ghost px-2 py-1 text-xs" onClick={() => ack.mutate(e.id)}><Check size={13} />Ack</button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        ) : (
          <Card bodyClass="overflow-x-auto">
            {!rules.length ? <Empty>No alert rules defined.</Empty> : (
              <table className="table">
                <thead><tr><th>Name</th><th>Condition</th><th>Scope</th><th>Severity</th><th>Notify</th><th>State</th><th /></tr></thead>
                <tbody>
                  {rules.map((r) => (
                    <tr key={r.id}>
                      <td className="font-medium text-ink-100">{r.name}</td>
                      <td className="mono">{r.metric} {r.operator} {fmtValue(r.metric, r.threshold)} <span className="text-ink-500">for {fmtDuration(r.for_seconds)}</span></td>
                      <td>{r.agent_id ? names.get(r.agent_id) : "all servers"}{r.iface && <span className="mono"> · {r.iface}</span>}{r.target && <span className="mono"> · {r.target}</span>}</td>
                      <td><SeverityBadge severity={r.severity} /></td>
                      <td className="text-xs">{[r.webhook_url && "webhook", r.email_to && "email"].filter(Boolean).join(", ") || "—"}</td>
                      <td><span className={`badge ${r.enabled ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`}>{r.enabled ? "enabled" : "disabled"}</span></td>
                      <td className="whitespace-nowrap text-right">
                        {can("admin") && (
                          <>
                            <button className="mr-3 text-ink-400 hover:text-ink-100" onClick={() => setEditing(r)} aria-label="Edit"><Pencil size={15} /></button>
                            <button className="text-ink-400 hover:text-red-300" onClick={() => confirm(`Delete rule ${r.name}?`) && del.mutate(r.id)} aria-label="Delete"><Trash2 size={15} /></button>
                          </>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>
        )}
      </div>
      {editing && <RuleModal rule={editing} onClose={() => setEditing(null)} agents={agents} />}
      <p className="mt-4 text-xs text-ink-500">Last refreshed {fmtRelative(new Date().toISOString())}</p>
    </>
  );
}
