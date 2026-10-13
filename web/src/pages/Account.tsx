import { useMutation } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { Card, ErrorText, Field, PageHeader } from "../components/ui";
import { fmtTime } from "../lib/format";
import { useAuth } from "../lib/auth";

export default function Account() {
  const { user } = useAuth();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [pw2, setPw2] = useState("");
  const [done, setDone] = useState(false);
  const change = useMutation({
    mutationFn: async () => {
      if (pw !== pw2) throw new Error("New passwords do not match");
      await api("/auth/change-password", { method: "POST", json: { current_password: cur, new_password: pw } });
    },
    onSuccess: () => { setDone(true); setCur(""); setPw(""); setPw2(""); },
  });
  return (
    <>
      <PageHeader title="Account" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Profile">
          <dl className="space-y-3 text-sm">
            {[["Username", user?.username], ["Role", user?.role], ["Email", user?.email ?? "—"], ["Member since", fmtTime(user?.created_at)]].map(([k, v]) => (
              <div key={k} className="flex"><dt className="w-36 text-ink-400">{k}</dt><dd className="text-ink-100">{v}</dd></div>
            ))}
          </dl>
        </Card>
        <Card title="Change password">
          <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setDone(false); change.mutate(); }}>
            <Field label="Current password"><input className="input" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} required /></Field>
            <Field label="New password" hint="≥ 12 characters with 3 of: lower, upper, digit, symbol"><input className="input" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} required /></Field>
            <Field label="Repeat new password"><input className="input" type="password" autoComplete="new-password" value={pw2} onChange={(e) => setPw2(e.target.value)} required /></Field>
            <ErrorText error={change.error} />
            {done && <div className="text-sm text-emerald-400">Password changed. Other sessions have been signed out.</div>}
            <button className="btn-primary" disabled={change.isPending}>Update password</button>
          </form>
        </Card>
      </div>
    </>
  );
}
