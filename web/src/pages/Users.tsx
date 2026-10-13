import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/client";
import type { Role, User } from "../api/types";
import { Card, ErrorText, Field, Modal, PageHeader } from "../components/ui";
import { fmtRelative } from "../lib/format";
import { useAuth } from "../lib/auth";

const ROLE_HELP: Record<Role, string> = {
  viewer: "Read-only access to dashboards, telemetry and results",
  operator: "Viewer + run tests, manage schedules, acknowledge alerts",
  admin: "Operator + users, servers, enrollment, alert rules, audit log",
};

export default function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ username: "", email: "", password: "", role: "viewer" as Role });
  const [reset, setReset] = useState<User | null>(null);
  const [newPw, setNewPw] = useState("");
  const { data = [] } = useQuery({ queryKey: ["users"], queryFn: () => api<User[]>("/users") });
  const inv = () => qc.invalidateQueries({ queryKey: ["users"] });
  const create = useMutation({
    mutationFn: () => api("/users", { method: "POST", json: { ...form, email: form.email || null } }),
    onSuccess: () => { inv(); setOpen(false); setForm({ username: "", email: "", password: "", role: "viewer" }); },
  });
  const patch = useMutation({ mutationFn: ({ id, body }: { id: number; body: object }) => api(`/users/${id}`, { method: "PATCH", json: body }), onSuccess: () => { inv(); setReset(null); setNewPw(""); } });
  const del = useMutation({ mutationFn: (id: number) => api(`/users/${id}`, { method: "DELETE" }), onSuccess: inv });

  return (
    <>
      <PageHeader title="Users" subtitle="Role-based access control" actions={<button className="btn-primary" onClick={() => setOpen(true)}><Plus size={15} />Add user</button>} />
      <ErrorText error={patch.error || del.error} />
      <Card bodyClass="overflow-x-auto" className="mt-2">
        <table className="table">
          <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last login</th><th /></tr></thead>
          <tbody>
            {data.map((u) => {
              const locked = u.locked_until && new Date(u.locked_until).getTime() > Date.now();
              return (
                <tr key={u.id}>
                  <td><div className="font-medium text-ink-100">{u.username}{u.id === me?.id && <span className="ml-2 text-xs text-ink-500">(you)</span>}</div><div className="text-xs text-ink-500">{u.email}</div></td>
                  <td>
                    <select className="input w-32 py-1" value={u.role} onChange={(e) => patch.mutate({ id: u.id, body: { role: e.target.value } })}>
                      {(["viewer", "operator", "admin"] as Role[]).map((r) => <option key={r}>{r}</option>)}
                    </select>
                  </td>
                  <td>
                    {locked ? <button className="badge bg-amber-950/50 text-amber-300" onClick={() => patch.mutate({ id: u.id, body: { unlock: true } })}>locked · unlock</button> :
                      <button className={`badge ${u.is_active ? "bg-emerald-900/40 text-emerald-300" : "bg-ink-750 text-ink-400"}`} onClick={() => patch.mutate({ id: u.id, body: { is_active: !u.is_active } })} title="Toggle">{u.is_active ? "active" : "disabled"}</button>}
                  </td>
                  <td>{fmtRelative(u.last_login_at)}</td>
                  <td className="whitespace-nowrap text-right">
                    <button className="btn-ghost mr-2 px-2 py-1 text-xs" onClick={() => setReset(u)}>Reset password</button>
                    {u.id !== me?.id && <button className="text-ink-400 hover:text-red-300" onClick={() => confirm(`Delete ${u.username}?`) && del.mutate(u.id)} aria-label="Delete"><Trash2 size={15} /></button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Card>
      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        {(Object.keys(ROLE_HELP) as Role[]).map((r) => <div key={r} className="card p-4 text-sm"><div className="font-medium capitalize text-emerald-300">{r}</div><div className="mt-1 text-ink-400">{ROLE_HELP[r]}</div></div>)}
      </div>
      <Modal open={open} onClose={() => setOpen(false)} title="Add user">
        <div className="space-y-4">
          <Field label="Username"><input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field label="Email (optional)"><input className="input" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
          <Field label="Initial password" hint="≥ 12 characters with 3 of: lower, upper, digit, symbol"><input className="input" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
          <Field label="Role" hint={ROLE_HELP[form.role]}>
            <select className="input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {(["viewer", "operator", "admin"] as Role[]).map((r) => <option key={r}>{r}</option>)}
            </select>
          </Field>
          <ErrorText error={create.error} />
          <div className="flex justify-end"><button className="btn-primary" onClick={() => create.mutate()} disabled={create.isPending}>Create user</button></div>
        </div>
      </Modal>
      <Modal open={!!reset} onClose={() => setReset(null)} title={`Reset password for ${reset?.username}`}>
        <div className="space-y-4">
          <Field label="New password"><input className="input" type="password" autoComplete="new-password" value={newPw} onChange={(e) => setNewPw(e.target.value)} /></Field>
          <p className="text-xs text-ink-400">All existing sessions of this user are signed out.</p>
          <ErrorText error={patch.error} />
          <div className="flex justify-end"><button className="btn-primary" onClick={() => reset && patch.mutate({ id: reset.id, body: { password: newPw } })}>Reset</button></div>
        </div>
      </Modal>
    </>
  );
}
