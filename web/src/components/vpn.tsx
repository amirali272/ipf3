import QRCode from "qrcode";
import { Check, Copy } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import type { VpnStatus } from "../api/types";
import { fmtTraffic } from "../lib/format";

export function QrCode({ text, size = 220 }: { text: string; size?: number }) {
  const [url, setUrl] = useState<string>("");
  useEffect(() => {
    QRCode.toDataURL(text, { width: size, margin: 1, errorCorrectionLevel: "M", color: { dark: "#0f1012", light: "#ffffff" } })
      .then(setUrl)
      .catch(() => setUrl(""));
  }, [text, size]);
  return url ? <img src={url} width={size} height={size} alt="QR code" className="rounded-lg bg-white p-1" /> : <div style={{ width: size, height: size }} className="rounded-lg bg-ink-800" />;
}

export function CopyButton({ text, label = "Copy", className = "" }: { text: string; label?: string; className?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className={`btn-ghost px-2.5 py-1.5 text-xs ${className}`}
      onClick={() =>
        navigator.clipboard.writeText(text).then(() => {
          setDone(true);
          setTimeout(() => setDone(false), 1400);
        })
      }
    >
      {done ? <Check size={13} className="text-emerald-400" /> : <Copy size={13} />}
      {done ? "Copied" : label}
    </button>
  );
}

const STATUS: Record<VpnStatus, string> = {
  active: "bg-emerald-900/40 text-emerald-300",
  expired: "bg-amber-950/50 text-amber-300",
  limited: "bg-red-950/50 text-red-300",
  disabled: "bg-ink-750 text-ink-400",
};

export function VpnStatusBadge({ status, online }: { status: VpnStatus; online?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`badge ${STATUS[status]}`}>{status}</span>
      {online && (
        <span className="badge bg-emerald-600/20 text-emerald-300">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
          online
        </span>
      )}
    </span>
  );
}

export function UsageBar({ used, limit }: { used: number; limit: number }) {
  const pct = limit ? Math.min(100, (used / limit) * 100) : 0;
  return (
    <div className="min-w-[140px]">
      <div className="mb-1 flex justify-between text-[11px] tabular-nums">
        <span className="text-ink-200">{fmtTraffic(used)}</span>
        <span className="text-ink-500">{limit ? fmtTraffic(limit) : "∞"}</span>
      </div>
      <div className="h-1.5 rounded-full bg-ink-750">
        <div
          className={`h-full rounded-full ${pct >= 90 ? "bg-red-400" : pct >= 70 ? "bg-amber-400" : "bg-emerald-500"}`}
          style={{ width: `${limit ? pct : used > 0 ? 100 : 0}%`, opacity: limit ? 1 : 0.35 }}
        />
      </div>
    </div>
  );
}

export function expiryText(expire_at: string | null): { text: string; tone: string } {
  if (!expire_at) return { text: "Never", tone: "text-ink-400" };
  const ms = new Date(expire_at).getTime() - Date.now();
  if (ms <= 0) return { text: "Expired", tone: "text-amber-300" };
  const d = Math.floor(ms / 86400000);
  const h = Math.floor((ms % 86400000) / 3600000);
  return { text: d ? `${d}d ${h}h left` : `${h}h left`, tone: d < 3 ? "text-amber-300" : "text-ink-200" };
}

export const GB = 1e9;

export function linkLabel(link: string): string {
  const hash = link.indexOf("#");
  if (link.startsWith("vmess://")) {
    try {
      return JSON.parse(atob(link.slice(8))).ps as string;
    } catch {
      return "vmess";
    }
  }
  return hash >= 0 ? decodeURIComponent(link.slice(hash + 1)) : link.split(":")[0];
}

export function linkProtocol(link: string): string {
  return link.split("://")[0].toUpperCase();
}

export function Chip({ children, tone = "neutral", icon }: { children: ReactNode; tone?: "neutral" | "green" | "amber"; icon?: ReactNode }) {
  const cls = { neutral: "border-ink-600 bg-ink-800 text-ink-200", green: "border-emerald-700/60 bg-emerald-950/40 text-emerald-300", amber: "border-amber-700/50 bg-amber-950/30 text-amber-300" }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide ${cls}`}>{icon}{children}</span>;
}

export function Switch({ on, onChange, disabled }: { on: boolean; onChange: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onChange}
      aria-pressed={on}
      className={`relative h-6 w-11 shrink-0 rounded-full transition disabled:opacity-40 ${on ? "bg-emerald-600 shadow-[0_0_12px_rgba(16,185,129,0.45)]" : "bg-ink-700"}`}
    >
      <span className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all ${on ? "left-[22px]" : "left-0.5"}`} />
    </button>
  );
}
