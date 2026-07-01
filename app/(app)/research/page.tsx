"use client";

import { useState, useEffect, type FormEvent } from "react";
import type { ClinicAccount, ClinicSource } from "@/types/database";

interface RunStatus {
  id: string;
  status: string;
  submitted_url: string;
  error: string | null;
  created_at: string;
}

export default function ResearchPage() {
  const [accounts, setAccounts] = useState<ClinicAccount[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sources, setSources] = useState<ClinicSource[]>([]);
  const [runs, setRuns] = useState<RunStatus[]>([]);
  const [queueing, setQueueing] = useState(false);
  const [doctifyUrl, setDoctifyUrl] = useState("");
  const [doctifyQueuing, setDoctifyQueuing] = useState(false);
  const [message, setMessage] = useState("");

  // Load accounts for the selector.
  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((data) => { setAccounts(data); if (data.length > 0) setSelectedId(data[0].id); });
  }, []);

  // Reload sources and runs when selected account changes.
  useEffect(() => {
    if (!selectedId) return;
    fetch(`/api/accounts/${selectedId}`)
      .then((r) => r.json())
      .then((d) => { setSources(d.sources ?? []); setRuns(d.research_runs ?? []); });
  }, [selectedId]);

  const queueResearch = async () => {
    if (!selectedId) return;
    setQueueing(true);
    setMessage("");
    const res = await fetch("/api/jobs/research", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ account_id: selectedId }),
    });
    const json = await res.json();
    setMessage(res.ok ? `Research run queued (ID: ${json.run_id})` : json.error);
    setQueueing(false);
    // Reload runs after queuing.
    fetch(`/api/accounts/${selectedId}`)
      .then((r) => r.json())
      .then((d) => setRuns(d.research_runs ?? []));
  };

  const queueDoctify = async (e: FormEvent) => {
    e.preventDefault();
    if (!doctifyUrl) return;
    setDoctifyQueuing(true);
    setMessage("");
    const res = await fetch("/api/jobs/doctify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ doctify_url: doctifyUrl }),
    });
    const json = await res.json();
    setMessage(res.ok ? `Doctify scrape queued.` : json.error);
    setDoctifyQueuing(false);
    setDoctifyUrl("");
  };

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Source ingestion</p>
          <h1>Research</h1>
        </div>
      </header>

      {message && (
        <div className="notice" style={{ marginBottom: "16px" }}>{message}</div>
      )}

      <div className="research-grid">
        {/* Controls panel */}
        <div style={{ display: "grid", gap: "16px" }}>
          {/* Website research */}
          <section className="panel">
            <div className="panel-header">
              <h2>Website Research</h2>
              <button className="text-button" onClick={queueResearch} disabled={queueing || !selectedId}>
                {queueing ? "Queuing…" : "Queue run"}
              </button>
            </div>
            <div className="research-form">
              <label>
                Account
                <select value={selectedId ?? ""} onChange={(e) => setSelectedId(e.target.value)}>
                  {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </label>
            </div>
            {runs.length > 0 && (
              <div style={{ marginTop: "14px" }}>
                <h3 style={{ fontSize: "13px", color: "var(--muted)", marginBottom: "8px" }}>Recent runs</h3>
                {runs.map((run) => (
                  <div key={run.id} className="tag-row" style={{ marginBottom: "6px" }}>
                    <span className={`run-status ${run.status}`}>{run.status}</span>
                    <span style={{ fontSize: "12px", color: "var(--muted)" }}>{run.created_at.slice(0, 10)}</span>
                    {run.error && <span style={{ fontSize: "12px", color: "var(--red)" }}>{run.error}</span>}
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Doctify scraper */}
          <section className="panel">
            <div className="panel-header">
              <h2>Doctify Scraper</h2>
            </div>
            <form onSubmit={queueDoctify} className="research-form">
              <label>
                Doctify listing URL
                <input
                  type="url"
                  value={doctifyUrl}
                  onChange={(e) => setDoctifyUrl(e.target.value)}
                  placeholder="https://www.doctify.com/uk/…"
                  required
                />
              </label>
              <button type="submit" className="primary-button" disabled={doctifyQueuing}>
                {doctifyQueuing ? "Queuing…" : "Queue Doctify scrape"}
              </button>
            </form>
          </section>
        </div>

        {/* Evidence ledger */}
        <section className="panel evidence-panel">
          <div className="panel-header">
            <h2>Evidence Ledger</h2>
            <span style={{ fontSize: "13px", color: "var(--muted)" }}>{sources.length} sources</span>
          </div>
          <div className="evidence-list">
            {sources.length === 0 && (
              <p style={{ color: "var(--muted)", fontSize: "14px" }}>
                No sources yet. Queue a research run to begin.
              </p>
            )}
            {sources.map((s) => (
              <article key={s.id} className="evidence-item">
                <h3 style={{ marginBottom: "6px" }}>{s.title}</h3>
                <p style={{ fontSize: "13px", color: "var(--muted)" }}>
                  {s.raw_text.slice(0, 300)}{s.raw_text.length > 300 ? "…" : ""}
                </p>
                {s.url && (
                  <a className="source-link" href={s.url} target="_blank" rel="noreferrer">{s.url}</a>
                )}
                <div className="tag-row" style={{ marginTop: "8px" }}>
                  <span className="pill">{s.type}</span>
                  <span className="pill">Captured {s.captured_at.slice(0, 10)}</span>
                </div>
              </article>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
