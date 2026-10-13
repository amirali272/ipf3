import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pause, Play, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Agent, JobType, Schedule } from "../api/types";
import { Card, Empty, ErrorText, Field, Modal, PageHeader } from "../components/ui";
import { fmtDuration, fmtRelative } from "../lib/format";
import { useAuth } from "../lib/auth";
import { JobForm, TYPE_TABS, toApiParams } from "./Tests";

const DEFAULTS: Record<JobType, Record<string, string | number | boolean | null>> = {
  iperf3: { target: "", port: 5201, protocol: "tcp", duration: 10, parallel: 1, direction: "forward", bitrate_mbps: "", omit: 1, ipv6: false },
  ping: { target: "", count: 20, interval: 1, packet_size: 56, ipv6: false },
  traceroute: { target: "", max_hops: 30, queries: 3, protocol: "udp", ipv6: false },
  mtr: { target: "", count: 10, max_hops: 30, protocol: "icmp", ipv6: false },
  dns: { name: "", record_type: "A", server: "", protocol: "udp", timeout: 5 },
};

function CreateModal({ open, onClose, agents }: { open: boolean; onClose: () => void; agents: Agent[] }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [agentId, setAgentId] = useState("");
  const [type, setType] = useState<JobType>("ping");
  const [params, setParams] = useState(DEFAULTS.ping);
  const [interval, setInterval] = useState(300);
  const create = useMutation({
    mutationFn: () =>
      api<Schedule>("/schedules", {
        method: "POST",
        json: { name, agent_id: agentId || agents[0]?.id, type, params: toApiParams(type, params), interval_seconds: interval },
      }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["schedules"] }); onClose(); },
  });
  return (
    <Modal open={open} onClose={onClose} title="New scheduled test" wide>
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="Name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="Cloudflare latency" /></Field>
          <Field label="Server">
            <select className="input" value={agentId || agents[0]?.id} onChange={(e) => setAgentId(e.target.value)}>
              {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
            </select>
          </Field>
          <Field label="Type">
            <select className="input" value={type} onChange={(e) => { const t = e.target.value as JobType; setType(t); setParams(DEFAULTS[t]); }}>
              {TYPE_TABS.map((t) => <option key={t.id} value={t.id}>{t.label}</option>)}
            </select>
          </Field>
          <Field label="Every (seconds)" hint={type === "iperf3" ? "Minimum 300 s for bandwidth tests" : "Minimum 30 s"}>
            <input className="input" type="number" min={type === "iperf3" ? 300 : 30} value={interval} onChange={(e) => setInterval(+e.target.value)} />
          </Field>
        </div>
        <JobForm type={type} params={params} setParams={setParams} />
        <ErrorText error={create.error} />
        <div className="flex justify-end"><button className="btn-primary" onClick={() => create.mutate()} disabled={create.isPending || !name}>Create schedule</button></div>
      </div>
    </Modal>
  );
}

export default function Schedules() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data = [] } = useQuery({ queryKey: ["schedules"], queryFn: () => api<Schedule[]>("/schedules"), refetchInterval: 15000 });
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  const names = new Map(agents.map((a) => [a.id, a.name]));
  const patch = useMutation({
    mutationFn: ({ id, body }: { id: number; body: object }) => api(`/schedules/${id}`, { method: "PATCH", json: body }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  const del = useMutation({
    mutationFn: (id: number) => api(`/schedules/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["schedules"] }),
  });
  return (
    <>
      <PageHeader
        title="Schedules"
        subtitle="Recurring tests feed historical analytics and alert rules"
        actions={can("operator") && <button className="btn-primary" onClick={() => setOpen(true)} disabled={!agents.length}><Plus size={15} />New schedule</button>}
      />
      <Card bodyClass="overflow-x-auto">
        {!data.length ? <Empty>No scheduled tests.</Empty> : (
          <table className="table">
            <thead><tr><th>Name</th><th>Server</th><th>Type</th><th>Target</th><th>Every</th><th>Last run</th><th>State</th><th /></tr></thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id}>
                  <td className="font-medium text-ink-100"><Link className="hover:text-emerald-300" to={`/analytics?type=${s.type}&agent=${s.agent_id}&target=${encodeURIComponent(String(s.params.target ?? s.params.name ?? ""))}`}>{s.name}</Link></td>
                  <td>{names.get(s.agent_id)}</td>
                  <td>{s.type}</td>
                  <td className="mono">{String(s.params.target ?? s.params.name)}</td>
                  <td>{fmtDuration(s.interval_seconds)}</td>
                  <td>{fmtRelative(s.last_run_at)}</td>
                  <td><span className={`badge ${s.enabled ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`}>{s.enabled ? "active" : "paused"}</span></td>
                  <td className="whitespace-nowrap text-right">
                    {can("operator") && (
                      <>
                        <button className="mr-3 text-ink-400 hover:text-ink-100" onClick={() => patch.mutate({ id: s.id, body: { enabled: !s.enabled } })} aria-label={s.enabled ? "Pause" : "Resume"}>
                          {s.enabled ? <Pause size={15} /> : <Play size={15} />}
                        </button>
                        <button className="text-ink-400 hover:text-red-300" onClick={() => confirm(`Delete schedule ${s.name}?`) && del.mutate(s.id)} aria-label="Delete"><Trash2 size={15} /></button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {open && <CreateModal open={open} onClose={() => setOpen(false)} agents={agents.filter((a) => !a.disabled)} />}
    </>
  );
}
