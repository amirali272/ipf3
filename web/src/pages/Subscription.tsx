import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Check, Copy, Download, Gauge, Globe2, Languages, QrCode as QrIcon, Server, Smartphone, Wifi } from "lucide-react";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import type { SubInfo } from "../api/types";
import { Brand, Logo } from "../components/Layout";
import { linkLabel, linkProtocol, QrCode } from "../components/vpn";
import { fmtTraffic } from "../lib/format";

async function fetchInfo(token: string): Promise<SubInfo> {
  const r = await fetch(`/api/sub/${encodeURIComponent(token)}/info`);
  if (!r.ok) throw new Error(r.status === 404 ? "invalid" : "error");
  return r.json();
}

type Lang = "fa" | "en";

const T = {
  en: {
    account: "Account", active: "Active", expired: "Expired", limited: "Data limit reached", disabled: "Disabled", online: "Connected",
    offline: "Not connected", used: "Used", remaining: "Remaining", unlimited: "Unlimited", of: "of", expires: "Expires", never: "Never",
    daysLeft: (d: number, h: number) => (d ? `${d} days ${h}h left` : `${h} hours left`), expiredAt: "Expired",
    sub: "Subscription link", subHint: "Add this link to your VPN app once — it updates itself.", copy: "Copy", copied: "Copied",
    addTo: "One-tap import", configs: "Configs", noConfigs: "No configs available yet.", inactive: "This account is not active — contact your provider.",
    connected: "Connected right now", noConn: "No device is connected at the moment.", lastOnline: "Last online", via: "via",
    apps: "Apps using this subscription", noApps: "Not added to any app yet.", updated: "updated", invalid: "This subscription link is not valid.",
    loadErr: "Could not load the subscription.", scan: "Scan with your VPN app", showQr: "QR", download: "Download", upload: "Upload",
    ago: (s: string) => `${s} ago`, now: "just now",
  },
  fa: {
    account: "حساب", active: "فعال", expired: "منقضی شده", limited: "حجم تمام شده", disabled: "غیرفعال", online: "متصل",
    offline: "متصل نیست", used: "مصرف شده", remaining: "باقی‌مانده", unlimited: "نامحدود", of: "از", expires: "انقضا", never: "بدون انقضا",
    daysLeft: (d: number, h: number) => (d ? `${d} روز و ${h} ساعت مانده` : `${h} ساعت مانده`), expiredAt: "منقضی شده",
    sub: "لینک اشتراک (ساب)", subHint: "این لینک را یک بار در برنامه اضافه کنید؛ خودش به‌روز می‌شود.", copy: "کپی", copied: "کپی شد",
    addTo: "افزودن سریع به برنامه", configs: "کانفیگ‌ها", noConfigs: "هنوز کانفیگی وجود ندارد.", inactive: "این حساب فعال نیست؛ با پشتیبانی تماس بگیرید.",
    connected: "دستگاه‌های متصل", noConn: "در حال حاضر هیچ دستگاهی وصل نیست.", lastOnline: "آخرین اتصال", via: "از طریق",
    apps: "برنامه‌هایی که از این ساب استفاده می‌کنند", noApps: "هنوز در هیچ برنامه‌ای اضافه نشده.", updated: "به‌روزرسانی", invalid: "این لینک اشتراک معتبر نیست.",
    loadErr: "بارگذاری اشتراک ممکن نشد.", scan: "با برنامهٔ VPN اسکن کنید", showQr: "QR", download: "دانلود", upload: "آپلود",
    ago: (s: string) => `${s} پیش`, now: "همین الان",
  },
};

function relative(iso: string | null, t: (typeof T)[Lang], lang: Lang): string {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 45) return t.now;
  const units: [number, string, string][] = [[86400, "d", "روز"], [3600, "h", "ساعت"], [60, "m", "دقیقه"]];
  for (const [n, en, fa] of units) {
    if (s >= n) return t.ago(lang === "fa" ? `${Math.floor(s / n)} ${fa}` : `${Math.floor(s / n)}${en}`);
  }
  return t.now;
}

