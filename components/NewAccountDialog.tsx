"use client";

import { useRef, type FormEvent } from "react";
import type { ClinicAccount } from "@/types/database";

export default function NewAccountDialog({
  onCreated,
  onClose,
}: {
  onCreated: (account: ClinicAccount) => void;
  onClose: () => void;
}) {
  const formRef = useRef<HTMLFormElement>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const form = new FormData(formRef.current!);
    const res = await fetch("/api/accounts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: form.get("name"),
        website_url: form.get("website_url"),
        owner_user: form.get("owner_user") || "internal",
        notes: form.get("notes") || undefined,
      }),
    });
    if (res.ok) {
      const account = await res.json();
      onCreated(account);
    }
  }

  return (
    <div
      style={{
        position: "fixed", inset: 0, background: "rgba(0,0,0,0.35)",
        display: "grid", placeItems: "center", zIndex: 50,
      }}
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="panel" style={{ width: "min(520px, calc(100vw - 32px))", padding: "24px" }}>
        <form ref={formRef} onSubmit={handleSubmit} style={{ display: "grid", gap: "14px" }}>
          <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0 }}>New Clinic Account</h2>
            <button type="button" className="icon-button" onClick={onClose}>×</button>
          </header>

          <label>
            Clinic name
            <input name="name" required placeholder="e.g. London Gynaecology" />
          </label>
          <label>
            Website URL
            <input name="website_url" type="url" required placeholder="https://…" />
          </label>
          <label>
            Owner
            <input name="owner_user" placeholder="Internal team" defaultValue="internal" />
          </label>
          <label>
            Notes (optional)
            <textarea name="notes" rows={4} placeholder="Any initial context about this clinic…" />
          </label>

          <footer style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
            <button type="button" className="text-button" onClick={onClose}>Cancel</button>
            <button type="submit" className="primary-button">Create</button>
          </footer>
        </form>
      </div>
    </div>
  );
}
