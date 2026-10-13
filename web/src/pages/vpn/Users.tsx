import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Ban, Edit3, KeyRound, Link2, MoreVertical, Plus, QrCode as QrIcon, RotateCcw, Search, Smartphone, Trash2, UserCheck, Wifi } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { api, qs } from "../../api/client";
import type { Inbound, UserActivity, VpnUser } from "../../api/types";
import { Card, Empty, ErrorText, Field, Modal, PageHeader, Spinner } from "../../components/ui";
import { CopyButton, expiryText, GB, linkLabel, linkProtocol, QrCode, UsageBar, VpnStatusBadge } from "../../components/vpn";
import { fmtRelative, fmtTime, fmtTraffic } from "../../lib/format";
import { useAuth } from "../../lib/auth";

interface FormState {
  username: string;
  data_limit_gb: string;
  expire_mode: "never" | "days" | "date";
  expire_days: string;
  expire_date: string;
  all_inbounds: boolean;
  inbound_ids: number[];
  note: string;
  enabled: boolean;
}

const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

function toForm(u?: VpnUser): FormState {
  return {
    username: u?.username ?? "",
    data_limit_gb: u ? (u.data_limit ? String(+(u.data_limit / GB).toFixed(3)) : "0") : "50",
    expire_mode: u ? (u.expire_at ? "date" : "never") : "days",
    expire_days: "30",
    expire_date: u?.expire_at ? toLocalInput(u.expire_at) : "",
    all_inbounds: u ? u.inbound_ids === null : true,
    inbound_ids: u?.inbound_ids ?? [],
    note: u?.note ?? "",
    enabled: u?.enabled ?? true,
  };
}

