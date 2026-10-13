import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, Edit3, KeyRound, Plus, RefreshCw, Server, Sparkles, Trash2, XCircle } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Inbound, InboundSettings, VpnNetwork, VpnNode, VpnProtocol, VpnSecurity } from "../../api/types";
import { Card, Empty, ErrorText, Field, Modal, PageHeader } from "../../components/ui";
import { fmtRelative } from "../../lib/format";
import { useAuth } from "../../lib/auth";

const DEFAULT_SETTINGS: InboundSettings = {
  path: "/",
  host: "",
  service_name: "grpc",
  xhttp_mode: "auto",
  flow: "",
  ss_method: "chacha20-ietf-poly1305",
  ss_server_password: "",
  sni: "",
  alpn: [],
  fingerprint: "chrome",
  cert_pem: "",
  key_pem: "",
  cert_file: "",
  key_file: "",
  target: "www.microsoft.com:443",
  server_names: ["www.microsoft.com"],
  private_key: "",
  public_key: "",
  short_ids: [""],
  spider_x: "/",
};

const SS_METHODS = ["chacha20-ietf-poly1305", "aes-128-gcm", "aes-256-gcm", "xchacha20-ietf-poly1305", "2022-blake3-aes-128-gcm", "2022-blake3-aes-256-gcm", "2022-blake3-chacha20-poly1305"];
const FINGERPRINTS = ["chrome", "firefox", "safari", "ios", "android", "edge", "random", "randomized"];

interface Draft {
  agent_id: string;
  remark: string;
  protocol: VpnProtocol;
  port: number;
  listen: string;
  network: VpnNetwork;
  security: VpnSecurity;
  address: string;
  settings: InboundSettings;
  enabled: boolean;
}

const PRESETS: { id: string; label: string; hint: string; recommended?: boolean; apply: (d: Draft) => Draft }[] = [
  { id: "reality-vision", label: "VLESS · REALITY · Vision", hint: "Best default. No domain or certificate needed.", recommended: true, apply: (d) => ({ ...d, protocol: "vless", network: "tcp", security: "reality", port: d.port || 443, settings: { ...d.settings, flow: "xtls-rprx-vision" } }) },
  { id: "reality-xhttp", label: "VLESS · REALITY · XHTTP", hint: "Modern transport recommended by Xray.", recommended: true, apply: (d) => ({ ...d, protocol: "vless", network: "xhttp", security: "reality", settings: { ...d.settings, flow: "", path: "/" } }) },
  { id: "ws-tls", label: "VLESS · WebSocket · TLS", hint: "For CDNs (e.g. Cloudflare). Needs a domain + certificate.", apply: (d) => ({ ...d, protocol: "vless", network: "ws", security: "tls", settings: { ...d.settings, flow: "", path: "/ws" } }) },
  { id: "trojan-tls", label: "Trojan · TLS", hint: "Needs a domain + certificate.", apply: (d) => ({ ...d, protocol: "trojan", network: "tcp", security: "tls", settings: { ...d.settings, flow: "" } }) },
  { id: "vmess-ws", label: "VMess · WebSocket", hint: "Legacy clients.", apply: (d) => ({ ...d, protocol: "vmess", network: "ws", security: "none", settings: { ...d.settings, flow: "", path: "/vm" } }) },
  { id: "ss", label: "Shadowsocks 2022", hint: "Simple, widely supported.", apply: (d) => ({ ...d, protocol: "shadowsocks", network: "tcp", security: "none", settings: { ...d.settings, flow: "", ss_method: "2022-blake3-aes-128-gcm" } }) },
];

const DEPRECATED: Partial<Record<string, string>> = {
  vmess: "VMess is deprecated in Xray 26 (no forward secrecy).",
  trojan: "Trojan is deprecated in Xray 26; prefer VLESS.",
  shadowsocks: "Shadowsocks is deprecated in Xray 26; prefer VLESS.",
  ws: "WebSocket is deprecated in Xray 26; prefer XHTTP.",
  grpc: "gRPC is deprecated in Xray 26; prefer XHTTP.",
  httpupgrade: "HTTPUpgrade is deprecated in Xray 26; prefer XHTTP.",
};

