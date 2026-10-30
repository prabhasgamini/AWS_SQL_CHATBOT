"use client";

import { FormEvent, useState } from "react";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: username.trim(), password }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        setError(typeof body.detail === "string" ? body.detail : "Sign-in failed.");
        setBusy(false);
        return;
      }
      sessionStorage.removeItem("welcomed"); // a fresh login gets a fresh welcome message
      window.location.href = "/";
    } catch {
      setError("Couldn't reach the server.");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <form onSubmit={submit} className="w-full max-w-sm rounded-2xl border border-line bg-panel p-8 shadow-sm">
        <div className="mb-1 text-3xl text-accent">✻</div>
        <h1 className="font-serif text-2xl">Sign in</h1>
        <p className="mb-6 mt-1 text-sm text-muted">SQL Knowledge Base</p>

        <label className="mb-1 block text-sm" htmlFor="username">Username</label>
        <input
          id="username"
          autoFocus
          autoComplete="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          className="mb-4 w-full rounded-lg border border-line bg-transparent px-3 py-2 outline-none focus:border-accent"
        />

        <label className="mb-1 block text-sm" htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="mb-4 w-full rounded-lg border border-line bg-transparent px-3 py-2 outline-none focus:border-accent"
        />

        {error && (
          <p role="alert" className="mb-4 rounded-lg border border-red-400/40 bg-red-500/10 px-3 py-2 text-sm text-red-700 dark:text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={busy || !username || !password}
          className="w-full rounded-lg bg-accent px-3 py-2 font-medium text-white disabled:opacity-50"
        >
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
