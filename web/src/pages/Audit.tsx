import { useInfiniteQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api, qs } from "../api/client";
import type { AuditEntry } from "../api/types";
import { Card, Empty, PageHeader } from "../components/ui";
import { fmtTime } from "../lib/format";

export default function Audit() {
  const [action, setAction] = useState("");
  const q = useInfiniteQuery({
    queryKey: ["audit", action],
    initialPageParam: 0,
    queryFn: ({ pageParam }) => api<AuditEntry[]>(`/audit${qs({ action, before_id: pageParam || undefined, limit: 100 })}`),
    getNextPageParam: (last) => (last.length === 100 ? last[last.length - 1].id : undefined),
  });
  const rows = q.data?.pages.flat() ?? [];
  return (
    <>
      <PageHeader title="Audit log" subtitle="Security-relevant actions by users and agents" />
      <Card bodyClass="overflow-x-auto" title="Entries" actions={
        <select className="input w-48" value={action} onChange={(e) => setAction(e.target.value)}>
          <option value="">All actions</option>
          {["auth", "user", "agent", "enrollment_token", "job", "schedule", "alert"].map((a) => <option key={a} value={a}>{a}.*</option>)}
        </select>}>
        {!rows.length ? <Empty>No entries.</Empty> : (
          <table className="table">
            <thead><tr><th>Time</th><th>User</th><th>Action</th><th>Target</th><th>Details</th><th>IP</th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="whitespace-nowrap">{fmtTime(r.ts)}</td>
                  <td>{r.username || <span className="text-ink-500">system</span>}</td>
                  <td className="mono text-emerald-300">{r.action}</td>
                  <td className="mono">{r.target}</td>
                  <td className="mono max-w-md truncate text-xs text-ink-400" title={JSON.stringify(r.details)}>{Object.keys(r.details).length ? JSON.stringify(r.details) : ""}</td>
                  <td className="mono">{r.ip}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {q.hasNextPage && <div className="p-3 text-center"><button className="btn-ghost" onClick={() => q.fetchNextPage()}>Load more</button></div>}
      </Card>
    </>
  );
}
