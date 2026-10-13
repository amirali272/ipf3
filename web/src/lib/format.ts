export function fmtBps(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  const units: [string, number][] = [
    ["Tbit/s", 1e12],
    ["Gbit/s", 1e9],
    ["Mbit/s", 1e6],
    ["kbit/s", 1e3],
  ];
  for (const [u, d] of units) if (Math.abs(v) >= d) return `${(v / d).toFixed(digits)} ${u}`;
  return `${v.toFixed(0)} bit/s`;
}

export function fmtBpsShort(v: number): string {
  const units: [string, number][] = [
    ["T", 1e12],
    ["G", 1e9],
    ["M", 1e6],
    ["k", 1e3],
  ];
  for (const [u, d] of units) if (Math.abs(v) >= d) return `${+(v / d).toFixed(1)}${u}`;
  return `${Math.round(v)}`;
}

export function fmtBytes(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let i = 0;
  let n = v;
  while (Math.abs(n) >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function fmtNum(v: number | null | undefined, digits = 1, suffix = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${v.toFixed(digits)}${suffix}`;
}

export function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return v < 1 ? `${(v * 1000).toFixed(0)} µs` : `${v.toFixed(v < 10 ? 2 : 1)} ms`;
}

export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m`;
  return `${Math.floor(seconds)}s`;
}

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 5) return "just now";
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function axisTime(rangeSeconds: number) {
  return (t: string | number) => {
    const d = new Date(t);
    if (rangeSeconds <= 86400)
      return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
}

export const RANGES: { label: string; seconds: number }[] = [
  { label: "15m", seconds: 900 },
  { label: "1h", seconds: 3600 },
  { label: "6h", seconds: 6 * 3600 },
  { label: "24h", seconds: 86400 },
  { label: "7d", seconds: 7 * 86400 },
  { label: "30d", seconds: 30 * 86400 },
];
