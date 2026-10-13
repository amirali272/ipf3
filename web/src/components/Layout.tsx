import {
  Activity,
  BarChart3,
  Bell,
  CalendarClock,
  Gauge,
  LogOut,
  Menu,
  ScrollText,
  Server,
  ShieldCheck,
  UserCog,
  Users,
  Zap,
} from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Overview } from "../api/types";
import { useAuth } from "../lib/auth";

const NAV = [
  { to: "/", label: "Dashboard", icon: Gauge, end: true },
  { to: "/servers", label: "Servers", icon: Server },
  { to: "/tests", label: "Speed & Diagnostics", icon: Zap },
  { to: "/schedules", label: "Schedules", icon: CalendarClock },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/alerts", label: "Alerts", icon: Bell },
];
const ADMIN_NAV = [
  { to: "/users", label: "Users", icon: Users },
  { to: "/audit", label: "Audit log", icon: ScrollText },
];

export default function Layout() {
  const { user, logout, can } = useAuth();
  const [open, setOpen] = useState(false);
  const { data: overview } = useQuery({
    queryKey: ["overview"],
    queryFn: () => api<Overview>("/analytics/overview"),
    refetchInterval: 15000,
  });
  const firing = Object.values(overview?.alerts_firing ?? {}).reduce((a, b) => a + (b ?? 0), 0);

  const link = (item: (typeof NAV)[number]) => (
    <NavLink
      key={item.to}
      to={item.to}
      end={item.end}
      onClick={() => setOpen(false)}
      className={({ isActive }) =>
        `group flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition ${
          isActive ? "bg-emerald-900/30 text-emerald-300 ring-1 ring-emerald-800/50" : "text-ink-300 hover:bg-ink-800 hover:text-ink-100"
        }`
      }
    >
      <item.icon size={17} />
      <span className="flex-1">{item.label}</span>
      {item.to === "/alerts" && firing > 0 && (
        <span className="rounded-full bg-red-500/90 px-1.5 text-[11px] font-semibold text-white">{firing}</span>
      )}
    </NavLink>
  );

  return (
    <div className="flex min-h-full">
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-ink-800 bg-ink-900 transition-transform lg:translate-x-0 ${
          open ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-600/15 ring-1 ring-emerald-600/40">
            <Activity size={19} className="text-emerald-400" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-wide">IPF3</div>
            <div className="text-[11px] text-ink-400">Network Monitor</div>
          </div>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3">
          {NAV.map(link)}
          {can("admin") && (
            <>
              <div className="px-3 pb-1 pt-5 text-[11px] font-semibold uppercase tracking-wider text-ink-500">Administration</div>
              {ADMIN_NAV.map(link)}
            </>
          )}
        </nav>
        <div className="border-t border-ink-800 p-3">
          <NavLink to="/account" className="flex items-center gap-3 rounded-lg px-3 py-2 hover:bg-ink-800">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ink-750 text-xs font-semibold uppercase text-emerald-300">
              {user?.username.slice(0, 2)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="truncate text-sm text-ink-100">{user?.username}</div>
              <div className="flex items-center gap-1 text-[11px] text-ink-400">
                {user?.role === "admin" ? <ShieldCheck size={11} /> : <UserCog size={11} />}
                {user?.role}
              </div>
            </div>
          </NavLink>
          <button onClick={logout} className="mt-1 flex w-full items-center gap-3 rounded-lg px-3 py-2 text-sm text-ink-400 hover:bg-ink-800 hover:text-ink-100">
            <LogOut size={16} /> Sign out
          </button>
        </div>
      </aside>
      {open && <div className="fixed inset-0 z-30 bg-black/50 lg:hidden" onClick={() => setOpen(false)} />}
      <div className="flex min-w-0 flex-1 flex-col lg:pl-64">
        <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-ink-800 bg-ink-950/80 px-4 py-3 backdrop-blur lg:hidden">
          <button onClick={() => setOpen(true)} aria-label="Open menu" className="text-ink-300"><Menu size={20} /></button>
          <span className="text-sm font-semibold">IPF3</span>
        </header>
        <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