function Seg<T extends string>({ value, options, onChange, disabled }: { value: T; options: { v: T; label: string; off?: boolean }[]; onChange: (v: T) => void; disabled?: boolean }) {
  return (
    <div className="inline-flex flex-wrap rounded-lg border border-ink-700 bg-ink-900 p-0.5">
      {options.map((o) => (
        <button
          type="button"
          key={o.v}
          disabled={disabled || o.off}
          onClick={() => onChange(o.v)}
          className={`rounded-md px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-30 ${value === o.v ? "bg-emerald-700/40 text-emerald-200 ring-1 ring-emerald-600/50" : "text-ink-400 hover:text-ink-200"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-900/40 p-4">
      <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-emerald-400">{title}</div>
      <div className="space-y-4">{children}</div>
    </div>
  );
}

function InboundModal({ inbound, nodes, onClose }: { inbound: Inbound | "new"; nodes: VpnNode[]; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = inbound === "new";
  const firstNode = nodes.find((n) => n.xray_installed) ?? nodes[0];
  const [d, setD] = useState<Draft>(() =>
    isNew
      ? { agent_id: firstNode?.agent_id ?? "", remark: "", protocol: "vless", port: 443, listen: "", network: "tcp", security: "reality", address: firstNode?.remote_addr && !/^(127\.|10\.|192\.168\.)/.test(firstNode.remote_addr) ? firstNode.remote_addr : window.location.hostname, settings: { ...DEFAULT_SETTINGS, flow: "xtls-rprx-vision" }, enabled: true }
      : { agent_id: inbound.agent_id, remark: inbound.remark, protocol: inbound.protocol, port: inbound.port, listen: inbound.listen, network: inbound.network, security: inbound.security, address: inbound.address, settings: { ...DEFAULT_SETTINGS, ...inbound.settings }, enabled: inbound.enabled },
  );
  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setD((s) => ({ ...s, [k]: v }));
  const setS = <K extends keyof InboundSettings>(k: K, v: InboundSettings[K]) => setD((s) => ({ ...s, settings: { ...s.settings, [k]: v } }));

  const genKeys = useMutation({
    mutationFn: () => api<{ private_key: string; public_key: string; short_id: string }>("/vpn/tools/reality-keys", { method: "POST" }),
    onSuccess: (k) => setD((s) => ({ ...s, settings: { ...s.settings, private_key: k.private_key, public_key: k.public_key, short_ids: [k.short_id] } })),
  });
  const genSs = useMutation({
    mutationFn: () => api<{ key: string }>(`/vpn/tools/ss2022-key?method=${encodeURIComponent(d.settings.ss_method)}`, { method: "POST" }),
    onSuccess: (k) => setS("ss_server_password", k.key),
  });
  const save = useMutation({
    mutationFn: () => {
      const body = { ...d, settings: { ...d.settings, server_names: d.settings.server_names.filter(Boolean) } };
      return isNew ? api<Inbound>("/vpn/inbounds", { method: "POST", json: body }) : api<Inbound>(`/vpn/inbounds/${inbound.id}`, { method: "PUT", json: body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-inbounds"] });
      qc.invalidateQueries({ queryKey: ["vpn-nodes"] });
      onClose();
    },
  });

  const p = d.protocol;
  const ss = p === "shadowsocks";
  const realityOk = (p === "vless" || p === "trojan") && ["tcp", "grpc", "xhttp"].includes(d.network);
  const visionOk = p === "vless" && d.network === "tcp" && d.security !== "none";
  const node = nodes.find((n) => n.agent_id === d.agent_id);
  const warn = [DEPRECATED[p], !ss ? DEPRECATED[d.network] : undefined].filter(Boolean);
  const panelHost = window.location.hostname;

  const changeProtocol = (v: VpnProtocol) =>
    setD((s) => {
      const n = { ...s, protocol: v };
      if (v === "shadowsocks") Object.assign(n, { network: "tcp", security: "none" });
      if (v === "vmess" && s.security === "reality") n.security = "none";
      if (v !== "vless") n.settings = { ...n.settings, flow: "" };
      return n;
    });

  return (
    <Modal open onClose={onClose} title={isNew ? "New inbound" : `Edit ${inbound.remark}`} wide>
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        {isNew && (
          <div>
            <span className="label">Quick presets</span>
            <div className="grid gap-2 sm:grid-cols-3">
              {PRESETS.map((pr) => (
                <button type="button" key={pr.id} onClick={() => setD(pr.apply)} className="rounded-lg border border-ink-700 bg-ink-900/60 p-2.5 text-left transition hover:border-emerald-700">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-ink-100">
                    {pr.recommended && <Sparkles size={12} className="text-emerald-400" />}
                    {pr.label}
                  </div>
                  <div className="mt-0.5 text-[11px] text-ink-500">{pr.hint}</div>
                </button>
              ))}
            </div>
          </div>
        )}

        <Section title="General">
          <div className="grid gap-4 sm:grid-cols-3">
            <Field label="Remark"><input className="input" value={d.remark} onChange={(e) => set("remark", e.target.value)} required maxLength={128} placeholder="e.g. Germany-Reality" /></Field>
            <Field label="Server (node)">
              <select className="input" value={d.agent_id} onChange={(e) => set("agent_id", e.target.value)} required>
                {nodes.map((n) => <option key={n.agent_id} value={n.agent_id}>{n.name}{n.xray_installed ? "" : " (Xray not installed)"}</option>)}
              </select>
            </Field>
            <Field label="Port"><input className="input" type="number" min={1} max={65535} value={d.port} onChange={(e) => set("port", Number(e.target.value))} required /></Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Address clients connect to" hint="Domain or public IP of this node (used in links)">
              <input className="input mono" value={d.address} onChange={(e) => set("address", e.target.value.trim())} required />
            </Field>
            <Field label="Listen IP" hint="Empty = all interfaces"><input className="input mono" value={d.listen} onChange={(e) => set("listen", e.target.value.trim())} placeholder="0.0.0.0" /></Field>
          </div>
          {node && d.port === 443 && node.remote_addr && (d.address === panelHost) && (
            <p className="flex items-center gap-1.5 text-xs text-amber-300"><AlertTriangle size={13} />If this node is also the panel server, port 443 is already used by the panel. Use another port (e.g. 8443, 2053).</p>
          )}
        </Section>

        <Section title="Protocol & transport">
          <div className="flex flex-wrap gap-6">
            <div><span className="label">Protocol</span><Seg value={p} onChange={changeProtocol} options={[{ v: "vless", label: "VLESS" }, { v: "vmess", label: "VMess" }, { v: "trojan", label: "Trojan" }, { v: "shadowsocks", label: "Shadowsocks" }]} /></div>
            {!ss && (
              <div><span className="label">Transport</span>
                <Seg value={d.network} onChange={(v) => setD((s) => ({ ...s, network: v, security: s.security === "reality" && !["tcp", "grpc", "xhttp"].includes(v) ? "tls" : s.security, settings: { ...s.settings, flow: v === "tcp" ? s.settings.flow : "" } }))}
                  options={[{ v: "tcp", label: "TCP" }, { v: "xhttp", label: "XHTTP" }, { v: "ws", label: "WebSocket" }, { v: "grpc", label: "gRPC" }, { v: "httpupgrade", label: "HTTPUpgrade" }]} />
              </div>
            )}
            {!ss && (
              <div><span className="label">Security</span>
                <Seg value={d.security} onChange={(v) => setD((s) => ({ ...s, security: v, settings: { ...s.settings, flow: v === "none" ? "" : s.settings.flow } }))}
                  options={[{ v: "none", label: "None" }, { v: "tls", label: "TLS" }, { v: "reality", label: "REALITY", off: !realityOk }]} />
              </div>
            )}
          </div>
          {warn.length > 0 && <p className="flex items-start gap-1.5 text-xs text-amber-300/90"><AlertTriangle size={13} className="mt-0.5 shrink-0" />{warn.join(" ")}</p>}
          {p === "vless" && (
            <label className={`flex items-center gap-2 text-sm ${visionOk ? "text-ink-200" : "text-ink-500"}`}>
              <input type="checkbox" className="accent-emerald-500" disabled={!visionOk} checked={d.settings.flow === "xtls-rprx-vision"} onChange={(e) => setS("flow", e.target.checked ? "xtls-rprx-vision" : "")} />
              XTLS Vision flow <span className="text-xs text-ink-500">(VLESS + TCP + TLS/REALITY)</span>
            </label>
          )}
          {["ws", "httpupgrade", "xhttp"].includes(d.network) && !ss && (
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Path"><input className="input mono" value={d.settings.path} onChange={(e) => setS("path", e.target.value)} /></Field>
              <Field label="Host header" hint="Optional"><input className="input mono" value={d.settings.host} onChange={(e) => setS("host", e.target.value.trim())} /></Field>
              {d.network === "xhttp" && (
                <Field label="XHTTP mode">
                  <select className="input" value={d.settings.xhttp_mode} onChange={(e) => setS("xhttp_mode", e.target.value as InboundSettings["xhttp_mode"])}>
                    {["auto", "packet-up", "stream-up", "stream-one"].map((m) => <option key={m}>{m}</option>)}
                  </select>
                </Field>
              )}
            </div>
          )}
          {d.network === "grpc" && !ss && (
            <div className="grid gap-4 sm:grid-cols-3"><Field label="gRPC service name"><input className="input mono" value={d.settings.service_name} onChange={(e) => setS("service_name", e.target.value)} /></Field></div>
          )}
          {ss && (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Cipher">
                <select className="input" value={d.settings.ss_method} onChange={(e) => setS("ss_method", e.target.value)}>
                  {SS_METHODS.map((m) => <option key={m}>{m}</option>)}
                </select>
              </Field>
              {d.settings.ss_method.startsWith("2022") && (
                <Field label="Server key (base64)">
                  <div className="flex gap-2">
                    <input className="input mono flex-1 text-xs" value={d.settings.ss_server_password} onChange={(e) => setS("ss_server_password", e.target.value.trim())} required />
                    <button type="button" className="btn-ghost text-xs" onClick={() => genSs.mutate()}><KeyRound size={13} />Generate</button>
                  </div>
                </Field>
              )}
            </div>
          )}
        </Section>

        {d.security === "reality" && !ss && (
          <Section title="REALITY">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Target (dest)" hint="A real TLS 1.3 site to imitate, host:port">
                <input className="input mono" value={d.settings.target} onChange={(e) => setS("target", e.target.value.trim())} />
              </Field>
              <Field label="Server names (SNI)" hint="Comma separated; must be valid for the target">
                <input className="input mono" value={d.settings.server_names.join(", ")} onChange={(e) => setS("server_names", e.target.value.split(",").map((x) => x.trim()))} />
              </Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-[1fr_1fr_auto]">
              <Field label="Private key"><input className="input mono text-xs" value={d.settings.private_key} onChange={(e) => setS("private_key", e.target.value.trim())} required /></Field>
              <Field label="Public key"><input className="input mono text-xs" value={d.settings.public_key} onChange={(e) => setS("public_key", e.target.value.trim())} required /></Field>
              <div className="flex items-end"><button type="button" className="btn-ghost" onClick={() => genKeys.mutate()}><KeyRound size={14} />Generate</button></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Short IDs" hint="Hex, comma separated"><input className="input mono" value={d.settings.short_ids.join(", ")} onChange={(e) => setS("short_ids", e.target.value.split(",").map((x) => x.trim()))} /></Field>
              <Field label="Client fingerprint"><select className="input" value={d.settings.fingerprint} onChange={(e) => setS("fingerprint", e.target.value)}>{FINGERPRINTS.map((f) => <option key={f}>{f}</option>)}</select></Field>
              <Field label="SpiderX"><input className="input mono" value={d.settings.spider_x} onChange={(e) => setS("spider_x", e.target.value)} /></Field>
            </div>
          </Section>
        )}

        {d.security === "tls" && !ss && (
          <Section title="TLS">
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="SNI / domain"><input className="input mono" value={d.settings.sni} onChange={(e) => setS("sni", e.target.value.trim())} placeholder="vpn.example.com" /></Field>
              <Field label="ALPN">
                <div className="flex gap-3 pt-2 text-sm text-ink-200">
                  {(["h2", "http/1.1"] as const).map((a) => (
                    <label key={a} className="flex items-center gap-1.5"><input type="checkbox" className="accent-emerald-500" checked={d.settings.alpn.includes(a)} onChange={(e) => setS("alpn", e.target.checked ? [...d.settings.alpn, a] : d.settings.alpn.filter((x) => x !== a))} />{a}</label>
                  ))}
                </div>
              </Field>
              <Field label="Client fingerprint"><select className="input" value={d.settings.fingerprint} onChange={(e) => setS("fingerprint", e.target.value)}>{FINGERPRINTS.map((f) => <option key={f}>{f}</option>)}</select></Field>
            </div>
            <p className="text-xs text-ink-400">Clients verify the certificate, so it must be valid for the domain (e.g. Let's Encrypt). Paste it, or give file paths on the node that the <span className="mono">ipf3-xray</span> user can read.</p>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Certificate (PEM, full chain)"><textarea className="input mono h-28 text-[11px]" value={d.settings.cert_pem} onChange={(e) => setS("cert_pem", e.target.value)} placeholder="-----BEGIN CERTIFICATE-----" /></Field>
              <Field label="Private key (PEM)"><textarea className="input mono h-28 text-[11px]" value={d.settings.key_pem} onChange={(e) => setS("key_pem", e.target.value)} placeholder="-----BEGIN PRIVATE KEY-----" /></Field>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="…or certificate file on node"><input className="input mono" value={d.settings.cert_file} onChange={(e) => setS("cert_file", e.target.value.trim())} placeholder="/etc/ssl/vpn/fullchain.pem" /></Field>
              <Field label="…and key file on node"><input className="input mono" value={d.settings.key_file} onChange={(e) => setS("key_file", e.target.value.trim())} placeholder="/etc/ssl/vpn/privkey.pem" /></Field>
            </div>
          </Section>
        )}

        <label className="flex items-center gap-2 text-sm text-ink-200"><input type="checkbox" className="accent-emerald-500" checked={d.enabled} onChange={(e) => set("enabled", e.target.checked)} />Enabled</label>
        <p className="text-xs text-ink-500">The node applies changes within ~10 seconds. If the server uses a firewall (ufw), allow the port: <span className="mono">ufw allow {d.port}</span></p>
        <ErrorText error={save.error || genKeys.error || genSs.error} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending || !d.agent_id}>{isNew ? "Create inbound" : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
}

function NodeCard({ n }: { n: VpnNode }) {
  const state = !n.xray_installed ? "missing" : !n.online ? "offline" : n.error ? "error" : !n.running ? "stopped" : !n.in_sync ? "syncing" : "ok";
  const tone = { ok: "text-emerald-300", syncing: "text-sky-300", stopped: "text-amber-300", error: "text-red-300", offline: "text-red-300", missing: "text-ink-400" }[state];
  const label = { ok: "Running · in sync", syncing: "Applying changes…", stopped: "Xray not running", error: "Config error", offline: "Agent offline", missing: "Xray not installed" }[state];
  const Icon = state === "ok" ? CheckCircle2 : state === "syncing" ? RefreshCw : state === "missing" ? Server : XCircle;
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-850 p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <Link to={`/servers/${n.agent_id}`} className="font-medium text-ink-100 hover:text-emerald-300">{n.name}</Link>
          <div className="font-mono text-[11px] text-ink-500">{n.remote_addr}</div>
        </div>
        <span className={`inline-flex items-center gap-1 text-xs ${tone}`}><Icon size={13} className={state === "syncing" ? "animate-spin" : ""} />{label}</span>
      </div>
      <div className="mt-3 flex gap-4 text-xs text-ink-400">
        <span>{n.inbounds} inbounds</span>
        <span>{n.online_users} online</span>
        {n.xray_version && <span>Xray {n.xray_version}</span>}
        {n.applied_at && <span>applied {fmtRelative(n.applied_at)}</span>}
      </div>
      {n.error && <pre className="mt-2 max-h-28 overflow-auto whitespace-pre-wrap rounded-lg bg-red-950/30 p-2 text-[11px] text-red-300">{n.error}</pre>}
      {state === "missing" && <p className="mt-2 text-xs text-ink-500">On this server run <span className="mono">sudo ./install.sh</span> → Upgrade, and answer yes to “VPN node”.</p>}
    </div>
  );
}

export default function VpnInbounds() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<Inbound | "new" | null>(null);
  const { data: inbounds = [] } = useQuery({ queryKey: ["vpn-inbounds"], queryFn: () => api<Inbound[]>("/vpn/inbounds"), refetchInterval: 15000 });
  const { data: nodes = [] } = useQuery({ queryKey: ["vpn-nodes"], queryFn: () => api<VpnNode[]>("/vpn/nodes"), refetchInterval: 5000 });
  const del = useMutation({
    mutationFn: (id: number) => api(`/vpn/inbounds/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-inbounds"] }),
  });
  const toggle = useMutation({
    mutationFn: (i: Inbound) => api(`/vpn/inbounds/${i.id}`, { method: "PUT", json: { ...i, enabled: !i.enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-inbounds"] }),
  });
  return (
    <>
      <PageHeader
        title="Inbounds"
        subtitle="Xray listeners on your nodes. Users connect through these."
        actions={can("admin") && <button className="btn-primary" disabled={!nodes.length} onClick={() => setEditing("new")}><Plus size={15} />New inbound</button>}
      />
      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-400">Nodes</h2>
      {nodes.length === 0 ? (
        <Card><Empty>No servers yet. Install the panel with an agent, or add servers with the installer (they become VPN nodes when Xray is enabled).</Empty></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">{nodes.map((n) => <NodeCard key={n.agent_id} n={n} />)}</div>
      )}
      <Card className="mt-6" title="Inbounds" bodyClass="overflow-x-auto">
        {inbounds.length === 0 ? <Empty>No inbounds yet. Create one — “VLESS · REALITY · Vision” works out of the box.</Empty> : (
          <table className="table">
            <thead><tr><th>Remark</th><th>Node</th><th>Protocol</th><th>Address</th><th>Users</th><th>State</th><th /></tr></thead>
            <tbody>
              {inbounds.map((i) => (
                <tr key={i.id}>
                  <td className="font-medium text-ink-100">{i.remark}</td>
                  <td>{i.agent_name}</td>
                  <td>
                    <span className="badge bg-ink-750 uppercase text-emerald-300">{i.protocol}</span>
                    {i.protocol !== "shadowsocks" && <span className="ml-1.5 text-xs text-ink-400">{i.network} · {i.security}</span>}
                    {i.settings.flow && <span className="ml-1.5 text-[10px] text-ink-500">vision</span>}
                  </td>
                  <td className="mono text-xs">{i.address}:{i.port}</td>
                  <td>{i.users}</td>
                  <td>
                    <button disabled={!can("admin")} onClick={() => toggle.mutate(i)} className={`badge ${i.enabled ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`}>{i.enabled ? "enabled" : "disabled"}</button>
                  </td>
                  <td className="whitespace-nowrap text-right">
                    {can("admin") && (
                      <>
                        <button className="mr-3 text-ink-400 hover:text-ink-100" onClick={() => setEditing(i)} aria-label="Edit"><Edit3 size={15} /></button>
                        <button className="text-ink-400 hover:text-red-300" onClick={() => confirm(`Delete inbound ${i.remark}? Users lose this config.`) && del.mutate(i.id)} aria-label="Delete"><Trash2 size={15} /></button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      <ErrorText error={del.error || toggle.error} />
      {editing && <InboundModal inbound={editing} nodes={nodes} onClose={() => setEditing(null)} />}
    </>
  );
}