export function UserModal({ user, inbounds, onClose }: { user: VpnUser | "new"; inbounds: Inbound[]; onClose: () => void }) {
  const qc = useQueryClient();
  const isNew = user === "new";
  const [f, setF] = useState<FormState>(toForm(isNew ? undefined : user));
  const set = <K extends keyof FormState>(k: K, v: FormState[K]) => setF((s) => ({ ...s, [k]: v }));
  const save = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {
        username: f.username.trim(),
        data_limit_gb: Number(f.data_limit_gb || 0),
        note: f.note,
        enabled: f.enabled,
      };
      if (f.expire_mode === "days") body.expire_days = Number(f.expire_days);
      if (f.expire_mode === "date" && f.expire_date) body.expire_at = new Date(f.expire_date).toISOString();
      if (isNew) {
        body.inbound_ids = f.all_inbounds ? null : f.inbound_ids;
        return api<VpnUser>("/vpn/users", { method: "POST", json: body });
      }
      if (f.expire_mode === "never") body.clear_expire = true;
      if (f.all_inbounds) body.all_inbounds = true;
      else body.inbound_ids = f.inbound_ids;
      return api<VpnUser>(`/vpn/users/${user.id}`, { method: "PATCH", json: body });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-users"] });
      qc.invalidateQueries({ queryKey: ["vpn-overview"] });
      onClose();
    },
  });
  return (
    <Modal open onClose={onClose} title={isNew ? "New user" : `Edit ${user.username}`} wide>
      <form className="space-y-5" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Username" hint="Letters, digits, . _ -">
            <input className="input" value={f.username} onChange={(e) => set("username", e.target.value)} required minLength={2} maxLength={64} pattern="[A-Za-z0-9_.\-]+" autoFocus />
          </Field>
          <Field label="Data limit (GB)" hint="0 = unlimited">
            <input className="input" type="number" min={0} step="any" value={f.data_limit_gb} onChange={(e) => set("data_limit_gb", e.target.value)} />
          </Field>
        </div>
        <div>
          <span className="label">Expiry</span>
          <div className="flex flex-wrap items-center gap-2">
            <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5">
              {(["never", "days", "date"] as const).map((m) => (
                <button type="button" key={m} onClick={() => set("expire_mode", m)} className={`rounded-md px-3 py-1.5 text-xs font-semibold ${f.expire_mode === m ? "bg-emerald-700/40 text-emerald-200" : "text-ink-400"}`}>
                  {m === "never" ? "Never" : m === "days" ? "In N days" : "On date"}
                </button>
              ))}
            </div>
            {f.expire_mode === "days" && (
              <div className="flex items-center gap-2">
                <input className="input w-24" type="number" min={1} value={f.expire_days} onChange={(e) => set("expire_days", e.target.value)} />
                <span className="text-sm text-ink-400">days from now</span>
                {[7, 30, 90].map((d) => (
                  <button type="button" key={d} className="rounded-md border border-ink-700 px-2 py-1 text-xs text-ink-300 hover:border-emerald-700" onClick={() => set("expire_days", String(d))}>{d}d</button>
                ))}
              </div>
            )}
            {f.expire_mode === "date" && <input className="input w-60" type="datetime-local" value={f.expire_date} onChange={(e) => set("expire_date", e.target.value)} required />}
          </div>
          {!isNew && user.expire_at && <p className="mt-1 text-xs text-ink-500">Currently: {fmtTime(user.expire_at)}</p>}
        </div>
        <div>
          <span className="label">Inbounds</span>
          <label className="mb-2 flex items-center gap-2 text-sm text-ink-200">
            <input type="checkbox" className="accent-emerald-500" checked={f.all_inbounds} onChange={(e) => set("all_inbounds", e.target.checked)} />
            All inbounds (including ones added later)
          </label>
          {!f.all_inbounds && (
            <div className="grid gap-2 sm:grid-cols-2">
              {inbounds.length === 0 && <p className="text-sm text-ink-500">No inbounds yet.</p>}
              {inbounds.map((i) => (
                <label key={i.id} className="flex items-center gap-2 rounded-lg border border-ink-700 px-3 py-2 text-sm text-ink-200 hover:border-ink-600">
                  <input
                    type="checkbox"
                    className="accent-emerald-500"
                    checked={f.inbound_ids.includes(i.id)}
                    onChange={(e) => set("inbound_ids", e.target.checked ? [...f.inbound_ids, i.id] : f.inbound_ids.filter((x) => x !== i.id))}
                  />
                  <span className="truncate">{i.remark}</span>
                  <span className="ml-auto text-[11px] uppercase text-ink-500">{i.protocol} · {i.agent_name}</span>
                </label>
              ))}
            </div>
          )}
        </div>
        <Field label="Note"><input className="input" value={f.note} maxLength={500} onChange={(e) => set("note", e.target.value)} placeholder="Optional (phone, Telegram ID, …)" /></Field>
        <label className="flex items-center gap-2 text-sm text-ink-200">
          <input type="checkbox" className="accent-emerald-500" checked={f.enabled} onChange={(e) => set("enabled", e.target.checked)} /> Enabled
        </label>
        <ErrorText error={save.error} />
        <div className="flex justify-end gap-2">
          <button type="button" className="btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn-primary" disabled={save.isPending}>{isNew ? "Create user" : "Save"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function ShareModal({ user, onClose }: { user: VpnUser; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["vpn-links", user.id, user.sub_token], queryFn: () => api<{ links: string[] }>(`/vpn/users/${user.id}/links`) });
  const [qr, setQr] = useState<string>(user.sub_url);
  const links = data?.links ?? [];
  return (
    <Modal open onClose={onClose} title={`Share — ${user.username}`} wide>
      <div className="grid gap-6 md:grid-cols-[240px_1fr]">
        <div className="flex flex-col items-center gap-2">
          <QrCode text={qr} size={230} />
          <p className="max-w-[230px] text-center text-[11px] text-ink-500">{qr === user.sub_url ? "Subscription link — scan with v2rayNG, Hiddify, Streisand, …" : linkLabel(qr)}</p>
        </div>
        <div className="min-w-0 space-y-4">
          <div>
            <span className="label">Subscription link</span>
            <div className="flex items-center gap-2">
              <input readOnly value={user.sub_url} className="input mono flex-1 text-xs" onFocus={(e) => e.target.select()} />
              <CopyButton text={user.sub_url} />
              <button className={`btn-ghost px-2.5 py-1.5 text-xs ${qr === user.sub_url ? "border-emerald-700" : ""}`} onClick={() => setQr(user.sub_url)}><QrIcon size={13} /></button>
            </div>
            <p className="mt-1 text-[11px] text-ink-500">Updates automatically in the client when inbounds change. Opening it in a browser shows the user's status page.</p>
          </div>
          <div>
            <span className="label">Individual configs</span>
            {links.length === 0 ? (
              <p className="text-sm text-ink-500">{user.status === "active" ? "No inbounds assigned yet." : `User is ${user.status} — configs are not served.`}</p>
            ) : (
              <ul className="space-y-2">
                {links.map((l) => (
                  <li key={l} className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2">
                    <span className="badge bg-ink-750 text-[10px] text-emerald-300">{linkProtocol(l)}</span>
                    <span className="min-w-0 flex-1 truncate text-sm text-ink-200">{linkLabel(l)}</span>
                    <CopyButton text={l} />
                    <button className={`btn-ghost px-2.5 py-1.5 text-xs ${qr === l ? "border-emerald-700" : ""}`} onClick={() => setQr(l)} aria-label="Show QR"><QrIcon size={13} /></button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>
    </Modal>
  );
}

export function ActivityModal({ user, onClose }: { user: VpnUser; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: ["vpn-user-activity", user.id],
    queryFn: () => api<UserActivity>(`/vpn/users/${user.id}/activity`),
    refetchInterval: 10000,
  });
  return (
    <Modal open onClose={onClose} title={`Activity — ${user.username}`} wide>
      {isLoading || !data ? <Spinner /> : (
        <div className="space-y-5">
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-400">
              <Wifi size={13} />Connected now
              {data.connections.length > 0 && <span className="rounded-md bg-emerald-900/60 px-1.5 py-0.5 text-[11px] text-emerald-300">{new Set(data.connections.map((c) => c.ip)).size} IP</span>}
            </div>
            {data.connections.length === 0 ? (
              <p className="text-sm text-ink-500">Not connected{data.last_online_at ? ` · last online ${fmtRelative(data.last_online_at)}` : ""}.</p>
            ) : (
              <table className="table">
                <thead><tr><th>IP</th><th>Node</th><th>Last activity</th></tr></thead>
                <tbody>
                  {data.connections.map((c) => (
                    <tr key={`${c.node}-${c.ip}`}>
                      <td className="font-mono text-sm text-ink-100"><span className="inline-flex items-center gap-2"><span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />{c.ip}<CopyButton text={c.ip} label="" /></span></td>
                      <td className="text-sm text-ink-300">{c.node}</td>
                      <td className="text-xs text-ink-400">{fmtRelative(c.last_seen)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div>
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-ink-400"><Smartphone size={13} />Apps using the subscription</div>
            {data.apps.length === 0 ? <p className="text-sm text-ink-500">The subscription link hasn't been added to an app yet.</p> : (
              <table className="table">
                <thead><tr><th>App</th><th>Last update</th><th>From IP</th><th>Updates</th></tr></thead>
                <tbody>
                  {data.apps.map((a) => (
                    <tr key={a.user_agent}>
                      <td><div className="text-sm font-medium text-ink-100">{a.app} {a.version && <span className="text-ink-400">{a.version}</span>}</div><div className="max-w-[260px] truncate font-mono text-[10px] text-ink-500" title={a.user_agent}>{a.user_agent || "—"}</div></td>
                      <td className="whitespace-nowrap text-xs text-ink-400" title={fmtTime(a.last_at)}>{fmtRelative(a.last_at)}</td>
                      <td className="font-mono text-xs text-ink-300">{a.last_ip}</td>
                      <td className="text-sm text-ink-300">{a.fetches}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <p className="text-[11px] text-ink-500">Connected IPs come from Xray on each node and refresh every ~10 s. Apps are recorded when they update the subscription.</p>
        </div>
      )}
    </Modal>
  );
}

function RowMenu({ u, onEdit, onShare, onActivity }: { u: VpnUser; onEdit: () => void; onShare: () => void; onActivity: () => void }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  const act = useMutation({
    mutationFn: ({ path, method = "POST", json }: { path: string; method?: string; json?: unknown }) => api(path, { method, json }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["vpn-users"] });
      qc.invalidateQueries({ queryKey: ["vpn-overview"] });
    },
  });
  const item = (icon: ReactNode, label: string, fn: () => void, danger = false) => (
    <button className={`flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-ink-800 ${danger ? "text-red-300" : "text-ink-200"}`} onClick={() => { setOpen(false); fn(); }}>
      {icon} {label}
    </button>
  );
  return (
    <div className="relative" ref={ref}>
      <button className="rounded-md p-1.5 text-ink-400 hover:bg-ink-800 hover:text-ink-100" onClick={() => setOpen(!open)} aria-label="Actions"><MoreVertical size={16} /></button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-52 rounded-xl border border-ink-700 bg-ink-850 p-1 shadow-card">
          {item(<Link2 size={15} />, "Share / QR", onShare)}
          {item(<Activity size={15} />, "Activity · IPs & apps", onActivity)}
          {item(<Edit3 size={15} />, "Edit", onEdit)}
          {item(<RotateCcw size={15} />, "Reset traffic", () => act.mutate({ path: `/vpn/users/${u.id}/reset-traffic` }))}
          {u.enabled
            ? item(<Ban size={15} />, "Disable", () => act.mutate({ path: `/vpn/users/${u.id}`, method: "PATCH", json: { enabled: false } }))
            : item(<UserCheck size={15} />, "Enable", () => act.mutate({ path: `/vpn/users/${u.id}`, method: "PATCH", json: { enabled: true } }))}
          {item(<KeyRound size={15} />, "Revoke links", () => confirm(`Revoke all links of ${u.username}? Old configs and the old subscription stop working.`) && act.mutate({ path: `/vpn/users/${u.id}/revoke` }))}
          {item(<Trash2 size={15} />, "Delete", () => confirm(`Delete ${u.username}?`) && act.mutate({ path: `/vpn/users/${u.id}`, method: "DELETE" }), true)}
        </div>
      )}
    </div>
  );
}

const FILTERS = ["", "active", "online", "expired", "limited", "disabled"] as const;

export default function VpnUsers() {
  const { can } = useAuth();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<(typeof FILTERS)[number]>("");
  const [editing, setEditing] = useState<VpnUser | "new" | null>(null);
  const [sharing, setSharing] = useState<VpnUser | null>(null);
  const [watching, setWatching] = useState<VpnUser | null>(null);
  const { data, isLoading } = useQuery({
    queryKey: ["vpn-users", search, status],
    queryFn: () => api<VpnUser[]>(`/vpn/users${qs({ search, status })}`),
    refetchInterval: 10000,
  });
  const { data: inbounds = [] } = useQuery({ queryKey: ["vpn-inbounds"], queryFn: () => api<Inbound[]>("/vpn/inbounds") });
  const users = data ?? [];
  return (
    <>
      <PageHeader
        title="Users"
        subtitle="VPN accounts, their limits and subscription links"
        actions={can("operator") && <button className="btn-primary" onClick={() => setEditing("new")}><Plus size={15} />New user</button>}
      />
      <Card
        bodyClass="overflow-x-auto"
        title={
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative">
              <Search size={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" />
              <input className="input w-56 pl-8" placeholder="Search username" value={search} onChange={(e) => setSearch(e.target.value)} />
            </div>
            <div className="inline-flex flex-wrap rounded-lg border border-ink-700 bg-ink-900 p-0.5">
              {FILTERS.map((s) => (
                <button key={s} onClick={() => setStatus(s)} className={`rounded-md px-2.5 py-1 text-xs font-medium capitalize ${status === s ? "bg-emerald-700/40 text-emerald-200" : "text-ink-400 hover:text-ink-200"}`}>
                  {s || "all"}
                </button>
              ))}
            </div>
          </div>
        }
      >
        {isLoading ? <Spinner /> : users.length === 0 ? (
          <Empty>{search || status ? "No users match." : "No users yet. Create an inbound first, then add users."}</Empty>
        ) : (
          <table className="table">
            <thead><tr><th>User</th><th>Status</th><th>Usage</th><th>Expiry</th><th>Last online</th><th /></tr></thead>
            <tbody>
              {users.map((u) => {
                const exp = expiryText(u.expire_at);
                return (
                  <tr key={u.id}>
                    <td>
                      <button className="text-left font-medium text-ink-100 hover:text-emerald-300" onClick={() => setSharing(u)}>{u.username}</button>
                      {u.note && <div className="max-w-[220px] truncate text-xs text-ink-500">{u.note}</div>}
                    </td>
                    <td>
                      <div className="flex items-center gap-1.5">
                        <VpnStatusBadge status={u.status} online={u.online} />
                        {u.online_ips > 0 && (
                          <button onClick={() => setWatching(u)} className="badge bg-sky-600/20 text-sky-300 hover:bg-sky-600/30" title="Connected IPs">
                            <Wifi size={11} />{u.online_ips} IP
                          </button>
                        )}
                      </div>
                    </td>
                    <td><UsageBar used={u.used} limit={u.data_limit} /><div className="mt-0.5 text-[10px] text-ink-500">↑ {fmtTraffic(u.used_up)} · ↓ {fmtTraffic(u.used_down)}</div></td>
                    <td className={`whitespace-nowrap text-sm ${exp.tone}`} title={u.expire_at ? fmtTime(u.expire_at) : ""}>{exp.text}</td>
                    <td className="whitespace-nowrap text-xs text-ink-400">{u.last_online_at ? fmtRelative(u.last_online_at) : "never"}</td>
                    <td className="whitespace-nowrap text-right">
                      <div className="flex items-center justify-end gap-1">
                        <CopyButton text={u.sub_url} label="Sub link" />
                        {can("operator") && <RowMenu u={u} onEdit={() => setEditing(u)} onShare={() => setSharing(u)} onActivity={() => setWatching(u)} />}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Card>
      {editing && <UserModal user={editing} inbounds={inbounds} onClose={() => setEditing(null)} />}
      {sharing && <ShareModal user={sharing} onClose={() => setSharing(null)} />}
      {watching && <ActivityModal user={watching} onClose={() => setWatching(null)} />}
    </>
  );
}
