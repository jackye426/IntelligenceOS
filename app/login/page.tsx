"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";

export default function LoginPage() {
  const router = useRouter();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setLoading(true);
    setError("");

    const password = (e.currentTarget.elements.namedItem("password") as HTMLInputElement).value;

    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });

    if (res.ok) {
      router.replace("/accounts");
    } else {
      setError("Incorrect password.");
      setLoading(false);
    }
  }

  return (
    <div style={{
      display: "grid",
      placeItems: "center",
      minHeight: "100vh",
      background: "var(--canvas)",
    }}>
      <div className="panel" style={{ width: "min(380px, calc(100vw - 32px))", padding: "32px" }}>
        <div className="brand" style={{ marginBottom: "28px", justifyContent: "center" }}>
          <span className="brand-mark" style={{ background: "#17201d", color: "#e7f2ef" }}>D</span>
          <div>
            <strong style={{ fontSize: "18px" }}>DocMap</strong>
            <span style={{ color: "var(--muted)", fontSize: "13px", display: "block" }}>
              Clinic Intelligence OS
            </span>
          </div>
        </div>

        {error && (
          <div className="notice error" style={{ marginBottom: "16px" }}>
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} style={{ display: "grid", gap: "16px" }}>
          <label>
            Internal password
            <input
              name="password"
              type="password"
              required
              autoFocus
              placeholder="Enter password"
              style={{ marginTop: "6px" }}
            />
          </label>
          <button className="primary-button" type="submit" disabled={loading}>
            {loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
