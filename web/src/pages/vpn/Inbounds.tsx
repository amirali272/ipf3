import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, AlertTriangle, CheckCircle2, Copy, Edit3, KeyRound, Lock, Plus, Server, ShieldCheck, Sparkles, Trash2, Users, Wifi, Zap } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { EnrollmentToken, Inbound, InboundSettings, VpnNetwork, VpnNode, VpnProtocol, VpnSecurity } from "../../api/types";
import { Chip, CopyButton, Switch } from "../../components/vpn";
import { Card, Empty, ErrorText, Field, Modal } from "../../components/ui";
import { fmtRelative, fmtTraffic } from "../../lib/format";
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
  { id: "reality-vision", label: "VLESS · REALITY · Vision", hint: "Best default. No domain or certificate needed.", recommended: true, apply: (d) => ({ ...d, protocol: "vless", network: "tcp", security: "reality", port: d.port || 8443, settings: { ...d.settings, flow: "xtls-rprx-vision" } }) },
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

function InboundModal({ inbound, nodes, onClose, preset }: { inbound: Inbound | "new"; nodes: VpnNode[]; onClose: () => void; preset?: string }) {
  const qc = useQueryClient();
  const isNew = inbound === "new";
  const firstNode = nodes.find((n) => n.xray_installed) ?? nodes[0];
  const [d, setD] = useState<Draft>(() => {
    const base: Draft = isNew
      ? { agent_id: firstNode?.agent_id ?? "", remark: "", protocol: "vless", port: 8443, listen: "", network: "tcp", security: "reality", address: firstNode?.remote_addr && !/^(127\.|10\.|192\.168\.)/.test(firstNode.remote_addr) ? firstNode.remote_addr : window.location.hostname, settings: { ...DEFAULT_SETTINGS, flow: "xtls-rprx-vision" }, enabled: true }
      : { agent_id: inbound.agent_id, remark: inbound.remark, protocol: inbound.protocol, port: inbound.port, listen: inbound.listen, network: inbound.network, security: inbound.security, address: inbound.address, settings: { ...DEFAULT_SETTINGS, ...inbound.settings }, enabled: inbound.enabled };
    const pr = PRESETS.find((x) => x.id === preset);
    return pr && isNew ? pr.apply(base) : base;
  });
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

const PROTO_STYLE: Record<string, { grad: string; ring: string; text: string; label: string }> = {
  vless: { grad: "from-emerald-500 to-emerald-700", ring: "ring-emerald-500/40", text: "text-emerald-300", label: "VLESS" },
  vmess: { grad: "from-violet-500 to-violet-700", ring: "ring-violet-500/40", text: "text-violet-300", label: "VMess" },
  trojan: { grad: "from-orange-500 to-orange-700", ring: "ring-orange-500/40", text: "text-orange-300", label: "Trojan" },
  shadowsocks: { grad: "from-sky-500 to-sky-700", ring: "ring-sky-500/40", text: "text-sky-300", label: "SS" },
};


function InboundCard({ i, canEdit, onEdit, onDelete, onToggle }: { i: Inbound; canEdit: boolean; onEdit: () => void; onDelete: () => void; onToggle: () => void }) {
  const st = PROTO_STYLE[i.protocol];
  const total = (i.up ?? 0) + (i.down ?? 0);
  const deprecated = DEPRECATED[i.protocol] || (i.protocol !== "shadowsocks" ? DEPRECATED[i.network] : undefined);
  const [copied, setCopied] = useState(false);
  return (
    <div className={`group relative overflow-hidden rounded-2xl border bg-gradient-to-br from-ink-800/80 to-ink-850 p-5 shadow-card transition ${i.enabled ? "border-ink-700/70 hover:border-emerald-700/60" : "border-ink-800 opacity-60"}`}>
      <div className={`pointer-events-none absolute -right-16 -top-16 h-40 w-40 rounded-full bg-gradient-to-br ${st.grad} opacity-[0.12] blur-2xl`} />
      <div className="relative flex items-start gap-4">
        <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${st.grad} text-xs font-black tracking-wide text-white shadow-lg ring-4 ${st.ring}`}>
          {st.label}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-lg font-semibold text-ink-100">{i.remark}</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-xs text-ink-400"><Server size={12} />{i.agent_name}</div>
        </div>
        <Switch on={i.enabled} onChange={onToggle} disabled={!canEdit} />
      </div>

      <div className="relative mt-4 flex flex-wrap items-center gap-1.5">
        {i.protocol !== "shadowsocks" && <Chip>{i.network}</Chip>}
        {i.security === "reality" && <Chip tone="green" icon={<ShieldCheck size={11} />}>Reality</Chip>}
        {i.security === "tls" && <Chip tone="green" icon={<Lock size={11} />}>TLS</Chip>}
        {i.security === "none" && i.protocol !== "shadowsocks" && <Chip>no tls</Chip>}
        {i.settings.flow && <Chip tone="green" icon={<Zap size={11} />}>Vision</Chip>}
        {i.protocol === "shadowsocks" && <Chip>{i.settings.ss_method.replace("2022-blake3-", "2022 ")}</Chip>}
        {deprecated && <Chip tone="amber" icon={<AlertTriangle size={11} />}>legacy</Chip>}
      </div>

      <button
        onClick={() => navigator.clipboard.writeText(`${i.address}:${i.port}`).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200); })}
        className="relative mt-4 flex w-full items-center justify-between rounded-xl border border-ink-700 bg-ink-950/60 px-3 py-2.5 text-left transition hover:border-ink-600"
        title="Copy address"
      >
        <span className="truncate font-mono text-sm text-ink-200">{i.address}</span>
        <span className="flex items-center gap-2">
          <span className={`rounded-md bg-ink-800 px-2 py-0.5 font-mono text-sm font-bold ${st.text}`}>:{i.port}</span>
          {copied ? <CheckCircle2 size={14} className="text-emerald-400" /> : <Copy size={14} className="text-ink-500" />}
        </span>
      </button>

      <div className="relative mt-4 grid grid-cols-3 gap-2">
        <div className="rounded-xl bg-ink-900/70 px-3 py-2">
          <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-ink-500"><Users size={11} />Users</div>
          <div className="mt-0.5 text-lg font-bold tabular-nums text-ink-100">{i.users}</div>
        </div>
        <div className="rounded-xl bg-ink-900/70 px-3 py-2">
          <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-ink-500"><Wifi size={11} />Online</div>
          <div className="mt-0.5 flex items-center gap-1.5 text-lg font-bold tabular-nums text-ink-100">
            {i.online > 0 && <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />}{i.online}
          </div>
        </div>
        <div className="rounded-xl bg-ink-900/70 px-3 py-2">
          <div className="flex items-center gap-1 text-[10px] uppercase tracking-wider text-ink-500"><Activity size={11} />Traffic</div>
          <div className="mt-0.5 truncate text-lg font-bold tabular-nums text-ink-100" title={`↓ ${fmtTraffic(i.down)} · ↑ ${fmtTraffic(i.up)}`}>{fmtTraffic(total, total >= 1e9 ? 2 : 1)}</div>
        </div>
      </div>

      {canEdit && (
        <div className="relative mt-4 flex gap-2 border-t border-ink-800 pt-3">
          <button className="btn-ghost flex-1 py-1.5 text-xs" onClick={onEdit}><Edit3 size={13} />Edit</button>
          <button className="btn-ghost py-1.5 text-xs hover:border-red-900 hover:text-red-300" onClick={onDelete} aria-label="Delete"><Trash2 size={13} /></button>
        </div>
      )}
    </div>
  );
}

function NodeCard({ n }: { n: VpnNode }) {
  const state = !n.xray_installed ? "missing" : !n.online ? "offline" : n.error ? "error" : !n.running ? "stopped" : !n.in_sync ? "syncing" : "ok";
  const meta = {
    ok: { tone: "text-emerald-300", glow: "from-emerald-500/20", dot: "bg-emerald-400 shadow-[0_0_10px_#34d399]", label: "Running · in sync" },
    syncing: { tone: "text-sky-300", glow: "from-sky-500/20", dot: "bg-sky-400", label: "Applying changes…" },
    stopped: { tone: "text-amber-300", glow: "from-amber-500/20", dot: "bg-amber-400", label: "Xray not running" },
    error: { tone: "text-red-300", glow: "from-red-500/20", dot: "bg-red-400", label: "Config error" },
    offline: { tone: "text-red-300", glow: "from-red-500/20", dot: "bg-red-400", label: "Agent offline" },
    missing: { tone: "text-ink-400", glow: "from-ink-500/10", dot: "bg-ink-500", label: "Xray not installed" },
  }[state];
  return (
    <div className="relative overflow-hidden rounded-2xl border border-ink-700/70 bg-ink-850 p-5 shadow-card">
      <div className={`pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-b ${meta.glow} to-transparent`} />
      <div className="relative flex items-start gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-ink-800 ring-1 ring-ink-600"><Server size={20} className="text-ink-200" /></div>
        <div className="min-w-0 flex-1">
          <Link to={`/servers/${n.agent_id}`} className="text-base font-semibold text-ink-100 hover:text-emerald-300">{n.name}</Link>
          <div className="font-mono text-[11px] text-ink-500">{n.remote_addr}</div>
        </div>
        <span className={`inline-flex items-center gap-1.5 rounded-full border border-ink-700 bg-ink-900/80 px-2.5 py-1 text-[11px] font-medium ${meta.tone}`}>
          <span className={`h-2 w-2 rounded-full ${meta.dot} ${state === "syncing" ? "animate-pulse" : ""}`} />{meta.label}
        </span>
      </div>
      <div className="relative mt-4 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-lg font-bold text-ink-100">{n.inbounds}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">inbounds</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="flex items-center justify-center gap-1.5 text-lg font-bold text-ink-100">{n.online_users > 0 && <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />}{n.online_users}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">online</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="truncate px-1 text-sm font-bold leading-7 text-ink-100">{n.xray_version ?? "—"}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">xray</div></div>
      </div>
      {n.applied_at && <div className="relative mt-2 text-[11px] text-ink-500">Config applied {fmtRelative(n.applied_at)}</div>}
      {n.error && <pre className="relative mt-2 max-h-28 overflow-auto whitespace-pre-wrap rounded-lg bg-red-950/30 p-2 text-[11px] text-red-300">{n.error}</pre>}
      {state === "stopped" && (
        <p className="relative mt-2 text-xs text-ink-400">Xray could not start — usually the port is already in use (e.g. 443 on the panel server). On the server: <span className="mono">journalctl -u ipf3-xray -n 30</span></p>
      )}
      {state === "missing" && <p className="relative mt-2 text-xs text-ink-500">On this server run <span className="mono">sudo ./install.sh</span> → Upgrade, and answer yes to “VPN node”.</p>}
    </div>
  );
}

const INSTALL_URL = "https://raw.githubusercontent.com/amirali272/ipf3/claude/gracious-ramanujan-enb5r9/install.sh";

function AddNodeModal({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [iperf, setIperf] = useState(false);
  const [token, setToken] = useState<EnrollmentToken | null>(null);
  const create = useMutation({
    mutationFn: () => api<EnrollmentToken>("/enrollment-tokens", { method: "POST", json: { note: `node: ${name}`, ttl_hours: 24 } }),
    onSuccess: (t) => { setToken(t); qc.invalidateQueries({ queryKey: ["enrollment-tokens"] }); },
  });
  const { data: tokens = [] } = useQuery({
    queryKey: ["enrollment-tokens"],
    queryFn: () => api<EnrollmentToken[]>("/enrollment-tokens"),
    enabled: !!token,
    refetchInterval: 3000,
  });
  const { data: nodes = [] } = useQuery({ queryKey: ["vpn-nodes"], queryFn: () => api<VpnNode[]>("/vpn/nodes"), enabled: !!token, refetchInterval: 3000 });
  const used = token ? tokens.find((t) => t.id === token.id && t.agent_id) : undefined;
  const node = used ? nodes.find((n) => n.agent_id === used.agent_id) : undefined;
  const valid = /^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$/.test(name);
  const cmd = token
    ? `bash <(curl -fsSL "${INSTALL_URL}?$(date +%s)") --node --panel ${window.location.origin} --token ${token.token} --name ${name}${iperf ? " --iperf3" : ""}`
    : "";
  return (
    <Modal open onClose={onClose} title="Add node" wide>
      {!token ? (
        <div className="space-y-4">
          <p className="text-sm text-ink-300">
            A node is another Ubuntu server (22.04 / 24.04) that runs Xray and serves inbounds. The panel stays here; users
            connect directly to the node.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Node name"><input className="input" value={name} onChange={(e) => setName(e.target.value.trim())} placeholder="e.g. de-1" maxLength={63} autoFocus /></Field>
            <label className="flex items-center gap-2 self-end pb-2 text-sm text-ink-300">
              <input type="checkbox" checked={iperf} onChange={(e) => setIperf(e.target.checked)} />Also run an iperf3 endpoint
            </label>
          </div>
          <ErrorText error={create.error} />
          <div className="flex justify-end gap-2">
            <button className="btn-ghost" onClick={onClose}>Cancel</button>
            <button className="btn-primary" disabled={!valid || create.isPending} onClick={() => create.mutate()}><KeyRound size={15} />Generate command</button>
          </div>
        </div>
      ) : (
        <div className="space-y-4">
          <div className="text-sm text-ink-300">
            <b className="text-ink-100">1.</b> Run this as root on the new server. The command is single-use and valid for 24 hours.
          </div>
          <div className="relative rounded-xl border border-ink-700 bg-ink-950 p-3 pr-24">
            <code className="block break-all font-mono text-xs leading-relaxed text-emerald-300">{cmd}</code>
            <CopyButton text={cmd} className="absolute right-2 top-2" />
          </div>
          <div className="text-sm text-ink-300">
            <b className="text-ink-100">2.</b> Wait for the node to connect, then create inbounds and choose <b className="text-ink-100">{name}</b> as the server.
          </div>
          <div className={`flex items-center gap-3 rounded-xl border px-4 py-3 text-sm ${node?.online ? "border-emerald-700/60 bg-emerald-950/30 text-emerald-300" : "border-ink-700 bg-ink-900/60 text-ink-300"}`}>
            {node?.online ? (
              <><CheckCircle2 size={18} />Connected — {node.name}{node.xray_installed ? ` · Xray ${node.xray_version ?? ""}` : " · installing Xray…"}</>
            ) : used ? (
              <><span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />Enrolled, waiting for the first report…</>
            ) : (
              <><span className="h-2 w-2 animate-pulse rounded-full bg-amber-400" />Waiting for the node to connect…</>
            )}
          </div>
          <div className="flex justify-end"><button className={node?.online ? "btn-primary" : "btn-ghost"} onClick={onClose}>Done</button></div>
        </div>
      )}
    </Modal>
  );
}

export default function VpnInbounds() {
  const { can } = useAuth();
  const qc = useQueryClient();
  const [editing, setEditing] = useState<{ inbound: Inbound | "new"; preset?: string } | null>(null);
  const [adding, setAdding] = useState(false);
  const { data: inbounds = [] } = useQuery({ queryKey: ["vpn-inbounds"], queryFn: () => api<Inbound[]>("/vpn/inbounds"), refetchInterval: 10000 });
  const { data: nodes = [] } = useQuery({ queryKey: ["vpn-nodes"], queryFn: () => api<VpnNode[]>("/vpn/nodes"), refetchInterval: 5000 });
  const del = useMutation({
    mutationFn: (id: number) => api(`/vpn/inbounds/${id}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-inbounds"] }),
  });
  const toggle = useMutation({
    mutationFn: (i: Inbound) => api(`/vpn/inbounds/${i.id}`, { method: "PUT", json: { ...i, enabled: !i.enabled } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["vpn-inbounds"] }),
  });
  const totals = inbounds.reduce((a, i) => ({ up: a.up + (i.up ?? 0), down: a.down + (i.down ?? 0), online: a.online + (i.online ?? 0), on: a.on + (i.enabled ? 1 : 0) }), { up: 0, down: 0, online: 0, on: 0 });
  const admin = can("admin");
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink-100">Inbounds</h1>
          <p className="mt-1 text-sm text-ink-400">Xray listeners on your nodes — users connect through these</p>
        </div>
        {admin && (
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => setAdding(true)}><Server size={15} />Add node</button>
            <button className="btn-primary" disabled={!nodes.length} onClick={() => setEditing({ inbound: "new" })}><Plus size={15} />New inbound</button>
          </div>
        )}
      </div>

      {inbounds.length > 0 && (
        <div className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          {[
            { k: "Inbounds", v: `${totals.on} / ${inbounds.length}`, s: "enabled" },
            { k: "Online", v: totals.online, s: "users connected" },
            { k: "Download", v: fmtTraffic(totals.down), s: "all time" },
            { k: "Upload", v: fmtTraffic(totals.up), s: "all time" },
          ].map((x) => (
            <div key={x.k} className="rounded-xl border border-ink-700/70 bg-ink-850 px-4 py-3">
              <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-400">{x.k}</div>
              <div className="mt-0.5 text-xl font-bold tabular-nums text-ink-100">{x.v}</div>
              <div className="text-[11px] text-ink-500">{x.s}</div>
            </div>
          ))}
        </div>
      )}

      {inbounds.length === 0 ? (
        <div className="relative overflow-hidden rounded-2xl border border-ink-700/70 bg-gradient-to-br from-emerald-950/40 to-ink-850 p-8 text-center shadow-card">
          <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-2xl bg-emerald-600/20 ring-1 ring-emerald-600/40"><Sparkles className="text-emerald-300" /></div>
          <h2 className="mt-4 text-xl font-semibold text-ink-100">Create your first inbound</h2>
          <p className="mx-auto mt-1 max-w-md text-sm text-ink-400">Pick a preset. VLESS + REALITY works out of the box — no domain or certificate needed.</p>
          {admin && nodes.length > 0 && (
            <div className="mx-auto mt-6 grid max-w-3xl gap-3 sm:grid-cols-3">
              {PRESETS.slice(0, 3).map((p) => (
                <button key={p.id} onClick={() => setEditing({ inbound: "new", preset: p.id })} className="rounded-xl border border-ink-700 bg-ink-900/70 p-4 text-left transition hover:border-emerald-600">
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-ink-100">{p.recommended && <Sparkles size={13} className="text-emerald-400" />}{p.label}</div>
                  <div className="mt-1 text-xs text-ink-500">{p.hint}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
          {inbounds.map((i) => (
            <InboundCard
              key={i.id}
              i={i}
              canEdit={admin}
              onEdit={() => setEditing({ inbound: i })}
              onToggle={() => toggle.mutate(i)}
              onDelete={() => confirm(`Delete inbound ${i.remark}? Users lose this config.`) && del.mutate(i.id)}
            />
          ))}
        </div>
      )}
      <ErrorText error={del.error || toggle.error} />

      <div className="mb-3 mt-10 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-400">Nodes</h2>
        {admin && <button className="text-xs font-medium text-emerald-300 hover:text-emerald-200" onClick={() => setAdding(true)}>+ Add node</button>}
      </div>
      {nodes.length === 0 ? (
        <Card><Empty>No nodes yet. {admin ? <button className="text-emerald-300 hover:underline" onClick={() => setAdding(true)}>Add a node</button> : "An admin can add one."}</Empty></Card>
      ) : (
        <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
          {nodes.map((n) => <NodeCard key={n.agent_id} n={n} />)}
          {admin && (
            <button onClick={() => setAdding(true)} className="flex min-h-[180px] flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-ink-600 text-ink-400 transition hover:border-emerald-600 hover:text-emerald-300">
              <Plus size={22} /><span className="text-sm font-medium">Add node</span><span className="text-xs text-ink-500">Serve inbounds from another server</span>
            </button>
          )}
        </div>
      )}
      {adding && <AddNodeModal onClose={() => setAdding(false)} />}
      {editing && <InboundModal inbound={editing.inbound} preset={editing.preset} nodes={nodes} onClose={() => setEditing(null)} />}
    </>
  );
}
