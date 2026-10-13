import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowRight, ArrowUp, CalendarClock, Network, Plus, QrCode as QrIcon, Search, UserCheck, Users, Wifi } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import type { Inbound, VpnNode, VpnOverview, VpnUser } from "../../api/types";
import { DailyBars } from "../../components/charts";
import { Card, Empty } from "../../components/ui";
import { CopyButton, expiryText, UsageBar, VpnStatusBadge } from "../../components/vpn";
import { useAuth } from "../../lib/auth";
import { fmtRelative } from "../../lib/format";
import { ShareModal, UserModal } from "./Users";
import { fmtTraffic } from "../../lib/format";

function UsersPanel() {
  const { can } = useAuth();
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [sharing, setSharing] = useState<VpnUser | null>(null);
  const { data: users = [] } = useQuery({ queryKey: ["vpn-users", "", ""], queryFn: () => api<VpnUser[]>("/vpn/users"), refetchInterval: 10000 });
  const { data: inbounds = [] } = useQuery({ queryKey: ["vpn-inbounds"], queryFn: () => api<Inbound[]>("/vpn/inbounds") });
  const rank = (u: VpnUser) => (u.online ? 2e13 : 0) + (u.last_online_at ? new Date(u.last_online_at).getTime() / 1000 : 0);
  const shown = users
    .filter((u) => !q || u.username.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => rank(b) - rank(a))
    .slice(0, 10);
  return (
    <section className="card mt-6 overflow-hidden">
      <div className="card-header flex-wrap">
        <h2 className="flex items-center gap-2 text-base font-semibold text-ink-100">
          <Users size={18} className="text-emerald-400" />Users
          <span className="rounded-md bg-ink-750 px-1.5 text-xs font-medium text-ink-300">{users.length}</span>
        </h2>
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-500" />
            <input className="input w-44 py-1.5 pl-8 text-sm" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          {can("operator") && <button className="btn-primary py-1.5" onClick={() => setCreating(true)}><Plus size={14} />New user</button>}
          <Link to="/vpn/users" className="btn-ghost py-1.5 text-xs">All <ArrowRight size={12} /></Link>
        </div>
      </div>
      {shown.length === 0 ? (
        <Empty>{users.length ? "No users match." : "No users yet — create one to get a subscription link."}</Empty>
      ) : (
        <ul className="divide-y divide-ink-800">
          {shown.map((u) => {
            const exp = expiryText(u.expire_at);
            return (
              <li key={u.id} className="grid grid-cols-[auto_1fr_auto] items-center gap-4 px-4 py-3 transition hover:bg-ink-800/40 md:grid-cols-[auto_minmax(140px,1fr)_minmax(160px,1.2fr)_120px_auto]">
                <div className="relative">
                  <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-ink-700 to-ink-800 text-sm font-bold uppercase text-emerald-300 ring-1 ring-ink-600">
                    {u.username.slice(0, 2)}
                  </div>
                  <span className={`absolute -bottom-0.5 -right-0.5 h-3.5 w-3.5 rounded-full border-2 border-ink-850 ${u.online ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-ink-600"}`} />
                </div>
                <div className="min-w-0">
                  <button onClick={() => setSharing(u)} className="truncate font-medium text-ink-100 hover:text-emerald-300">{u.username}</button>
                  <div className="mt-0.5 flex items-center gap-2"><VpnStatusBadge status={u.status} />
                    <span className="hidden text-[11px] text-ink-500 sm:inline">{u.online ? "online now" : u.last_online_at ? `seen ${fmtRelative(u.last_online_at)}` : "never connected"}</span>
                  </div>
                </div>
                <div className="hidden md:block"><UsageBar used={u.used} limit={u.data_limit} /></div>
                <div className={`hidden text-sm md:block ${exp.tone}`}>{exp.text}</div>
                <div className="flex items-center gap-1.5">
                  <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setSharing(u)} aria-label="QR and links"><QrIcon size={13} /></button>
                  <CopyButton text={u.sub_url} label="Sub" />
                </div>
              </li>
            );
          })}
        </ul>
      )}
      {creating && <UserModal user="new" inbounds={inbounds} onClose={() => setCreating(false)} />}
      {sharing && <ShareModal user={sharing} onClose={() => setSharing(null)} />}
    </section>
  );
}

function Tile({ label, value, sub, icon, tone = "neutral" }: { label: string; value: ReactNode; sub?: ReactNode; icon: ReactNode; tone?: "green" | "blue" | "amber" | "neutral" }) {
  const box = { green: "bg-emerald-600/15 text-emerald-300 ring-emerald-600/40", blue: "bg-sky-600/15 text-sky-300 ring-sky-600/40", amber: "bg-amber-600/15 text-amber-300 ring-amber-600/40", neutral: "bg-ink-750 text-ink-300 ring-ink-600" }[tone];
  const border = { green: "border-emerald-700/60 from-emerald-950/40", blue: "border-sky-700/60 from-sky-950/40", amber: "border-amber-700/50 from-amber-950/30", neutral: "border-ink-700/70 from-ink-850" }[tone];
  return (
    <div className={`rounded-xl border bg-gradient-to-br to-ink-850 p-4 shadow-card ${border}`}>
      <div className="flex items-start gap-3">
        <div className={`flex h-10 w-10 items-center justify-center rounded-lg ring-1 ${box}`}>{icon}</div>
        <div className="min-w-0">
          <div className="text-[11px] font-semibold uppercase tracking-wider text-ink-300">{label}</div>
          <div className="mt-1 truncate text-[26px] font-bold leading-tight tabular-nums text-ink-100">{value}</div>
          {sub && <div className="mt-1 text-xs text-ink-400">{sub}</div>}
        </div>
      </div>
    </div>
  );
}

