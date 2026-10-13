import { Activity, Lock } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ErrorText } from "../components/ui";
import { useAuth } from "../lib/auth";

export default function Login() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-full items-center justify-center bg-[radial-gradient(ellipse_at_top,rgba(16,185,129,0.10),transparent_60%)] px-4">
      <form onSubmit={submit} className="card w-full max-w-sm p-7">
        <div className="mb-6 flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-600/15 ring-1 ring-emerald-600/40">
            <Activity className="text-emerald-400" size={22} />
          </div>
          <div>
            <h1 className="text-lg font-semibold">IPF3 Network Monitor</h1>
            <p className="text-xs text-ink-400">Sign in to continue</p>
          </div>
        </div>
        <div className="space-y-4">
          <div>
            <label className="label" htmlFor="u">Username</label>
            <input id="u" className="input" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} required />
          </div>
          <div>
            <label className="label" htmlFor="p">Password</label>
            <input id="p" type="password" className="input" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>
          <ErrorText error={error} />
          <button className="btn-primary w-full" disabled={busy}>
            <Lock size={15} /> {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>
      </form>
    </div>
  );
}
