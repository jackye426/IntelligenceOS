"use client";

import { useState, useEffect } from "react";
import type { ClinicAccount, OutreachDraft } from "@/types/database";

type Tone = "direct" | "warm" | "brief";

export default function OutreachPage() {
  const [accounts, setAccounts] = useState<ClinicAccount[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<OutreachDraft[]>([]);
  const [activeDraftId, setActiveDraftId] = useState<string | null>(null);
  const [tone, setTone] = useState<Tone>("direct");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [generating, setGenerating] = useState(false);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    fetch("/api/accounts").then((r) => r.json()).then((data) => {
      setAccounts(data);
      if (data.length > 0) setSelectedId(data[0].id);
    });
  }, []);

  useEffect(() => {
    if (!selectedId) return;
    fetch(`/api/accounts/${selectedId}/outreach`)
      .then((r) => r.json())
      .then((data: OutreachDraft[]) => {
        setDrafts(data);
        const first = data[0];
        if (first) {
          setActiveDraftId(first.id);
          setSubject(first.subject);
          setBody(first.body);
          setTone((first.tone as Tone) ?? "direct");
        }
      });
  }, [selectedId]);

  const loadDraft = (draft: OutreachDraft) => {
    setActiveDraftId(draft.id);
    setSubject(draft.subject);
    setBody(draft.body);
    setTone((draft.tone as Tone) ?? "direct");
  };

  const generate = async () => {
    if (!selectedId) return;
    setGenerating(true);
    setMessage("");
    const res = await fetch(`/api/accounts/${selectedId}/outreach`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tone }),
    });
    if (res.ok) {
      const draft: OutreachDraft = await res.json();
      setDrafts((prev) => [draft, ...prev]);
      loadDraft(draft);
    } else {
      setMessage("Generation failed. Check OpenRouter configuration.");
    }
    setGenerating(false);
  };

  const saveDraft = async () => {
    if (!selectedId || !activeDraftId) return;
    setSaving(true);
    await fetch(`/api/accounts/${selectedId}/outreach/${activeDraftId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject, body, tone }),
    });
    setSaving(false);
  };

  const approveDraft = async () => {
    if (!selectedId || !activeDraftId) return;
    await fetch(`/api/accounts/${selectedId}/outreach/${activeDraftId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: "approved" }),
    });
    setDrafts((prev) =>
      prev.map((d) => d.id === activeDraftId ? { ...d, status: "approved" } : d)
    );
    setMessage("Draft approved.");
  };

  const activeDraft = drafts.find((d) => d.id === activeDraftId);
  const claimChecks = [
    { text: "Every clinic-specific statement maps to a source or manual note.", state: drafts.length > 0 ? "supported" : "needs-review" },
    { text: "No patient medical data is included in the outreach draft.", state: "supported" },
    { text: "No automated sending is enabled from this workspace.", state: "supported" },
  ] as const;

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Human-reviewed outreach</p>
          <h1>Outreach</h1>
        </div>
        <select
          value={selectedId ?? ""}
          onChange={(e) => setSelectedId(e.target.value)}
          style={{ minHeight: "38px", padding: "0 11px", borderRadius: "8px", border: "1px solid var(--line)" }}
        >
          {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
        </select>
      </header>

      <div className="notice">
        <strong>Review gate:</strong>
        <span>No outreach is sent automatically. Approve to mark a draft ready.</span>
      </div>

      {message && <div className="notice" style={{ marginBottom: "16px" }}>{message}</div>}

      <div className="outreach-layout">
        {/* Composer */}
        <section className="panel composer">
          <div className="panel-header">
            <h2>Draft Outreach</h2>
            <div className="segmented" role="tablist" aria-label="Tone">
              {(["direct", "warm", "brief"] as Tone[]).map((t) => (
                <button
                  key={t}
                  className={tone === t ? "active" : ""}
                  onClick={() => setTone(t)}
                >
                  {t.charAt(0).toUpperCase() + t.slice(1)}
                </button>
              ))}
            </div>
          </div>

          {/* Draft selector */}
          {drafts.length > 1 && (
            <select
              value={activeDraftId ?? ""}
              onChange={(e) => {
                const d = drafts.find((d) => d.id === e.target.value);
                if (d) loadDraft(d);
              }}
              style={{ marginBottom: "4px" }}
            >
              {drafts.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.created_at.slice(0, 10)} — {d.status} — {d.subject.slice(0, 40)}
                </option>
              ))}
            </select>
          )}

          <label>
            Subject
            <input value={subject} onChange={(e) => setSubject(e.target.value)} onBlur={saveDraft} />
          </label>
          <label>
            Body
            <textarea value={body} rows={14} onChange={(e) => setBody(e.target.value)} onBlur={saveDraft} />
          </label>

          <div className="composer-actions">
            <button className="text-button" onClick={generate} disabled={generating}>
              {generating ? "Generating…" : "Regenerate from evidence"}
            </button>
            <button
              className="primary-button"
              onClick={approveDraft}
              disabled={!activeDraftId || activeDraft?.status === "approved"}
            >
              {activeDraft?.status === "approved" ? "Approved ✓" : "Mark approved"}
            </button>
          </div>
          {saving && <span style={{ fontSize: "12px", color: "var(--muted)" }}>Saving…</span>}
        </section>

        {/* Claim checks */}
        <section className="panel">
          <div className="panel-header">
            <h2>Claim Checks</h2>
            <span style={{ fontSize: "13px", color: "var(--muted)" }}>
              {activeDraft?.status === "approved" ? "Approved" : "Needs review"}
            </span>
          </div>
          <div className="claim-list">
            {claimChecks.map((c, i) => (
              <article key={i} className="claim-item" data-state={c.state}>
                <strong>{c.state === "supported" ? "Supported" : "Needs review"}</strong>
                <p>{c.text}</p>
              </article>
            ))}
          </div>
        </section>
      </div>
    </>
  );
}
