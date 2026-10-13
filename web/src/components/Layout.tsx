import {
  Activity,
  BarChart3,
  Bell,
  CalendarClock,
  ChevronDown,
  Gauge,
  HardDriveDownload,
  LogOut,
  Menu,
  Network,
  ScrollText,
  Search,
  Server,
  Settings,
  ShieldCheck,
  Users,
  Zap,
} from "lucide-react";

type NavItem = { to: string; label: string; icon: typeof Gauge; end?: boolean; badge?: number; tone?: "green" | "red" };
import { useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Agent, Overview, SystemStatus } from "../api/types";
import { useAuth } from "../lib/auth";

export function Logo({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#34d399" />
          <stop offset="1" stopColor="#047857" />
        </linearGradient>
      </defs>
      <path d="M24 3 42 13.5v21L24 45 6 34.5v-21Z" fill="url(#lg)" opacity="0.18" stroke="url(#lg)" strokeWidth="2" />
      <path d="M24 12 34 18v12l-10 6-10-6V18Z" fill="url(#lg)" />
      <path d="M17 26l4-4 3 3 6-7" fill="none" stroke="#0f1012" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Brand({ large = false }: { large?: boolean }) {
  return (
    <div className="leading-none">
      <div className={`${large ? "text-2xl" : "text-[19px]"} font-extrabold tracking-[0.06em] text-ink-100`}>
        Unknown
      </div>
      <div className={`${large ? "mt-1 text-xs" : "mt-0.5 text-[11px]"} font-medium uppercase tracking-[0.42em] text-emerald-400`}>
        monitor
      </div>
    </div>
  );
}

function MiniBar({ label, value }: { label: string; value: number | null | undefined }) {
  const v = value ?? 0;
  return (
    <div>
      <div className="mb-1 flex justify-between text-[11px] text-ink-400">
        <span>{label}</span>
        <span className="tabular-nums text-ink-200">{value == null ? "—" : `${v.toFixed(0)}%`}</span>
      </div>
      <div className="h-1.5 rounded-full bg-ink-750">
        <div className={`h-full rounded-full ${v >= 90 ? "bg-red-400" : v >= 75 ? "bg-amber-400" : "bg-emerald-500"}`} style={{ width: `${Math.min(100, v)}%` }} />
      </div>
    </div>
  );
}

function SystemCard() {
  const { data, isError } = useQuery({
    queryKey: ["system-status"],
    queryFn: () => api<SystemStatus>("/system/status"),
    refetchInterval: 15000,
  });
  const allOk = data && data.api && data.database && data.worker;
  return (
    <div className="rounded-xl border border-ink-700/70 bg-ink-850 p-3">
      <div className="flex items-center gap-2.5">
        <span className={`h-2.5 w-2.5 rounded-full ${isError ? "bg-red-400" : allOk ? "bg-emerald-400 shadow-[0_0_8px_#34d399]" : "bg-amber-400"}`} />
        <div className="min-w-0">
          <div className="text-xs text-ink-200">
            Control plane <span className={isError ? "text-red-300" : allOk ? "text-emerald-400" : "text-amber-300"}>{isError ? "Unreachable" : allOk ? "Online" : "Degraded"}</span>
          </div>
          <div className="truncate text-[11px] text-ink-500">
            {isError ? "API not responding" : !data ? "Checking…" : allOk ? "All services running" : !data.worker ? "Worker not running" : "Check services"}
          </div>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        <MiniBar label="CPU" value={data?.cpu_percent} />
        <MiniBar label="Memory" value={data?.mem_percent} />
        <MiniBar label="Disk" value={data?.disk_percent} />
      </div>
    </div>
  );
}

function UserMenu() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const h = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="flex items-center gap-3 rounded-lg py-1 pl-1 pr-2 hover:bg-ink-800">
        <span className="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-600/20 text-xs font-bold uppercase text-emerald-300 ring-1 ring-emerald-600/50">
          {user?.username.slice(0, 2)}
        </span>
        <span className="hidden text-left sm:block">
          <span className="block text-sm font-medium text-ink-100">{user?.username}</span>
          <span className="block text-[11px] capitalize text-ink-400">{user?.role === "admin" ? "Administrator" : user?.role}</span>
        </span>
        <ChevronDown size={15} className="text-ink-400" />
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-48 rounded-xl border border-ink-700 bg-ink-850 p-1 shadow-card">
          <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-200 hover:bg-ink-800" onClick={() => { setOpen(false); nav("/account"); }}>
            <Settings size={15} /> Account
          </button>
          <button className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-sm text-ink-200 hover:bg-ink-800" onClick={logout}>
            <LogOut size={15} /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}

function GlobalSearch() {
  const nav = useNavigate();
  const ref = useRef<HTMLInputElement>(null);
  const [q, setQ] = useState("");
  const [focus, setFocus] = useState(false);
  const { data: agents = [] } = useQuery({ queryKey: ["agents"], queryFn: () => api<Agent[]>("/agents"), staleTime: 15000 });
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        ref.current?.focus();
      }
    };
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, []);
  const needle = q.trim().toLowerCase();
  const hits = needle
    ? agents.filter((a) => [a.name, a.hostname, a.remote_addr ?? "", ...a.tags].some((f) => f.toLowerCase().includes(needle))).slice(0, 8)
    : [];
  return (
    <div className="relative w-full max-w-md">
      <Search size={16} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-500" />
      <input
        ref={ref}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => setFocus(true)}
        onBlur={() => setTimeout(() => setFocus(false), 150)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && hits[0]) { nav(`/servers/${hits[0].id}`); setQ(""); ref.current?.blur(); }
          if (e.key === "Escape") ref.current?.blur();
        }}
        placeholder="Search servers, IPs, tags…"
        className="w-full rounded-lg border border-ink-700 bg-ink-900/80 py-2 pl-9 pr-16 text-sm text-ink-100 placeholder:text-ink-500 focus:border-emerald-600 focus:outline-none"
      />
      <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-ink-700 bg-ink-800 px-1.5 py-0.5 text-[10px] text-ink-400 sm:block">Ctrl + K</kbd>
      {focus && needle && (
        <div className="absolute left-0 right-0 z-50 mt-2 overflow-hidden rounded-xl border border-ink-700 bg-ink-850 shadow-card">
          {hits.length === 0 ? (
            <div className="px-3 py-3 text-sm text-ink-500">No servers match “{q}”.</div>
          ) : (
            hits.map((a) => (
              <button key={a.id} onMouseDown={() => { nav(`/servers/${a.id}`); setQ(""); }} className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-ink-800">
                <span className={`h-2 w-2 rounded-full ${a.online ? "bg-emerald-400" : "bg-red-400"}`} />
                <span className="text-ink-100">{a.name}</span>
                <span className="ml-auto font-mono text-xs text-ink-500">{a.remote_addr}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

export default function Layout() {
  const { can } = useAuth();
  const [open, setOpen] = useState(false);
  const { data: overview } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/analytics/overview"),
    refetchInterval: 15000,
  });
  const { data: status } = useQuery({ queryKey: ["system-status"], queryFn: () => api<SystemStatus>("/system/status"), refetchInterval: 15000 });
  const firing = Object.values(overview?.alerts_firing ?? {}).reduce((a, b) => a + (b ?? 0), 0);

  const SECTIONS: { title: string; items: NavItem[] }[] = [
    {
      title: "VPN",
      items: [
        { to: "/", label: "Overview", icon: Gauge, end: true },
        { to: "/vpn/users", label: "Users", icon: Users },
        { to: "/vpn/inbounds", label: "Inbounds & nodes", icon: Network },
      ],
    },
    {
      title: "Monitoring",
      items: [
        { to: "/monitoring", label: "Dashboard", icon: Activity },
        { to: "/servers", label: "Servers", icon: Server, badge: overview?.agents_total || undefined, tone: "green" },
        { to: "/usage", label: "Traffic Usage", icon: HardDriveDownload },
        { to: "/tests", label: "Speed & Diagnostics", icon: Zap },
        { to: "/schedules", label: "Schedules", icon: CalendarClock },
        { to: "/analytics", label: "Analytics", icon: BarChart3 },
        { to: "/alerts", label: "Alerts", icon: Bell, badge: firing || undefined, tone: "red" },
      ],
    },
  ];
  const ADMIN_NAV: NavItem[] = [
    { to: "/users", label: "Panel admins", icon: ShieldCheck },
    { to: "/audit", label: "Audit log", icon: ScrollText },
    { to: "/account", label: "Settings", icon: Settings },
  ];

  const link = (item: NavItem) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      onClick={() => setOpen(false)}
      className={({ isActive }) =>
        `group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition ${
          isActive
            ? "bg-gradient-to-r from-emerald-600/30 to-emerald-600/5 text-emerald-200 ring-1 ring-emerald-700/50 before:absolute before:-left-3 before:top-1.5 before:h-[calc(100%-12px)] before:w-1 before:rounded-r before:bg-emerald-400"
            : "text-ink-300 hover:bg-ink-800 hover:text-ink-100"
        }`
      }
    >
      <item.icon size={18} />
      <span className="flex-1">{item.label}</span>
      {item.badge !== undefined && (
        <span className={`min-w-[22px] rounded-md px-1.5 py-0.5 text-center text-[11px] font-semibold ${item.tone === "red" ? "bg-red-500 text-white" : "bg-emerald-900/60 text-emerald-300"}`}>
          {item.badge}
        </span>
      )}
    </NavLink>
  );

  return (
    <div className="flex min-h-full">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-ink-800 bg-gradient-to-b from-ink-900 to-ink-950 transition-transform lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-3 border-b border-ink-800 px-5 py-4">
          <Logo />
          <Brand />
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-4">
          {SECTIONS.map((sec, i) => (
            <div key={sec.title}>
              <div className={`px-3 pb-1 ${i ? "pt-6" : "pt-1"} text-[11px] font-semibold uppercase tracking-wider text-ink-500`}>{sec.title}</div>
              <div className="space-y-1">{sec.items.map(link)}</div>
            </div>
          ))}
          {can("admin") && (
            <>
              <div className="px-3 pb-1 pt-6 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Administration</div>
              {ADMIN_NAV.map(link)}
            </>
          )}
        </nav>
        <div className="space-y-3 p-3">
          <SystemCard />
          <div className="flex items-center gap-2.5 border-t border-ink-800 px-2 pt-3">
            <Logo size={26} />
            <div className="text-xs">
              <div className="font-semibold text-ink-200">Unknown Monitor</div>
              <div className="text-ink-500">v{status?.version ?? "…"}</div>
            </div>
          </div>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-ink-800 bg-ink-950/85 px-4 py-3 backdrop-blur sm:px-6 lg:px-8">
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-ink-300 lg:hidden"><Menu size={20} /></button>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1 sm:gap-3">
            <NavLink to="/alerts" className="relative rounded-lg p-2 text-ink-300 hover:bg-ink-800 hover:text-ink-100" aria-label="Alerts">
              <Bell size={19} />
              {firing > 0 && <span className="absolute right-1 top-1 flex h-4 min-w-[16px] items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">{firing}</span>}
            </NavLink>
            {can("admin") && (
              <NavLink to="/account" className="rounded-lg p-2 text-ink-300 hover:bg-ink-800 hover:text-ink-100" aria-label="Settings">
                <Settings size={19} />
              </NavLink>
            )}
            <div className="mx-1 hidden h-8 w-px bg-ink-800 sm:block" />
            <UserMenu />
          </div>
        </header>
        <main className="mx-auto w-full max-w-[1600px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
