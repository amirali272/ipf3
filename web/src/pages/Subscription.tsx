import { useQuery } from "@tanstack/react-query";
import { CalendarClock, Download, Gauge, Smartphone } from "lucide-react";
import { useState } from "react";
import { useParams } from "react-router-dom";
import type { SubInfo } from "../api/types";
import { Brand, Logo } from "../components/Layout";
import { CopyButton, expiryText, linkLabel, linkProtocol, QrCode, VpnStatusBadge } from "../components/vpn";
import { fmtTime, fmtTraffic } from "../lib/format";

async function fetchInfo(token: string): Promise<SubInfo> {
  const r = await fetch(`/api/sub/${encodeURIComponent(token)}/info`);
  if (!r.ok) throw new Error(r.status === 404 ? "This subscription link is not valid." : "Could not load the subscription.");
  return r.json();
}

const APPS = (url: string) => [
  { name: "v2rayNG", os: "Android", href: `v2rayng://install-config?url=${encodeURIComponent(url)}` },
  { name: "Hiddify", os: "Android · iOS · Desktop", href: `hiddify://import/${url}` },
  { name: "Streisand", os: "iOS", href: `streisand://import/${url}` },
  { name: "V2Box", os: "iOS", href: `v2box://install-sub?url=${encodeURIComponent(url)}&name=Unknown%20Monitor` },
  { name: "sing-box", os: "Android · iOS", href: `sing-box://import-remote-profile?url=${encodeURIComponent(url)}#Unknown%20Monitor` },
];

/** Public page shown when a subscription link is opened in a browser. */
export default function Subscription() {
  const { token = "" } = useParams();
  const { data, error, isLoading } = useQuery({ queryKey: ["sub", token], queryFn: () => fetchInfo(token), refetchInterval: 30000, retry: false });
  const [qr, setQr] = useState<string | null>(null);

  return (
    <div className="min-h-full bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.10),transparent_60%)] px-4 py-8">
      <div className="mx-auto max-w-3xl">
        <div className="mb-8 flex items-center gap-3"><Logo size={42} /><Brand /></div>
        {isLoading && <div className="text-ink-400">Loading…</div>}
        {error && <div className="card p-6 text-red-300">{(error as Error).message}</div>}
        {data && (() => {
          const exp = expiryText(data.expire_at);
          const pct = data.data_limit ? Math.min(100, (data.used / data.data_limit) * 100) : 0;
          const url = qr ?? data.sub_url;
          return (
            <div className="space-y-5">
              <div className="card p-6">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-xs uppercase tracking-wider text-ink-400">Account</div>
                    <div className="text-2xl font-bold text-ink-100">{data.username}</div>
                  </div>
                  <VpnStatusBadge status={data.status} online={data.online} />
                </div>
                <div className="mt-6 grid gap-4 sm:grid-cols-3">
                  <div className="rounded-xl bg-ink-900/60 p-4">
                    <div className="flex items-center gap-1.5 text-xs text-ink-400"><Gauge size={13} />Used</div>
                    <div className="mt-1 text-xl font-semibold text-ink-100">{fmtTraffic(data.used)}</div>
                    <div className="text-xs text-ink-500">↓ {fmtTraffic(data.used_down)} · ↑ {fmtTraffic(data.used_up)}</div>
                  </div>
                  <div className="rounded-xl bg-ink-900/60 p-4">
                    <div className="flex items-center gap-1.5 text-xs text-ink-400"><Download size={13} />Remaining</div>
                    <div className="mt-1 text-xl font-semibold text-ink-100">{data.data_limit ? fmtTraffic(Math.max(0, data.data_limit - data.used)) : "Unlimited"}</div>
                    <div className="text-xs text-ink-500">{data.data_limit ? `of ${fmtTraffic(data.data_limit)}` : ""}</div>
                  </div>
                  <div className="rounded-xl bg-ink-900/60 p-4">
                    <div className="flex items-center gap-1.5 text-xs text-ink-400"><CalendarClock size={13} />Expires</div>
                    <div className={`mt-1 text-xl font-semibold ${exp.tone}`}>{exp.text}</div>
                    <div className="text-xs text-ink-500">{data.expire_at ? fmtTime(data.expire_at) : ""}</div>
                  </div>
                </div>
                {data.data_limit > 0 && (
                  <div className="mt-4 h-2 rounded-full bg-ink-750">
                    <div className={`h-full rounded-full ${pct >= 90 ? "bg-red-400" : pct >= 70 ? "bg-amber-400" : "bg-emerald-500"}`} style={{ width: `${pct}%` }} />
                  </div>
                )}
              </div>

              <div className="card grid gap-6 p-6 sm:grid-cols-[auto_1fr]">
                <div className="flex flex-col items-center gap-2">
                  <QrCode text={url} size={210} />
                  <span className="max-w-[210px] text-center text-[11px] text-ink-500">{qr ? linkLabel(qr) : "Scan in your VPN app to add the subscription"}</span>
                </div>
                <div className="min-w-0 space-y-4">
                  <div>
                    <div className="label">Subscription link</div>
                    <div className="flex gap-2">
                      <input readOnly className="input mono flex-1 text-xs" value={data.sub_url} onFocus={(e) => e.target.select()} />
                      <CopyButton text={data.sub_url} />
                    </div>
                  </div>
                  <div>
                    <div className="label flex items-center gap-1.5"><Smartphone size={12} />Add to app</div>
                    <div className="flex flex-wrap gap-2">
                      {APPS(data.sub_url).map((a) => (
                        <a key={a.name} href={a.href} className="rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2 text-left hover:border-emerald-700">
                          <div className="text-sm font-medium text-ink-100">{a.name}</div>
                          <div className="text-[10px] text-ink-500">{a.os}</div>
                        </a>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

              <div className="card p-6">
                <div className="label">Configs</div>
                {data.links.length === 0 ? (
                  <p className="text-sm text-ink-400">{data.status === "active" ? "No configs available yet." : "This account is not active — contact your provider."}</p>
                ) : (
                  <ul className="space-y-2">
                    {data.links.map((l) => (
                      <li key={l} className="flex items-center gap-2 rounded-lg border border-ink-700 bg-ink-900/60 px-3 py-2">
                        <span className="badge bg-ink-750 text-[10px] text-emerald-300">{linkProtocol(l)}</span>
                        <span className="min-w-0 flex-1 truncate text-sm text-ink-200">{linkLabel(l)}</span>
                        <CopyButton text={l} />
                        <button className="btn-ghost px-2.5 py-1.5 text-xs" onClick={() => setQr(qr === l ? null : l)}>QR</button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <p className="text-center text-[11px] text-ink-600">Powered by Unknown Monitor</p>
            </div>
          );
        })()}
      </div>
    </div>
  );
}