const APPS = (url: string) => [
  { name: "v2rayNG", os: "Android", href: `v2rayng://install-config?url=${encodeURIComponent(url)}` },
  { name: "Hiddify", os: "Android · iOS · PC", href: `hiddify://import/${url}` },
  { name: "Happ", os: "Android · iOS", href: `happ://add/${url}` },
  { name: "Streisand", os: "iOS", href: `streisand://import/${url}` },
  { name: "V2Box", os: "iOS", href: `v2box://install-sub?url=${encodeURIComponent(url)}&name=Unknown%20Monitor` },
  { name: "sing-box", os: "Android · iOS", href: `sing-box://import-remote-profile?url=${encodeURIComponent(url)}#Unknown%20Monitor` },
];

function Copy2({ text, t }: { text: string; t: (typeof T)[Lang] }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={() => navigator.clipboard.writeText(text).then(() => { setDone(true); setTimeout(() => setDone(false), 1400); })}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-2 text-xs font-semibold transition ${done ? "bg-emerald-600 text-white" : "bg-ink-800 text-ink-200 hover:bg-ink-700"}`}
    >
      {done ? <Check size={14} /> : <Copy size={14} />}{done ? t.copied : t.copy}
    </button>
  );
}

function Ring({ pct, tone }: { pct: number; tone: string }) {
  const r = 52;
  const c = 2 * Math.PI * r;
  return (
    <svg width="132" height="132" viewBox="0 0 132 132" className="-rotate-90">
      <circle cx="66" cy="66" r={r} fill="none" stroke="currentColor" strokeWidth="12" className="text-ink-800" />
      <circle cx="66" cy="66" r={r} fill="none" stroke="currentColor" strokeWidth="12" strokeLinecap="round" strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} className={`${tone} transition-all duration-700`} />
    </svg>
  );
}

/** Public page shown when a subscription link is opened in a browser. */
export default function Subscription() {
  const { token = "" } = useParams();
  const [lang, setLang] = useState<Lang>(() => {
    try {
      const saved = localStorage.getItem("sub.lang");
      if (saved === "fa" || saved === "en") return saved;
    } catch { /* storage unavailable */ }
    return navigator.language?.toLowerCase().startsWith("fa") ? "fa" : "en";
  });
  useEffect(() => {
    try { localStorage.setItem("sub.lang", lang); } catch { /* storage unavailable */ }
  }, [lang]);
  const t = T[lang];
  const { data, error, isLoading } = useQuery({ queryKey: ["sub", token], queryFn: () => fetchInfo(token), refetchInterval: 15000, retry: false });
  const [qr, setQr] = useState<string | null>(null);
  const num = (n: number) => (lang === "fa" ? n.toLocaleString("fa-IR") : String(n));
  const traffic = (v: number) => (lang === "fa" ? fmtTraffic(v).replace(/[\d.]+/g, (m) => Number(m).toLocaleString("fa-IR", { maximumFractionDigits: 2 })) : fmtTraffic(v));

  return (
    <div dir={lang === "fa" ? "rtl" : "ltr"} className={`min-h-full bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.12),transparent_60%)] px-4 py-6 sm:py-10 ${lang === "fa" ? "font-[Vazirmatn,Tahoma,sans-serif]" : ""}`}>
      <div className="mx-auto max-w-3xl">
        <div className="mb-6 flex items-center justify-between gap-3" dir="ltr">
          <div className="flex items-center gap-3"><Logo size={40} /><Brand /></div>
          <button onClick={() => setLang(lang === "fa" ? "en" : "fa")} className="inline-flex items-center gap-1.5 rounded-lg border border-ink-700 bg-ink-900/70 px-3 py-1.5 text-xs font-medium text-ink-200 hover:border-emerald-700">
            <Languages size={14} />{lang === "fa" ? "English" : "فارسی"}
          </button>
        </div>
        {isLoading && <div className="text-ink-400">…</div>}
        {error && <div className="card p-6 text-red-300">{(error as Error).message === "invalid" ? t.invalid : t.loadErr}</div>}
        {data && (() => {
          const pct = data.data_limit ? Math.min(100, (data.used / data.data_limit) * 100) : 0;
          const ringTone = pct >= 90 ? "text-red-400" : pct >= 70 ? "text-amber-400" : "text-emerald-400";
          const ms = data.expire_at ? new Date(data.expire_at).getTime() - Date.now() : null;
          const days = ms !== null && ms > 0 ? Math.floor(ms / 86400000) : 0;
          const hours = ms !== null && ms > 0 ? Math.floor((ms % 86400000) / 3600000) : 0;
          const expText = ms === null ? t.never : ms <= 0 ? t.expiredAt : t.daysLeft(days, hours).replace(/\d+/g, (m) => num(+m));
          const expTone = ms !== null && (ms <= 0 || days < 3) ? "text-amber-300" : "text-ink-100";
          const statusTone = { active: "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40", expired: "bg-amber-500/15 text-amber-300 ring-amber-500/40", limited: "bg-red-500/15 text-red-300 ring-red-500/40", disabled: "bg-ink-700 text-ink-300 ring-ink-600" }[data.status];
          const ips = Array.from(new Set(data.connections.map((c) => c.ip)));
          return (
            <div className="space-y-5">
              {/* account */}
              <div className="card overflow-hidden">
                <div className="flex flex-wrap items-center justify-between gap-3 border-b border-ink-800 px-6 py-5">
                  <div>
                    <div className="text-xs text-ink-400">{t.account}</div>
                    <div className="text-2xl font-bold text-ink-100" dir="ltr">{data.username}</div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-3 py-1 text-xs font-semibold ring-1 ${statusTone}`}>{t[data.status]}</span>
                    <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ring-1 ${data.online ? "bg-emerald-500/15 text-emerald-300 ring-emerald-500/40" : "bg-ink-800 text-ink-400 ring-ink-700"}`}>
                      <span className={`h-2 w-2 rounded-full ${data.online ? "animate-pulse bg-emerald-400" : "bg-ink-500"}`} />{data.online ? t.online : t.offline}
                    </span>
                  </div>
                </div>
                <div className="grid items-center gap-6 p-6 sm:grid-cols-[auto_1fr]">
                  <div className="relative mx-auto h-[132px] w-[132px]">
                    <Ring pct={data.data_limit ? pct : 100} tone={data.data_limit ? ringTone : "text-emerald-500/40"} />
                    <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                      <div className="text-2xl font-bold text-ink-100">{data.data_limit ? `${num(Math.round(pct))}%` : "∞"}</div>
                      <div className="text-[10px] text-ink-500">{t.used}</div>
                    </div>
                  </div>
                  <div className="grid gap-3 sm:grid-cols-3">
                    <div className="rounded-xl bg-ink-900/60 p-4">
                      <div className="flex items-center gap-1.5 text-xs text-ink-400"><Gauge size={13} />{t.used}</div>
                      <div className="mt-1 text-lg font-semibold text-ink-100" dir="ltr">{traffic(data.used)}</div>
                      <div className="mt-0.5 text-[11px] text-ink-500" dir="ltr">↓ {traffic(data.used_down)} · ↑ {traffic(data.used_up)}</div>
                    </div>
                    <div className="rounded-xl bg-ink-900/60 p-4">
                      <div className="flex items-center gap-1.5 text-xs text-ink-400"><Download size={13} />{t.remaining}</div>
                      <div className="mt-1 text-lg font-semibold text-ink-100" dir="ltr">{data.data_limit ? traffic(Math.max(0, data.data_limit - data.used)) : t.unlimited}</div>
                      {data.data_limit > 0 && <div className="mt-0.5 text-[11px] text-ink-500">{t.of} <span dir="ltr">{traffic(data.data_limit)}</span></div>}
                    </div>
                    <div className="rounded-xl bg-ink-900/60 p-4">
                      <div className="flex items-center gap-1.5 text-xs text-ink-400"><CalendarClock size={13} />{t.expires}</div>
                      <div className={`mt-1 text-lg font-semibold ${expTone}`}>{expText}</div>
                      {data.expire_at && <div className="mt-0.5 text-[11px] text-ink-500">{new Date(data.expire_at).toLocaleDateString(lang === "fa" ? "fa-IR" : "en-GB")}</div>}
                    </div>
                  </div>
                </div>
              </div>

              {/* connected devices + apps */}
              <div className="grid gap-5 md:grid-cols-2">
                <div className="card p-5">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink-100">
                    <Wifi size={16} className="text-emerald-400" />{t.connected}
                    {ips.length > 0 && <span className="rounded-md bg-emerald-900/60 px-1.5 py-0.5 text-[11px] text-emerald-300">{num(ips.length)} IP</span>}
                  </div>
                  {data.connections.length === 0 ? (
                    <p className="text-sm text-ink-500">{t.noConn}{data.last_online_at && <span className="block pt-1 text-xs">{t.lastOnline}: {relative(data.last_online_at, t, lang)}</span>}</p>
                  ) : (
                    <ul className="space-y-2">
                      {data.connections.map((c) => (
                        <li key={`${c.node}-${c.ip}`} className="flex items-center gap-3 rounded-xl border border-ink-700/70 bg-ink-900/60 px-3 py-2.5">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-emerald-600/15"><Globe2 size={15} className="text-emerald-300" /></span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate font-mono text-sm text-ink-100" dir="ltr">{c.ip}</div>
                            <div className="flex items-center gap-1 text-[11px] text-ink-500"><Server size={10} />{t.via} {c.node} · {relative(c.last_seen, t, lang)}</div>
                          </div>
                          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
                <div className="card p-5">
                  <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-ink-100"><Smartphone size={16} className="text-sky-400" />{t.apps}</div>
                  {data.apps.length === 0 ? <p className="text-sm text-ink-500">{t.noApps}</p> : (
                    <ul className="space-y-2">
                      {data.apps.slice(0, 6).map((a) => (
                        <li key={`${a.app}-${a.version}-${a.last_at}`} className="flex items-center gap-3 rounded-xl border border-ink-700/70 bg-ink-900/60 px-3 py-2.5">
                          <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-sky-600/15 text-xs font-bold text-sky-300">{a.app.slice(0, 2)}</span>
                          <div className="min-w-0 flex-1">
                            <div className="truncate text-sm font-medium text-ink-100" dir="ltr">{a.app}{a.version && <span className="text-ink-400"> {a.version}</span>}</div>
                            <div className="text-[11px] text-ink-500">{t.updated} {relative(a.last_at, t, lang)}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              </div>

              {/* subscription */}
              <div className="card grid gap-6 p-6 sm:grid-cols-[auto_1fr]">
                <div className="flex flex-col items-center gap-2">
                  <QrCode text={qr ?? data.sub_url} size={200} />
                  <span className="max-w-[210px] text-center text-[11px] text-ink-500">{qr ? linkLabel(qr) : t.scan}</span>
                </div>
                <div className="min-w-0 space-y-5">
                  <div>
                    <div className="mb-1 text-sm font-semibold text-ink-100">{t.sub}</div>
                    <p className="mb-2 text-xs text-ink-500">{t.subHint}</p>
                    <div className="flex gap-2" dir="ltr">
                      <input readOnly className="input mono min-w-0 flex-1 text-xs" value={data.sub_url} onFocus={(e) => e.target.select()} />
                      <Copy2 text={data.sub_url} t={t} />
                    </div>
                  </div>
                  <div>
                    <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink-400"><Smartphone size={12} />{t.addTo}</div>
                    <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" dir="ltr">
                      {APPS(data.sub_url).map((a) => (
                        <a key={a.name} href={a.href} className="rounded-xl border border-ink-700 bg-ink-900/60 px-3 py-2 transition hover:border-emerald-600">
                          <div className="text-sm font-medium text-ink-100">{a.name}</div>
                          <div className="text-[10px] text-ink-500">{a.os}</div>
                        </a>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              {/* configs */}
              <div className="card p-6">
                <div className="mb-3 text-sm font-semibold text-ink-100">{t.configs}</div>
                {data.links.length === 0 ? (
                  <p className="text-sm text-ink-400">{data.status === "active" ? t.noConfigs : t.inactive}</p>
                ) : (
                  <ul className="space-y-2" dir="ltr">
                    {data.links.map((l) => (
                      <li key={l} className={`flex items-center gap-2 rounded-xl border bg-ink-900/60 px-3 py-2 ${qr === l ? "border-emerald-600" : "border-ink-700"}`}>
                        <span className="rounded-md bg-emerald-900/50 px-1.5 py-0.5 text-[10px] font-bold text-emerald-300">{linkProtocol(l)}</span>
                        <span className="min-w-0 flex-1 truncate text-sm text-ink-200">{linkLabel(l)}</span>
                        <Copy2 text={l} t={t} />
                        <button className={`inline-flex items-center gap-1 rounded-lg px-2.5 py-2 text-xs font-semibold ${qr === l ? "bg-emerald-600 text-white" : "bg-ink-800 text-ink-200 hover:bg-ink-700"}`} onClick={() => setQr(qr === l ? null : l)}>
                          <QrIcon size={13} />{t.showQr}
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="text-center text-[11px] text-ink-600" dir="ltr">Powered by Unknown Monitor</p>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
