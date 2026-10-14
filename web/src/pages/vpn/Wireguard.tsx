import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Download, Edit3, KeyRound, Plus, QrCode as QrIcon, Radio, Trash2, Users } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api } from "../../api/client";
import type { Agent, Inventory, VpnUser, WgInbound, WgPeer } from "../../api/types";
import { Empty, ErrorText, Field, Modal } from "../../components/ui";
import { CopyButton, QrCode, Switch } from "../../components/vpn";
import { fmtRelative, fmtTraffic } from "../../lib/format";
import { useAuth } from "../../lib/auth";

const CIDR_PRESETS = ["10.70.0.0/24", "10.71.0.0/24", "10.8.0.0/24"];

function nextFreeCidr(used: string[]): string {
  return CIDR_PRESETS.find((c) => !used.includes(c)) ?? `10.${70 + used.length}.0.0/24`;
}

// ============================================================================ create/edit inbound
function InboundModal({ inbound, nodes, onClose }: { inbound: WgInbound | "new"; nodes: Agent[]; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = inbound === "new";
  const { data: usedNetworks = [] } = useQuery({ queryKey: ["vpn-wg-inbounds"], queryFn: () => api<WgInbound[]>("/vpn/wg/inbounds"), select: (d) => d.map((i) => i.network) });
  const [agentId, setAgentId] = useState(isNew ? nodes[0]?.id ?? "" : inbound.agent_id);
  const [remark, setRemark] = useState(isNew ? "WireGuard" : inbound.remark);
  const [port, setPort] = useState(isNew ? 51820 : inbound.listen_port);
  const [network, setNetwork] = useState(isNew ? nextFreeCidr(usedNetworks) : inbound.network);
  const [address, setAddress] = useState(isNew ? "" : inbound.address);
  const [dns, setDns] = useState(isNew ? "1.1.1.1" : inbound.dns);
  const [egress, setEgress] = useState(isNew ? "" : inbound.egress_iface);
  const [enabled, setEnabled] = useState(isNew ? true : inbound.enabled);

  const { data: inventory } = useQuery({
    queryKey: ["agent-inventory", agentId],
    queryFn: () => api<Inventory>(`/agents/${agentId}/inventory`),
    enabled: !!agentId,
  });
  const ifaceNames = useMemo(() => (inventory?.interfaces ?? []).map((i) => i.name).filter((n) => n !== "lo" && !n.startsWith("wg")), [inventory]);

  const save = useMutation({
    mutationFn: () => {
      const body = { agent_id: agentId, remark, listen_port: port, network, address, dns, mtu: 1420, persistent_keepalive: 25, egress_iface: egress, enabled };
      return isNew ? api("/vpn/wg/inbounds", { method: "POST", json: body }) : api(`/vpn/wg/inbounds/${inbound.agent_id}`, { method: "PUT", json: body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-wg-inbounds"] });
      onClose();
    },
  });

  return (
    <Modal open onClose={onClose} title={isNew ? "Add WireGuard inbound" : `Edit ${inbound.remark}`} wide>
      <div className="space-y-4">
        <p className="text-sm text-ink-400">One WireGuard interface (wg0) per node. Peers are added separately, per user.</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Node">
            <select className="input" value={agentId} onChange={(e) => setAgentId(e.target.value)} disabled={!isNew}>
              {nodes.length === 0 && <option value="">No nodes available</option>}
              {nodes.map((n) => <option key={n.id} value={n.id}>{n.name}{n.capabilities?.tools?.wireguard ? "" : " (WireGuard not installed)"}</option>)}
            </select>
          </Field>
          <Field label="Name"><input className="input" value={remark} onChange={(e) => setRemark(e.target.value)} maxLength={128} /></Field>
          <Field label="Listen port (UDP)"><input className="input" type="number" min={1} max={65535} value={port} onChange={(e) => setPort(+e.target.value)} /></Field>
          <Field label="Peer network (CIDR)" hint="Private range for peer IPs, e.g. 10.70.0.0/24"><input className="input mono" value={network} onChange={(e) => setNetwork(e.target.value)} /></Field>
          <Field label="Public address" hint="Domain or IP clients connect to"><input className="input" value={address} onChange={(e) => setAddress(e.target.value)} placeholder="vpn.example.com" /></Field>
          <Field label="DNS pushed to clients"><input className="input" value={dns} onChange={(e) => setDns(e.target.value)} placeholder="1.1.1.1" /></Field>
          <Field label="Egress interface" hint="Outbound NIC for NAT (auto-detected if left blank)">
            <select className="input" value={egress} onChange={(e) => setEgress(e.target.value)}>
              <option value="">Auto-detect</option>
              {ifaceNames.map((n) => <option key={n} value={n}>{n}</option>)}
            </select>
          </Field>
          <Field label="Status">
            <label className="flex h-10 items-center gap-3 text-sm text-ink-300"><Switch on={enabled} onChange={() => setEnabled(!enabled)} />{enabled ? "Enabled" : "Disabled"}</label>
          </Field>
        </div>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending || !agentId || !address} onClick={() => save.mutate()}>{isNew ? "Add inbound" : "Save"}</button>
        </div>
      </div>
    </Modal>
  );
}

// ============================================================================ add peer
function AddPeerModal({ agentId, existingUserIds, onClose }: { agentId: string; existingUserIds: number[]; onClose: () => void }) {
  const qc = useQueryClient();
  const { data: users = [] } = useQuery({ queryKey: ["vpn-users-all"], queryFn: () => api<VpnUser[]>("/vpn/users") });
  const available = users.filter((u) => !existingUserIds.includes(u.id));
  const [userId, setUserId] = useState<number | "">("");
  useEffect(() => {
    if (userId === "" && available.length > 0) setUserId(available[0].id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [available.length]);
  const create = useMutation({
    mutationFn: () => api(`/vpn/wg/inbounds/${agentId}/peers`, { method: "POST", json: { user_id: userId } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-wg-peers", agentId] });
      qc.invalidateQueries({ queryKey: ["vpn-wg-inbounds"] });
      onClose();
    },
  });
  return (
    <Modal open onClose={onClose} title="Add peer">
      <div className="space-y-4">
        {available.length === 0 ? (
          <Empty>Every existing user already has a peer here.</Empty>
        ) : (
          <Field label="User">
            <select className="input" value={userId} onChange={(e) => setUserId(+e.target.value)}>
              {available.map((u) => <option key={u.id} value={u.id}>{u.username}</option>)}
            </select>
          </Field>
        )}
        <ErrorText error={create.error} />
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={create.isPending || !userId} onClick={() => create.mutate()}><KeyRound size={15} />Add peer</button>
        </div>
      </div>
    </Modal>
  );
}

// ============================================================================ peer config / QR
function PeerConfigModal({ peer, onClose }: { peer: WgPeer; onClose: () => void }) {
  const { data, isLoading } = useQuery({ queryKey: ["vpn-wg-peer-config", peer.id], queryFn: () => api<{ config: string; qr_text: string }>(`/vpn/wg/peers/${peer.id}/config`) });
  const download = () => {
    if (!data) return;
    const blob = new Blob([data.config], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${peer.username}-${peer.address}.conf`;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Modal open onClose={onClose} title={`WireGuard config — ${peer.username}`} wide>
      {isLoading || !data ? (
        <div className="py-8 text-center text-sm text-ink-400">Loading…</div>
      ) : (
        <div className="grid gap-6 sm:grid-cols-[auto_1fr]">
          <div className="flex flex-col items-center gap-2">
            <QrCode text={data.qr_text} size={200} />
            <span className="text-[11px] text-ink-500">Scan in the WireGuard app</span>
          </div>
          <div className="min-w-0 space-y-3">
            <textarea readOnly className="input mono min-h-[180px] w-full text-xs" value={data.config} onFocus={(e) => e.target.select()} spellCheck={false} />
            <div className="flex gap-2">
              <CopyButton text={data.config} label="Copy config" />
              <button className="btn-ghost" onClick={download}><Download size={15} />Download .conf</button>
            </div>
          </div>
        </div>
      )}
    </Modal>
  );
}

// ============================================================================ peers list
function PeersPanel({ inbound, canEdit }: { inbound: WgInbound; canEdit: boolean }) {
  const qc = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [viewing, setViewing] = useState<WgPeer | null>(null);
  const { data: peers = [] } = useQuery({ queryKey: ["vpn-wg-peers", inbound.agent_id], queryFn: () => api<WgPeer[]>(`/vpn/wg/inbounds/${inbound.agent_id}/peers`), refetchInterval: 10000 });
  const del = useMutation({
    mutationFn: (id: number) => api(`/vpn/wg/peers/${id}`, { method: "DELETE" }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["vpn-wg-peers", inbound.agent_id] }); qc.invalidateQueries({ queryKey: ["vpn-wg-inbounds"] }); },
  });
  const toggle = useMutation({
    mutationFn: (id: number) => api(`/vpn/wg/peers/${id}/toggle`, { method: "PATCH" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-wg-peers", inbound.agent_id] }),
  });
  return (
    <div className="mt-4 border-t border-ink-800 pt-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-ink-400"><Users size={13} />Peers ({peers.length})</div>
        {canEdit && <button className="text-xs font-medium text-emerald-300 hover:text-emerald-200" onClick={() => setAdding(true)}>+ Add peer</button>}
      </div>
      {peers.length === 0 ? (
        <p className="text-sm text-ink-500">No peers yet.</p>
      ) : (
        <ul className="space-y-1.5">
          {peers.map((p) => (
            <li key={p.id} className={`flex items-center gap-3 rounded-lg border border-ink-700/70 bg-ink-900/60 px-3 py-2 ${p.enabled ? "" : "opacity-50"}`}>
              <span className={`h-2 w-2 shrink-0 rounded-full ${p.online ? "animate-pulse bg-emerald-400" : "bg-ink-600"}`} />
              <div className="min-w-0 flex-1">
                <div className="truncate text-sm font-medium text-ink-100">{p.username}</div>
                <div className="font-mono text-[11px] text-ink-500">{p.address} · {p.last_handshake_at ? fmtRelative(p.last_handshake_at) : "never connected"}</div>
              </div>
              <div className="shrink-0 text-right text-[11px] text-ink-500">↓ {fmtTraffic(p.down)} · ↑ {fmtTraffic(p.up)}</div>
              <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100" onClick={() => setViewing(p)} aria-label="View config"><QrIcon size={15} /></button>
              {canEdit && (
                <>
                  <Switch on={p.enabled} onChange={() => toggle.mutate(p.id)} />
                  <button className="rounded-lg p-1.5 text-ink-400 hover:bg-red-950/50 hover:text-red-300" onClick={() => confirm(`Remove ${p.username}'s peer?`) && del.mutate(p.id)} aria-label="Delete"><Trash2 size={15} /></button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      <ErrorText error={del.error || toggle.error} />
      {adding && <AddPeerModal agentId={inbound.agent_id} existingUserIds={peers.map((p) => p.user_id)} onClose={() => setAdding(false)} />}
      {viewing && <PeerConfigModal peer={viewing} onClose={() => setViewing(null)} />}
    </div>
  );
}

// ============================================================================ inbound card
function InboundCard({ i, canEdit, onEdit, onDelete }: { i: WgInbound; canEdit: boolean; onEdit: () => void; onDelete: () => void }) {
  const [open, setOpen] = useState(false);
  const state = !i.online ? "offline" : i.error ? "error" : !i.running ? "stopped" : !i.in_sync ? "syncing" : "ok";
  const meta = {
    ok: { tone: "text-emerald-300", label: "Running · in sync", dot: "bg-emerald-400" },
    syncing: { tone: "text-sky-300", label: "Applying changes…", dot: "bg-sky-400" },
    stopped: { tone: "text-amber-300", label: "wg0 not running", dot: "bg-amber-400" },
    error: { tone: "text-red-300", label: "Error", dot: "bg-red-400" },
    offline: { tone: "text-red-300", label: "Agent offline", dot: "bg-red-400" },
  }[state];
  return (
    <div className="rounded-2xl border border-ink-700/70 bg-ink-850 p-5 shadow-card">
      <div className="flex items-start gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-violet-600/15 ring-1 ring-violet-600/40"><Radio size={20} className="text-violet-300" /></div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold text-ink-100">{i.remark}</div>
          <div className="truncate font-mono text-[11px] text-ink-500">{i.agent_name} · {i.address}:{i.listen_port}/udp</div>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border border-ink-700 bg-ink-900/80 px-2.5 py-1 text-[11px] font-medium ${meta.tone}`}>
          <span className={`h-2 w-2 rounded-full ${meta.dot} ${state === "syncing" ? "animate-pulse" : ""}`} />{meta.label}
        </span>
      </div>
      <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] text-ink-500">
        <span className="rounded-md bg-ink-800 px-2 py-0.5 font-mono">{i.network}</span>
        {i.egress_iface && <span className="rounded-md bg-ink-800 px-2 py-0.5">via {i.egress_iface}</span>}
      </div>
      <div className="mt-4 grid grid-cols-4 gap-2 text-center">
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{i.peers}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">peers</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="flex items-center justify-center gap-1 text-sm font-bold text-ink-100">{i.online_peers > 0 && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />}{i.online_peers}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">online</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{fmtTraffic(i.down)}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">down</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{fmtTraffic(i.up)}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">up</div></div>
      </div>
      {i.error && <pre className="mt-2 max-h-24 overflow-auto whitespace-pre-wrap rounded-lg bg-red-950/30 p-2 text-[11px] text-red-300">{i.error}</pre>}
      <div className="mt-3 flex items-center justify-between">
        <button className="text-xs font-medium text-ink-400 hover:text-ink-200" onClick={() => setOpen(!open)}>{open ? "Hide peers" : "Show peers"}</button>
        {canEdit && (
          <div className="flex gap-1">
            <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100" onClick={onEdit} aria-label="Edit"><Edit3 size={15} /></button>
            <button className="rounded-lg p-1.5 text-ink-400 hover:bg-red-950/50 hover:text-red-300" onClick={onDelete} aria-label="Delete"><Trash2 size={15} /></button>
          </div>
        )}
      </div>
      {open && <PeersPanel inbound={i} canEdit={canEdit} />}
    </div>
  );
}

// ============================================================================ page
export default function VpnWireguard() {
  const { can } = useAuth();
  const admin = can("admin");
  const qc = useQueryClient();
  const [editing, setEditing] = useState<WgInbound | "new" | null>(null);
  const { data: inbounds = [], isLoading } = useQuery({ queryKey: ["vpn-wg-inbounds"], queryFn: () => api<WgInbound[]>("/vpn/wg/inbounds"), refetchInterval: 10000 });
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents") });
  const availableNodes = agents.filter((a) => !inbounds.some((i) => i.agent_id === a.id));
  const del = useMutation({
    mutationFn: (agentId: string) => api(`/vpn/wg/inbounds/${agentId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-wg-inbounds"] }),
  });

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink-100">WireGuard</h1>
          <p className="mt-1 text-sm text-ink-400">Native WireGuard peers, alongside your Xray inbounds</p>
        </div>
        {admin && <button className="btn-primary" disabled={!availableNodes.length} onClick={() => setEditing("new")}><Plus size={15} />Add WireGuard inbound</button>}
      </div>

      <div className="mb-6 flex items-start gap-3 rounded-xl border border-amber-800/40 bg-amber-950/20 px-4 py-3 text-sm text-amber-200">
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        <div>
          Plain WireGuard traffic is easy to fingerprint and block where deep packet inspection is in use — prefer VLESS +
          REALITY/XHTTP for censored networks. Use WireGuard where you need the fastest possible speed, full-device/router
          tunneling, or compatibility with the native OS client.
        </div>
      </div>

      {isLoading ? (
        <div className="text-sm text-ink-400">Loading…</div>
      ) : inbounds.length === 0 ? (
        <div className="relative overflow-hidden rounded-2xl border border-ink-700/70 bg-gradient-to-br from-violet-950/30 to-ink-850 p-8 text-center shadow-card">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-violet-600/20 ring-1 ring-violet-600/40"><Radio className="text-violet-300" /></div>
          <h2 className="mt-4 text-xl font-semibold text-ink-100">No WireGuard inbounds yet</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-400">
            {availableNodes.length === 0
              ? "No node has WireGuard installed. Run the installer and choose yes to the WireGuard prompt, or pass --wireguard."
              : "Pick a node to run a wg0 interface on."}
          </p>
          {admin && availableNodes.length > 0 && (
            <button className="btn-primary mx-auto mt-5" onClick={() => setEditing("new")}><Plus size={15} />Add WireGuard inbound</button>
          )}
        </div>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {inbounds.map((i) => (
            <InboundCard key={i.agent_id} i={i} canEdit={admin} onEdit={() => setEditing(i)} onDelete={() => confirm(`Remove the WireGuard inbound on ${i.agent_name}? All its peers are removed too.`) && del.mutate(i.agent_id)} />
          ))}
        </div>
      )}
      <ErrorText error={del.error} />
      {editing && <InboundModal inbound={editing} nodes={editing === "new" ? availableNodes : agents} onClose={() => setEditing(null)} />}
    </>
  );
}
