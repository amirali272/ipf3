import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, ArrowUp, Ban, Edit3, Globe2, Link2, Lock, Plus, Route, Shuffle, Sparkles, Trash2, Users } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import type { Inbound, Outbound, OutboundDetail, RoutingRule, RuleAction, VpnNode, VpnUser } from "../../api/types";
import { Empty, ErrorText, Field, Modal } from "../../components/ui";
import { Chip, Switch } from "../../components/vpn";
import { fmtTraffic } from "../../lib/format";
import { useAuth } from "../../lib/auth";

// ============================================================================ outbounds
interface Preview { remark: string; protocol?: string; address: string; port: number | null; network: string; security: string; config: { protocol: string } }

function OutboundModal({ outbound, nodes, onClose }: { outbound: Outbound | "new"; nodes: VpnNode[]; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = outbound === "new";
  const { data: detail } = useQuery({
    queryKey: ["vpn-outbound", isNew ? 0 : outbound.id],
    queryFn: () => api<OutboundDetail>(`/vpn/outbounds/${(outbound as Outbound).id}`),
    enabled: !isNew,
  });
  const [mode, setMode] = useState<"link" | "json">("link");
  const [link, setLink] = useState("");
  const [json, setJson] = useState("");
  const [remark, setRemark] = useState("");
  const [scope, setScope] = useState<"all" | "some">("all");
  const [picked, setPicked] = useState<string[]>([]);
  const [enabled, setEnabled] = useState(true);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [previewErr, setPreviewErr] = useState<unknown>(null);

  useEffect(() => {
    if (!detail) return;
    setRemark(detail.remark);
    setEnabled(detail.enabled);
    if (detail.agent_ids) { setScope("some"); setPicked(detail.agent_ids); }
    if (detail.link) { setMode("link"); setLink(detail.link); } else { setMode("json"); setJson(JSON.stringify(detail.config, null, 2)); }
  }, [detail]);

  const source = (): { link: string; config?: Record<string, unknown> } | null => {
    if (mode === "link") return link.trim() ? { link: link.trim() } : null;
    if (!json.trim()) return null;
    try { return { link: "", config: JSON.parse(json) }; } catch { return null; }
  };

  useEffect(() => {
    const src = source();
    setPreview(null);
    setPreviewErr(null);
    if (!src) return;
    const t = setTimeout(() => {
      api<Preview>("/vpn/outbounds/parse", { method: "POST", json: src }).then(setPreview, setPreviewErr);
    }, 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, link, json]);

  const save = useMutation({
    mutationFn: () => {
      const src = source();
      if (!src) throw new Error(mode === "json" ? "Invalid JSON" : "Paste a share link");
      const body = { ...src, remark, enabled, agent_ids: scope === "all" ? null : picked };
      return isNew ? api("/vpn/outbounds", { method: "POST", json: body }) : api(`/vpn/outbounds/${(outbound as Outbound).id}`, { method: "PUT", json: body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-outbounds"] });
      qc.invalidateQueries({ queryKey: ["vpn-nodes"] });
      onClose();
    },
  });

  return (
    <Modal open onClose={onClose} title={isNew ? "Add outbound" : `Edit ${(outbound as Outbound).remark}`} wide>
      <div className="space-y-4">
        <p className="text-sm text-ink-400">
          An outbound is an upstream server your nodes forward traffic to — paste any config link (from another panel, a provider, WARP…). Then add routing rules to decide which traffic uses it.
        </p>
        <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5 text-sm">
          {(["link", "json"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)} className={`rounded-md px-3 py-1.5 font-medium ${mode === m ? "bg-emerald-600 text-white" : "text-ink-300 hover:text-ink-100"}`}>
              {m === "link" ? "Share link" : "JSON"}
            </button>
          ))}
        </div>
        {mode === "link" ? (
          <Field label="Config link" hint="vless:// vmess:// trojan:// ss:// socks:// http(s):// wireguard://">
            <textarea className="input min-h-[92px] font-mono text-xs" value={link} onChange={(e) => setLink(e.target.value)} placeholder="vless://uuid@host:443?type=tcp&security=reality&…#name" spellCheck={false} />
          </Field>
        ) : (
          <Field label="Xray outbound JSON" hint="An outbound object, or a full client config (its first proxy outbound is used).">
            <textarea className="input min-h-[180px] font-mono text-xs" value={json} onChange={(e) => setJson(e.target.value)} placeholder='{"protocol": "socks", "settings": {"servers": [{"address": "1.2.3.4", "port": 1080}]}}' spellCheck={false} />
          </Field>
        )}
        {preview && (
          <div className="flex flex-wrap items-center gap-2 rounded-xl border border-emerald-800/50 bg-emerald-950/20 px-3 py-2.5 text-sm">
            <Chip tone="green">{preview.config.protocol}</Chip>
            {preview.network && <Chip>{preview.network}</Chip>}
            {preview.security !== "none" && <Chip tone="amber" icon={<Lock size={10} />}>{preview.security}</Chip>}
            <span className="font-mono text-xs text-ink-200">{preview.address}{preview.port ? `:${preview.port}` : ""}</span>
            {preview.remark && <span className="text-xs text-ink-400">“{preview.remark}”</span>}
          </div>
        )}
        <ErrorText error={previewErr} />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={remark} onChange={(e) => setRemark(e.target.value)} placeholder={preview?.remark || "e.g. Germany exit"} maxLength={128} /></Field>
          <Field label="Status">
            <label className="flex h-10 items-center gap-3 text-sm text-ink-300"><Switch on={enabled} onChange={() => setEnabled(!enabled)} />{enabled ? "Enabled" : "Disabled"}</label>
          </Field>
        </div>
        <Field label="Available on">
          <div className="space-y-2">
            <div className="flex gap-4 text-sm text-ink-200">
              <label className="flex items-center gap-2"><input type="radio" checked={scope === "all"} onChange={() => setScope("all")} />All nodes</label>
              <label className="flex items-center gap-2"><input type="radio" checked={scope === "some"} onChange={() => setScope("some")} />Selected nodes</label>
            </div>
            {scope === "some" && (
              <div className="flex flex-wrap gap-2">
                {nodes.map((n) => {
                  const on = picked.includes(n.agent_id);
                  return (
                    <button key={n.agent_id} type="button" onClick={() => setPicked(on ? picked.filter((x) => x !== n.agent_id) : [...picked, n.agent_id])}
                      className={`rounded-lg border px-3 py-1.5 text-sm ${on ? "border-emerald-600 bg-emerald-950/40 text-emerald-200" : "border-ink-700 text-ink-300 hover:border-ink-500"}`}>
                      {n.name}
                    </button>
                  );
                })}
              </div>
            )}
          </div>
        </Field>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending || (scope === "some" && !picked.length)} onClick={() => save.mutate()}>{isNew ? "Add outbound" : "Save"}</button>
        </div>
      </div>
    </Modal>
  );
}

function BuiltinCard({ icon, title, sub, tone }: { icon: ReactNode; title: string; sub: string; tone: string }) {
  return (
    <div className="flex items-center gap-3 rounded-2xl border border-ink-700/70 bg-ink-850/60 p-4">
      <div className={`flex h-10 w-10 items-center justify-center rounded-xl ring-1 ${tone}`}>{icon}</div>
      <div>
        <div className="text-sm font-semibold text-ink-100">{title}</div>
        <div className="text-xs text-ink-500">{sub}</div>
      </div>
      <span className="ml-auto text-[10px] uppercase tracking-wider text-ink-600">built-in</span>
    </div>
  );
}

function OutboundCard({ o, canEdit, onEdit, onToggle, onDelete }: { o: Outbound; canEdit: boolean; onEdit: () => void; onToggle: () => void; onDelete: () => void }) {
  return (
    <div className={`relative overflow-hidden rounded-2xl border bg-ink-850 p-5 shadow-card transition ${o.enabled ? "border-ink-700/70" : "border-ink-800 opacity-60"}`}>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-16 bg-gradient-to-b from-sky-500/10 to-transparent" />
      <div className="relative flex items-start gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-sky-600/15 ring-1 ring-sky-600/40"><Globe2 size={20} className="text-sky-300" /></div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-base font-semibold text-ink-100">{o.remark}</div>
          <div className="truncate font-mono text-[11px] text-ink-500">{o.address}{o.port ? `:${o.port}` : ""}</div>
        </div>
        <Switch on={o.enabled} onChange={onToggle} disabled={!canEdit} />
      </div>
      <div className="relative mt-3 flex flex-wrap gap-1.5">
        <Chip tone="green">{o.protocol}</Chip>
        {o.network && <Chip>{o.network}</Chip>}
        {o.security !== "none" && <Chip tone="amber" icon={<Lock size={10} />}>{o.security}</Chip>}
      </div>
      <div className="relative mt-4 grid grid-cols-3 gap-2 text-center">
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{fmtTraffic(o.down)}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">down</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{fmtTraffic(o.up)}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">up</div></div>
        <div className="rounded-xl bg-ink-900/70 py-2"><div className="text-sm font-bold text-ink-100">{o.rules}</div><div className="text-[10px] uppercase tracking-wider text-ink-500">rules</div></div>
      </div>
      <div className="relative mt-3 flex items-center justify-between gap-2">
        <div className="truncate text-xs text-ink-500">{o.agent_ids === null ? "All nodes" : o.nodes.join(", ") || "No nodes"}</div>
        {canEdit && (
          <div className="flex shrink-0 gap-1">
            <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100" onClick={onEdit} aria-label="Edit"><Edit3 size={15} /></button>
            <button className="rounded-lg p-1.5 text-ink-400 hover:bg-red-950/50 hover:text-red-300" onClick={onDelete} aria-label="Delete"><Trash2 size={15} /></button>
          </div>
        )}
      </div>
    </div>
  );
}

// ============================================================================ routing rules
type RuleDraft = Omit<RoutingRule, "id" | "position" | "outbound">;
const EMPTY_RULE: RuleDraft = { remark: "", action: "direct", outbound_id: null, inbound_ids: [], user_ids: [], domains: [], ips: [], port: "", network: "", protocols: [], enabled: true };

const TEMPLATES: { label: string; hint: string; icon: ReactNode; rule: (out: number | null) => Partial<RuleDraft> }[] = [
  { label: "Iranian sites → Direct", hint: "Don't send local traffic abroad", icon: <ArrowRight size={14} />, rule: () => ({ remark: "Iran direct", action: "direct", domains: ["geosite:category-ir", "domain:ir"], ips: ["geoip:ir"] }) },
  { label: "Block ads", hint: "geosite:category-ads-all", icon: <Ban size={14} />, rule: () => ({ remark: "Block ads", action: "block", domains: ["geosite:category-ads-all"] }) },
  { label: "All traffic → Outbound", hint: "Use an upstream for everything", icon: <Shuffle size={14} />, rule: (o) => ({ remark: "All via outbound", action: "outbound", outbound_id: o }) },
  { label: "Some sites → Outbound", hint: "e.g. Google, OpenAI, Netflix", icon: <Globe2 size={14} />, rule: (o) => ({ remark: "Sites via outbound", action: "outbound", outbound_id: o, domains: ["geosite:google", "geosite:openai", "geosite:netflix"] }) },
  { label: "Some users → Outbound", hint: "Pick users below", icon: <Users size={14} />, rule: (o) => ({ remark: "Users via outbound", action: "outbound", outbound_id: o }) },
];

const ruleBody = (r: RoutingRule): RuleDraft => ({ remark: r.remark, action: r.action, outbound_id: r.outbound_id, inbound_ids: r.inbound_ids, user_ids: r.user_ids, domains: r.domains, ips: r.ips, port: r.port, network: r.network, protocols: r.protocols, enabled: r.enabled });

const lines = (v: string) => v.split(/[\n,]+/).map((x) => x.trim()).filter(Boolean);

function PickList<T extends { id: number }>({ items, selected, onChange, label, search }: { items: T[]; selected: number[]; onChange: (v: number[]) => void; label: (t: T) => ReactNode; search: (t: T) => string }) {
  const [q, setQ] = useState("");
  const shown = items.filter((i) => !q || search(i).toLowerCase().includes(q.toLowerCase())).slice(0, 200);
  return (
    <div className="rounded-xl border border-ink-700 bg-ink-900/60">
      {items.length > 8 && <input className="w-full border-b border-ink-700 bg-transparent px-3 py-2 text-sm outline-none" placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} />}
      <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto p-2">
        {shown.length === 0 && <span className="px-1 text-xs text-ink-500">Nothing here yet</span>}
        {shown.map((i) => {
          const on = selected.includes(i.id);
          return (
            <button key={i.id} type="button" onClick={() => onChange(on ? selected.filter((x) => x !== i.id) : [...selected, i.id])}
              className={`rounded-md border px-2 py-1 text-xs ${on ? "border-emerald-600 bg-emerald-950/50 text-emerald-200" : "border-ink-700 text-ink-300 hover:border-ink-500"}`}>
              {label(i)}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function RuleModal({ rule, outbounds, inbounds, users, onClose }: { rule: RoutingRule | "new"; outbounds: Outbound[]; inbounds: Inbound[]; users: VpnUser[]; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = rule === "new";
  const [d, setD] = useState<RuleDraft>(() => (isNew ? { ...EMPTY_RULE } : ruleBody(rule)));
  const [domains, setDomains] = useState(() => d.domains.join("\n"));
  const [ips, setIps] = useState(() => d.ips.join("\n"));
  const set = (p: Partial<RuleDraft>) => setD((x) => ({ ...x, ...p }));
  const applyTemplate = (t: (typeof TEMPLATES)[number]) => {
    const r = { ...EMPTY_RULE, ...t.rule(outbounds[0]?.id ?? null) };
    setD(r);
    setDomains(r.domains.join("\n"));
    setIps(r.ips.join("\n"));
  };
  const final: RuleDraft = { ...d, domains: lines(domains), ips: lines(ips), outbound_id: d.action === "outbound" ? d.outbound_id : null };
  const matchesAll = !final.domains.length && !final.ips.length && !final.user_ids.length && !final.inbound_ids.length && !final.port && !final.network && !final.protocols.length;
  const save = useMutation({
    mutationFn: () => (isNew ? api("/vpn/routing", { method: "POST", json: final }) : api(`/vpn/routing/${(rule as RoutingRule).id}`, { method: "PUT", json: final })),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-routing"] });
      qc.invalidateQueries({ queryKey: ["vpn-outbounds"] });
      qc.invalidateQueries({ queryKey: ["vpn-nodes"] });
      onClose();
    },
  });
  const actions: { id: RuleAction; label: string; cls: string }[] = [
    { id: "direct", label: "Direct", cls: "bg-emerald-600 text-white" },
    { id: "block", label: "Block", cls: "bg-red-600 text-white" },
    { id: "outbound", label: "Outbound", cls: "bg-sky-600 text-white" },
  ];
  return (
    <Modal open onClose={onClose} title={isNew ? "Add routing rule" : "Edit routing rule"} wide>
      <div className="space-y-5">
        {isNew && (
          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wider text-ink-400">Start from a template</div>
            <div className="grid gap-2 sm:grid-cols-3">
              {TEMPLATES.map((t) => (
                <button key={t.label} type="button" onClick={() => applyTemplate(t)} className="rounded-xl border border-ink-700 bg-ink-900/70 p-3 text-left transition hover:border-emerald-600">
                  <div className="flex items-center gap-1.5 text-sm font-semibold text-ink-100">{t.icon}{t.label}</div>
                  <div className="mt-0.5 text-[11px] text-ink-500">{t.hint}</div>
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name"><input className="input" value={d.remark} onChange={(e) => set({ remark: e.target.value })} placeholder="e.g. Netflix via Germany" maxLength={128} /></Field>
          <Field label="Send matching traffic to">
            <div className="flex gap-2">
              <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5 text-sm">
                {actions.map((a) => (
                  <button key={a.id} type="button" onClick={() => set({ action: a.id, outbound_id: a.id === "outbound" ? d.outbound_id ?? outbounds[0]?.id ?? null : null })}
                    className={`rounded-md px-3 py-1.5 font-medium ${d.action === a.id ? a.cls : "text-ink-300 hover:text-ink-100"}`}>{a.label}</button>
                ))}
              </div>
            </div>
          </Field>
        </div>
        {d.action === "outbound" && (
          <Field label="Outbound">
            {outbounds.length ? (
              <select className="input" value={d.outbound_id ?? ""} onChange={(e) => set({ outbound_id: +e.target.value })}>
                {outbounds.map((o) => <option key={o.id} value={o.id}>{o.remark} — {o.protocol} {o.address}</option>)}
              </select>
            ) : <div className="text-sm text-amber-300">Add an outbound first.</div>}
          </Field>
        )}

        <div className="rounded-xl border border-ink-700/70 bg-ink-900/40 p-4">
          <div className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-400">When traffic matches <span className="normal-case text-ink-500">(all filled conditions must match)</span></div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Domains" hint="One per line: geosite:google, domain:example.com, full:a.b.com, keyword:abc, regexp:…">
              <textarea className="input min-h-[96px] font-mono text-xs" value={domains} onChange={(e) => setDomains(e.target.value)} placeholder={"geosite:openai\ndomain:netflix.com"} spellCheck={false} />
            </Field>
            <Field label="IPs" hint="One per line: geoip:ir, 1.2.3.0/24, 2001:db8::/32">
              <textarea className="input min-h-[96px] font-mono text-xs" value={ips} onChange={(e) => setIps(e.target.value)} placeholder={"geoip:ir\n8.8.8.8/32"} spellCheck={false} />
            </Field>
            <Field label="Users">
              <PickList items={users} selected={d.user_ids} onChange={(v) => set({ user_ids: v })} label={(u) => u.username} search={(u) => u.username} />
            </Field>
            <Field label="Inbounds">
              <PickList items={inbounds} selected={d.inbound_ids} onChange={(v) => set({ inbound_ids: v })} label={(i) => <>{i.remark} <span className="text-ink-500">· {i.agent_name}</span></>} search={(i) => `${i.remark} ${i.agent_name}`} />
            </Field>
            <Field label="Destination ports" hint="e.g. 443 or 53,80,1000-2000">
              <input className="input font-mono" value={d.port} onChange={(e) => set({ port: e.target.value })} placeholder="any" />
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Network">
                <select className="input" value={d.network} onChange={(e) => set({ network: e.target.value as RuleDraft["network"] })}>
                  <option value="">any</option><option value="tcp">TCP</option><option value="udp">UDP</option>
                </select>
              </Field>
              <Field label="Sniffed protocol">
                <div className="flex flex-wrap gap-1.5 pt-1">
                  {(["http", "tls", "quic", "bittorrent"] as const).map((p) => {
                    const on = d.protocols.includes(p);
                    return <button key={p} type="button" onClick={() => set({ protocols: on ? d.protocols.filter((x) => x !== p) : [...d.protocols, p] })} className={`rounded-md border px-2 py-1 text-xs ${on ? "border-emerald-600 bg-emerald-950/50 text-emerald-200" : "border-ink-700 text-ink-400"}`}>{p}</button>;
                  })}
                </div>
              </Field>
            </div>
          </div>
          {matchesAll && <div className="mt-3 rounded-lg bg-amber-950/30 px-3 py-2 text-xs text-amber-300">No conditions — this rule matches <b>all traffic</b>. Rules below it will never be reached.</div>}
        </div>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <button className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending || (d.action === "outbound" && !d.outbound_id)} onClick={() => save.mutate()}>{isNew ? "Add rule" : "Save"}</button>
        </div>
      </div>
    </Modal>
  );
}

function Target({ action, name }: { action: RuleAction; name?: string | null }) {
  const m = {
    direct: { cls: "border-emerald-700/60 bg-emerald-950/40 text-emerald-300", label: "Direct" },
    block: { cls: "border-red-800/60 bg-red-950/40 text-red-300", label: "Block" },
    outbound: { cls: "border-sky-700/60 bg-sky-950/40 text-sky-300", label: name ?? "Outbound" },
  }[action];
  return <span className={`inline-flex max-w-[180px] items-center gap-1 truncate rounded-lg border px-2.5 py-1 text-xs font-semibold ${m.cls}`}>{m.label}</span>;
}

function Conditions({ r, inboundName, userName }: { r: RuleDraft; inboundName: (id: number) => string; userName: (id: number) => string }) {
  const chips: ReactNode[] = [];
  const many = (label: string, items: string[]) => chips.push(
    <span key={label} className="inline-flex max-w-full items-baseline gap-1 rounded-md bg-ink-800 px-2 py-0.5 text-[11px] text-ink-300">
      <span className="shrink-0 text-ink-500">{label}</span>
      <span className="min-w-0 break-all font-mono">{items.slice(0, 3).join(", ")}{items.length > 3 ? ` +${items.length - 3}` : ""}</span>
    </span>,
  );
  if (r.domains.length) many("domain", r.domains);
  if (r.ips.length) many("ip", r.ips);
  if (r.user_ids.length) many("user", r.user_ids.map(userName));
  if (r.inbound_ids.length) many("inbound", r.inbound_ids.map(inboundName));
  if (r.port) many("port", [r.port]);
  if (r.network) many("net", [r.network]);
  if (r.protocols.length) many("proto", r.protocols);
  if (!chips.length) return <span className="text-xs font-semibold text-amber-300">All traffic</span>;
  return <div className="flex flex-wrap gap-1.5">{chips}</div>;
}

function SystemRow({ label, target }: { label: ReactNode; target: RuleAction }) {
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm text-ink-500">
      <Lock size={13} className="shrink-0" />
      <div className="flex-1">{label}</div>
      <ArrowRight size={14} />
      <Target action={target} />
      <span className="hidden w-[132px] text-right text-[10px] uppercase tracking-wider text-ink-600 sm:inline">always</span>
    </div>
  );
}

// ============================================================================ page
export default function VpnOutbounds() {
  const { can } = useAuth();
  const admin = can("admin");
  const qc = useQueryClient();
  const [editOut, setEditOut] = useState<Outbound | "new" | null>(null);
  const [editRule, setEditRule] = useState<RoutingRule | "new" | null>(null);
  const { data: outbounds = [] } = useQuery({ queryKey: ["vpn-outbounds"], queryFn: () => api<Outbound[]>("/vpn/outbounds"), refetchInterval: 10000 });
  const { data: rules = [] } = useQuery({ queryKey: ["vpn-routing"], queryFn: () => api<RoutingRule[]>("/vpn/routing") });
  const { data: nodes = [] } = useQuery({ queryKey: ["vpn-nodes"], queryFn: () => api<VpnNode[]>("/vpn/nodes"), refetchInterval: 10000 });
  const { data: inbounds = [] } = useQuery({ queryKey: ["vpn-inbounds"], queryFn: () => api<Inbound[]>("/vpn/inbounds") });
  const { data: users = [] } = useQuery({ queryKey: ["vpn-users-all"], queryFn: () => api<VpnUser[]>("/vpn/users") });
  const inboundName = useMemo(() => { const m = new Map(inbounds.map((i) => [i.id, i.remark])); return (id: number) => m.get(id) ?? `#${id} (deleted)`; }, [inbounds]);
  const userName = useMemo(() => { const m = new Map(users.map((u) => [u.id, u.username])); return (id: number) => m.get(id) ?? `#${id}`; }, [users]);
  const syncing = nodes.filter((n) => n.online && n.xray_installed && !n.in_sync).length;

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["vpn-outbounds"] });
    qc.invalidateQueries({ queryKey: ["vpn-routing"] });
    qc.invalidateQueries({ queryKey: ["vpn-nodes"] });
  };
  const toggleOut = useMutation({
    mutationFn: async (o: Outbound) => {
      const d = await api<OutboundDetail>(`/vpn/outbounds/${o.id}`);
      return api(`/vpn/outbounds/${o.id}`, { method: "PUT", json: { remark: d.remark, link: d.link, config: d.link ? undefined : d.config, agent_ids: d.agent_ids, enabled: !d.enabled } });
    },
    onSuccess: refresh,
  });
  const delOut = useMutation({ mutationFn: (id: number) => api(`/vpn/outbounds/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const toggleRule = useMutation({ mutationFn: (r: RoutingRule) => api(`/vpn/routing/${r.id}`, { method: "PUT", json: { ...ruleBody(r), enabled: !r.enabled } }), onSuccess: refresh });
  const delRule = useMutation({ mutationFn: (id: number) => api(`/vpn/routing/${id}`, { method: "DELETE" }), onSuccess: refresh });
  const order = useMutation({ mutationFn: (ids: number[]) => api(`/vpn/routing/order`, { method: "POST", json: { ids } }), onSuccess: refresh });
  const move = (idx: number, dir: -1 | 1) => {
    const ids = rules.map((r) => r.id);
    const j = idx + dir;
    if (j < 0 || j >= ids.length) return;
    [ids[idx], ids[j]] = [ids[j], ids[idx]];
    order.mutate(ids);
  };

  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink-100">Outbounds & routing</h1>
          <p className="mt-1 text-sm text-ink-400">Forward user traffic to other servers and decide what goes where</p>
        </div>
        {admin && (
          <div className="flex gap-2">
            <button className="btn-ghost" onClick={() => setEditRule("new")}><Route size={15} />Add rule</button>
            <button className="btn-primary" onClick={() => setEditOut("new")}><Plus size={15} />Add outbound</button>
          </div>
        )}
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-2 rounded-2xl border border-ink-700/70 bg-gradient-to-r from-ink-850 to-emerald-950/30 px-5 py-4 text-sm text-ink-300">
        <span className="rounded-lg bg-ink-800 px-2.5 py-1 font-medium text-ink-100">User</span><ArrowRight size={14} className="text-ink-500" />
        <span className="rounded-lg bg-ink-800 px-2.5 py-1 font-medium text-ink-100">Inbound on a node</span><ArrowRight size={14} className="text-ink-500" />
        <span className="rounded-lg bg-emerald-900/50 px-2.5 py-1 font-medium text-emerald-200">Routing rules · first match wins</span><ArrowRight size={14} className="text-ink-500" />
        <Target action="direct" /><Target action="block" /><Target action="outbound" name="Outbound" />
        {syncing > 0 && <span className="ml-auto flex items-center gap-1.5 text-xs text-sky-300"><span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />Applying to {syncing} node{syncing > 1 ? "s" : ""}…</span>}
      </div>

      <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-ink-400">Outbounds</h2>
      <div className="grid gap-5 md:grid-cols-2 2xl:grid-cols-3">
        {outbounds.map((o) => (
          <OutboundCard key={o.id} o={o} canEdit={admin} onEdit={() => setEditOut(o)} onToggle={() => toggleOut.mutate(o)}
            onDelete={() => confirm(`Delete outbound ${o.remark}?`) && delOut.mutate(o.id)} />
        ))}
        {admin && (
          <button onClick={() => setEditOut("new")} className="flex min-h-[200px] flex-col items-center justify-center gap-2 rounded-2xl border border-dashed border-ink-600 text-ink-400 transition hover:border-emerald-600 hover:text-emerald-300">
            <Link2 size={22} /><span className="text-sm font-medium">Add outbound from a config link</span><span className="text-xs text-ink-500">vless · vmess · trojan · ss · socks · http · wireguard</span>
          </button>
        )}
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        <BuiltinCard icon={<ArrowRight size={18} className="text-emerald-300" />} title="Direct" sub="Out through the node's own internet" tone="bg-emerald-600/15 ring-emerald-600/40" />
        <BuiltinCard icon={<Ban size={18} className="text-red-300" />} title="Block" sub="Drop the connection" tone="bg-red-600/15 ring-red-600/40" />
      </div>
      <ErrorText error={toggleOut.error || delOut.error} />

      <div className="mb-3 mt-10 flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wider text-ink-400">Routing rules</h2>
        {admin && <button className="text-xs font-medium text-emerald-300 hover:text-emerald-200" onClick={() => setEditRule("new")}>+ Add rule</button>}
      </div>
      <div className="overflow-hidden rounded-2xl border border-ink-700/70 bg-ink-850 shadow-card">
        <div className="divide-y divide-ink-800">
          <SystemRow label="Private & local networks (geoip:private)" target="block" />
          <SystemRow label="BitTorrent" target="block" />
          {rules.length === 0 && (
            <div className="px-4 py-8">
              <Empty>
                <div className="flex flex-col items-center gap-2">
                  <Sparkles className="text-emerald-400" size={20} />
                  No rules yet — all traffic goes out directly from each node.
                  {admin && <button className="text-emerald-300 hover:underline" onClick={() => setEditRule("new")}>Add your first rule</button>}
                </div>
              </Empty>
            </div>
          )}
          {rules.map((r, idx) => (
            <div key={r.id} className={`flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-3 ${r.enabled ? "" : "opacity-50"}`}>
              <div className="flex min-w-0 flex-1 items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-ink-800 text-xs font-bold text-ink-300">{idx + 1}</span>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-semibold text-ink-100">{r.remark || <span className="text-ink-400">Untitled rule</span>}</div>
                  <div className="mt-1"><Conditions r={r} inboundName={inboundName} userName={userName} /></div>
                </div>
              </div>
              <div className="flex items-center justify-between gap-3 pl-10 sm:justify-end sm:pl-0">
                <div className="flex items-center gap-2"><ArrowRight size={14} className="text-ink-500" /><Target action={r.action} name={r.outbound} /></div>
                {admin && (
                  <div className="flex items-center gap-1">
                    <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100 disabled:opacity-30" disabled={idx === 0 || order.isPending} onClick={() => move(idx, -1)} aria-label="Move up"><ArrowUp size={15} /></button>
                    <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100 disabled:opacity-30" disabled={idx === rules.length - 1 || order.isPending} onClick={() => move(idx, 1)} aria-label="Move down"><ArrowDown size={15} /></button>
                    <Switch on={r.enabled} onChange={() => toggleRule.mutate(r)} />
                    <button className="rounded-lg p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100" onClick={() => setEditRule(r)} aria-label="Edit"><Edit3 size={15} /></button>
                    <button className="rounded-lg p-1.5 text-ink-400 hover:bg-red-950/50 hover:text-red-300" onClick={() => confirm("Delete this rule?") && delRule.mutate(r.id)} aria-label="Delete"><Trash2 size={15} /></button>
                  </div>
                )}
              </div>
            </div>
          ))}
          <SystemRow label="Anything else" target="direct" />
        </div>
      </div>
      <ErrorText error={toggleRule.error || delRule.error || order.error} />
      <p className="mt-3 text-xs text-ink-500">
        Rules are checked top to bottom on every node; the first match decides. A rule that uses an outbound only applies on nodes where that outbound is available.
        Changes reach nodes within ~10 seconds.
      </p>

      {editOut && <OutboundModal outbound={editOut} nodes={nodes} onClose={() => setEditOut(null)} />}
      {editRule && <RuleModal rule={editRule} outbounds={outbounds} inbounds={inbounds} users={users} onClose={() => setEditRule(null)} />}
    </>
  );
}