export default function VpnOverviewPage() {
  const { data: o } = useQuery({ queryKey: ["vpn-overview"], queryFn: () => api<VpnOverview>("/vpn/overview"), refetchInterval: 10000 });
  const { data: nodes = [] } = useQuery({ queryKey: ["vpn-nodes"], queryFn: () => api<VpnNode[]>("/vpn/nodes"), refetchInterval: 10000 });
  const s = o?.users_by_status;
  const healthy = nodes.filter((n) => n.xray_installed && n.online && n.running && !n.error).length;
  const vpnNodes = nodes.filter((n) => n.xray_installed).length;
  return (
    <>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-ink-100">VPN</h1>
          <p className="mt-1 text-sm text-ink-400">Users, traffic and nodes at a glance</p>
        </div>
        <div className="flex gap-2">
          <Link to="/vpn/inbounds" className="btn-ghost"><Network size={15} />Inbounds</Link>
          <Link to="/vpn/users" className="btn-primary"><Users size={15} />Manage users</Link>
        </div>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile tone="green" icon={<Users size={20} />} label="Users" value={o?.users_total ?? "—"} sub={s ? `${s.active} active · ${s.expired} expired · ${s.limited} limited` : undefined} />
        <Tile tone="blue" icon={<Wifi size={20} />} label="Online now" value={o?.users_online ?? "—"} sub="traffic in the last 2 minutes" />
        <Tile icon={<ArrowDown size={20} />} label="Traffic today" value={fmtTraffic((o?.traffic.today_down ?? 0) + (o?.traffic.today_up ?? 0))} sub={`↓ ${fmtTraffic(o?.traffic.today_down ?? 0)} · ↑ ${fmtTraffic(o?.traffic.today_up ?? 0)}`} />
        <Tile icon={<ArrowUp size={20} />} label="Traffic this month" value={fmtTraffic((o?.traffic.month_down ?? 0) + (o?.traffic.month_up ?? 0))} sub={`↓ ${fmtTraffic(o?.traffic.month_down ?? 0)} · ↑ ${fmtTraffic(o?.traffic.month_up ?? 0)}`} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Tile tone={healthy === vpnNodes && vpnNodes ? "green" : vpnNodes ? "amber" : "neutral"} icon={<Network size={20} />} label="Nodes healthy" value={`${healthy} / ${vpnNodes}`} sub={`${o?.inbounds ?? 0} inbounds`} />
        <Tile icon={<UserCheck size={20} />} label="Active users" value={s?.active ?? "—"} sub={s ? `${s.disabled} disabled` : undefined} />
        <Tile tone={(o?.expiring_soon.length ?? 0) ? "amber" : "neutral"} icon={<CalendarClock size={20} />} label="Expiring in 3 days" value={o?.expiring_soon.length ?? 0} />
        <Tile icon={<ArrowDown size={20} />} label="Avg per active user (month)" value={fmtTraffic(s?.active ? ((o?.traffic.month_down ?? 0) + (o?.traffic.month_up ?? 0)) / s.active : 0)} />
      </div>
      <UsersPanel />
      <Card className="mt-6" title="Daily VPN traffic (30 days)" actions={o && <span className="text-xs text-ink-500">{o.timezone}</span>}>
        <DailyBars
          data={o?.daily ?? []}
          xKey="day"
          series={[{ key: "down", label: "Download" }, { key: "up", label: "Upload" }]}
          yFormat={(v) => fmtTraffic(v, v >= 1e9 ? 1 : 0)}
          xFormat={(d) => new Date(`${d}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "numeric" })}
          height={260}
        />
      </Card>
      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card title="Top users" bodyClass="" actions={<Link to="/vpn/users" className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:underline">All <ArrowRight size={12} /></Link>}>
          {!o?.top_users.length ? <Empty>No users yet.</Empty> : (
            <ul className="divide-y divide-ink-800">
              {o.top_users.map((u) => (
                <li key={u.id} className="flex items-center gap-4 px-4 py-2.5">
                  <span className="w-32 truncate text-sm text-ink-100">{u.username}</span>
                  <div className="flex-1"><UsageBar used={u.used} limit={u.data_limit} /></div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Expiring soon" bodyClass="">
          {!o?.expiring_soon.length ? <Empty>Nobody expires in the next 3 days.</Empty> : (
            <ul className="divide-y divide-ink-800">
              {o.expiring_soon.map((u) => {
                const e = expiryText(u.expire_at);
                return <li key={u.id} className="flex justify-between px-4 py-2.5 text-sm"><span className="text-ink-100">{u.username}</span><span className={e.tone}>{e.text}</span></li>;
              })}
            </ul>
          )}
        </Card>
        <Card title="Nodes" bodyClass="" actions={<Link to="/vpn/inbounds" className="inline-flex items-center gap-1 text-xs text-emerald-400 hover:underline">Details <ArrowRight size={12} /></Link>}>
          {!nodes.length ? <Empty>No servers enrolled.</Empty> : (
            <ul className="divide-y divide-ink-800">
              {nodes.map((n) => {
                const ok = n.xray_installed && n.online && n.running && !n.error;
                return (
                  <li key={n.agent_id} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-400" : n.xray_installed ? "bg-red-400" : "bg-ink-600"}`} />
                    <span className="flex-1 text-ink-100">{n.name}</span>
                    <span className="text-xs text-ink-400">{n.xray_installed ? `${n.inbounds} inbounds · ${n.online_users} online` : "no Xray"}</span>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
