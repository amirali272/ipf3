import { AlertTriangle, CheckCircle2, Circle, Loader2, OctagonAlert, X, XCircle } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import type { JobStatus, Severity } from "../api/types";
import { RANGES } from "../lib/format";

export function Card({ title, actions, children, className = "", bodyClass = "p-4" }: {
  title?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClass?: string;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <div className="card-header">
          <h2 className="card-title">{title}</h2>
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </div>
      )}
      <div className={bodyClass}>{children}</div>
    </section>
  );
}

export function StatTile({ label, value, sub, accent = false, icon }: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  accent?: boolean;
  icon?: ReactNode;
}) {
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between text-xs font-medium uppercase tracking-wider text-ink-400">
        {label}
        {icon && <span className="text-ink-500">{icon}</span>}
      </div>
      <div className={`mt-2 truncate whitespace-nowrap text-2xl font-semibold tabular-nums ${accent ? "text-emerald-400" : "text-ink-100"}`}>{value}</div>
      {sub && <div className="mt-1 text-xs text-ink-400">{sub}</div>}
    </div>
  );
}

export function OnlineBadge({ online, disabled }: { online: boolean; disabled?: boolean }) {
  if (disabled) return <span className="badge bg-ink-750 text-ink-400"><Circle size={8} />Disabled</span>;
  return online ? (
    <span className="badge bg-emerald-900/40 text-emerald-300"><span className="h-2 w-2 rounded-full bg-emerald-400 shadow-[0_0_8px_#34d399]" />Online</span>
  ) : (
    <span className="badge bg-red-950/50 text-red-300"><span className="h-2 w-2 rounded-full bg-red-400" />Offline</span>
  );
}

const JOB_STYLE: Record<JobStatus, string> = {
  queued: "bg-ink-750 text-ink-300",
  running: "bg-sky-950/60 text-sky-300",
  completed: "bg-emerald-900/40 text-emerald-300",
  failed: "bg-red-950/50 text-red-300",
  cancelled: "bg-ink-750 text-ink-400",
  expired: "bg-amber-950/50 text-amber-300",
};

export function JobStatusBadge({ status }: { status: JobStatus }) {
  const icon =
    status === "running" ? <Loader2 size={12} className="animate-spin" /> :
    status === "completed" ? <CheckCircle2 size={12} /> :
    status === "failed" ? <XCircle size={12} /> : null;
  return <span className={`badge ${JOB_STYLE[status]}`}>{icon}{status}</span>;
}

export function SeverityBadge({ severity }: { severity: Severity }) {
  const map = {
    info: ["bg-sky-950/60 text-sky-300", <Circle size={10} key="i" />],
    warning: ["bg-amber-950/50 text-amber-300", <AlertTriangle size={12} key="w" />],
    critical: ["bg-red-950/60 text-red-300", <OctagonAlert size={12} key="c" />],
  } as const;
  const [cls, icon] = map[severity];
  return <span className={`badge ${cls}`}>{icon}{severity}</span>;
}

export function RangePicker({ value, onChange, options = RANGES }: {
  value: number;
  onChange: (s: number) => void;
  options?: { label: string; seconds: number }[];
}) {
  return (
    <div className="inline-flex rounded-lg border border-ink-700 bg-ink-900 p-0.5" role="group" aria-label="Time range">
      {options.map((r) => (
        <button
          key={r.seconds}
          onClick={() => onChange(r.seconds)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium transition ${
            value === r.seconds ? "bg-ink-700 text-emerald-300" : "text-ink-400 hover:text-ink-200"
          }`}
        >
          {r.label}
        </button>
      ))}
    </div>
  );
}

export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string }[]; value: T; onChange: (t: T) => void }) {
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-ink-700" role="tablist">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={value === t.id}
          onClick={() => onChange(t.id)}
          className={`-mb-px whitespace-nowrap border-b-2 px-3.5 py-2 text-sm font-medium transition ${
            value === t.id ? "border-emerald-500 text-emerald-300" : "border-transparent text-ink-400 hover:text-ink-200"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-sm text-ink-400">{children}</div>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-8 text-sm text-ink-400">
      <Loader2 size={16} className="animate-spin text-emerald-500" /> {label}
    </div>
  );
}

export function ErrorText({ error }: { error: unknown }) {
  if (!error) return null;
  const msg = error instanceof Error ? error.message : String(error);
  return <div className="rounded-lg border border-red-900/60 bg-red-950/30 px-3 py-2 text-sm text-red-300">{msg}</div>;
}

export function Modal({ open, onClose, title, children, wide = false }: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/60 p-4 pt-[8vh] backdrop-blur-sm" onMouseDown={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`card w-full ${wide ? "max-w-3xl" : "max-w-lg"}`}
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="card-header">
          <h2 className="card-title">{title}</h2>
          <button className="text-ink-400 hover:text-ink-100" onClick={onClose} aria-label="Close"><X size={18} /></button>
        </div>
        <div className="p-4">{children}</div>
      </div>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-xs text-ink-500">{hint}</span>}
    </label>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold text-ink-100">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-ink-400">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Meter({ value, label }: { value: number | null | undefined; label: string }) {
  const v = value ?? 0;
  const color = v >= 90 ? "bg-red-400" : v >= 75 ? "bg-amber-400" : "bg-emerald-500";
  return (
    <div title={`${label}: ${value == null ? "—" : v.toFixed(1) + "%"}`}>
      <div className="mb-1 flex justify-between text-[11px] text-ink-400">
        <span>{label}</span>
        <span className="tabular-nums text-ink-200">{value == null ? "—" : `${v.toFixed(0)}%`}</span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-ink-750">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${Math.min(100, v)}%` }} />
      </div>
    </div>
  );
}
