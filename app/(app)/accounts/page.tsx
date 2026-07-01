"use client";

import { useState, useEffect, useCallback } from "react";
import type { ClinicAccount } from "@/types/database";
import AccountDetail from "@/components/AccountDetail";
import NewAccountDialog from "@/components/NewAccountDialog";

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<ClinicAccount[]>([]);
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [showDialog, setShowDialog] = useState(false);
  const [loading, setLoading] = useState(true);

  const fetchAccounts = useCallback(async () => {
    const res = await fetch(`/api/accounts${query ? `?q=${encodeURIComponent(query)}` : ""}`);
    const data = await res.json();
    setAccounts(data);
    if (!selectedId && data.length > 0) setSelectedId(data[0].id);
    setLoading(false);
  }, [query, selectedId]);

  useEffect(() => { fetchAccounts(); }, [fetchAccounts]);

  const handleCreated = (account: ClinicAccount) => {
    setAccounts((prev) => [account, ...prev]);
    setSelectedId(account.id);
    setShowDialog(false);
  };

  const exportSelected = async () => {
    if (!selectedId) return;
    const res = await fetch(`/api/accounts/${selectedId}`);
    const data = await res.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${data.account?.name ?? "account"}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Human reviewed clinic outreach</p>
          <h1>Accounts</h1>
        </div>
        <div className="toolbar">
          <button className="icon-button" onClick={() => setShowDialog(true)} title="New account">+</button>
          <button className="icon-button" onClick={exportSelected} title="Export JSON">E</button>
        </div>
      </header>

      <div className="notice">
        <strong>Review gate:</strong>
        <span>No outreach is sent automatically. Drafts require owner approval.</span>
      </div>

      <div className="split-layout">
        {/* Account list */}
        <section className="panel" aria-label="Clinic accounts">
          <div className="panel-header">
            <h2>Clinic Accounts</h2>
            <input
              type="search"
              placeholder="Search clinics"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              style={{ width: "160px" }}
            />
          </div>
          {loading ? (
            <p style={{ color: "var(--muted)", fontSize: "14px" }}>Loading…</p>
          ) : (
            <div className="account-list">
              {accounts.length === 0 && (
                <p style={{ color: "var(--muted)", fontSize: "14px" }}>No accounts yet.</p>
              )}
              {accounts.map((a) => (
                <button
                  key={a.id}
                  className={`account-card${a.id === selectedId ? " active" : ""}`}
                  onClick={() => setSelectedId(a.id)}
                >
                  <strong>{a.name}</strong>
                  <span className="source-link">{a.website_url}</span>
                  <span className="meta-row">
                    <span className="stage-pill">{a.pipeline_stage}</span>
                    <span className="pill">Owner: {a.owner_user}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
        </section>

        {/* Account detail */}
        <section aria-label="Selected clinic">
          {selectedId ? (
            <AccountDetail id={selectedId} onStageChange={fetchAccounts} />
          ) : (
            <div className="account-detail" style={{ display: "grid", placeItems: "center", minHeight: "300px" }}>
              <p style={{ color: "var(--muted)" }}>Select a clinic to view details.</p>
            </div>
          )}
        </section>
      </div>

      {showDialog && (
        <NewAccountDialog onCreated={handleCreated} onClose={() => setShowDialog(false)} />
      )}
    </>
  );
}
