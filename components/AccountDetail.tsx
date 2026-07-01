"use client";

import { useEffect, useState } from "react";
import type {
  ClinicAccount, ClinicSource, ClinicObservation,
  ClinicContact, ClinicInteraction, OutreachDraft,
  AccountTask, ClinicResearchRun, PipelineStage,
} from "@/types/database";

const PIPELINE_STAGES: PipelineStage[] = [
  "Identified", "Researching", "Contact found", "Outreach drafted",
  "Contacted", "Replied", "Meeting booked", "Demo completed",
  "Proposal sent", "Won", "Lost", "Paused",
];

interface AccountData {
  account: ClinicAccount;
  sources: ClinicSource[];
  observations: ClinicObservation[];
  contacts: ClinicContact[];
  interactions: ClinicInteraction[];
  drafts: OutreachDraft[];
  tasks: AccountTask[];
  research_runs: ClinicResearchRun[];
}

export default function AccountDetail({
  id,
  onStageChange,
}: {
  id: string;
  onStageChange?: () => void;
}) {
  const [data, setData] = useState<AccountData | null>(null);
  const [loading, setLoading] = useState(true);
  const [noteText, setNoteText] = useState("");

  const fetchData = async () => {
    setLoading(true);
    const res = await fetch(`/api/accounts/${id}`);
    setData(await res.json());
    setLoading(false);
  };

  useEffect(() => { fetchData(); }, [id]);

  const changeStage = async (to_stage: PipelineStage) => {
    await fetch(`/api/accounts/${id}/stage`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to_stage }),
    });
    fetchData();
    onStageChange?.();
  };

  const addNote = async () => {
    if (!noteText.trim()) return;
    await fetch(`/api/accounts/${id}/interactions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ body: noteText.trim() }),
    });
    setNoteText("");
    fetchData();
  };

  if (loading) return <div className="account-detail" style={{ padding: "20px", color: "var(--muted)" }}>Loading…</div>;
  if (!data) return null;

  const { account, sources, observations, contacts, interactions, drafts, tasks, research_runs } = data;

  return (
    <div className="account-detail">
      {/* Hero */}
      <div className="detail-hero">
        <div>
          <h2>{account.name}</h2>
          <a className="source-link" href={account.website_url} target="_blank" rel="noreferrer">
            {account.website_url}
          </a>
          <div className="tag-row" style={{ marginTop: "8px" }}>
            <span className="stage-pill">{account.pipeline_stage}</span>
            {account.next_action_due_at && (
              <span className="pill">Due {account.next_action_due_at}</span>
            )}
            <span className="pill">{sources.length} sources</span>
          </div>
          {/* Stage selector */}
          <div style={{ marginTop: "10px" }}>
            <select
              value={account.pipeline_stage}
              onChange={(e) => changeStage(e.target.value as PipelineStage)}
              style={{ width: "auto", fontSize: "13px" }}
            >
              {PIPELINE_STAGES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
        </div>
        <div className="score" aria-label="Fit score">
          <span><strong>{account.fit_score}</strong>fit</span>
        </div>
      </div>

      {/* Detail grid */}
      <div className="detail-grid">
        {/* Research runs */}
        {research_runs.length > 0 && (
          <section className="section-box full">
            <h3>Research Runs</h3>
            <div className="tag-row">
              {research_runs.map((run) => (
                <span key={run.id} className={`run-status ${run.status}`}>
                  {run.status}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* Contacts */}
        <section className="section-box">
          <h3>Contacts</h3>
          <ul className="list">
            {contacts.length === 0 && <li style={{ color: "var(--muted)" }}>Pending research</li>}
            {contacts.map((c) => (
              <li key={c.id}>
                <strong>{c.name}</strong> — {c.role}
                {c.email && <><br /><span className="source-link">{c.email}</span></>}
                <br /><span className="pill" style={{ marginTop: "4px" }}>{Math.round(c.confidence * 100)}% confidence</span>
              </li>
            ))}
          </ul>
        </section>

        {/* Observations */}
        <section className="section-box">
          <h3>Observations</h3>
          <ul className="list">
            {observations.length === 0 && <li style={{ color: "var(--muted)" }}>Pending research</li>}
            {observations.map((o) => {
              const src = sources.find((s) => s.id === o.source_id);
              return (
                <li key={o.id}>
                  <span className="pill" style={{ marginBottom: "4px" }}>{o.category}</span>
                  <p style={{ margin: "4px 0 0" }}>{o.text}</p>
                  {src && <a className="source-link" href={src.url ?? "#"} target="_blank" rel="noreferrer">{src.title}</a>}
                </li>
              );
            })}
          </ul>
        </section>

        {/* Sales angle */}
        {account.sales_angle && (
          <section className="section-box full">
            <h3>Likely DocMap Sales Angle</h3>
            <p style={{ margin: 0 }}>{account.sales_angle}</p>
          </section>
        )}

        {/* Outreach drafts */}
        {drafts.length > 0 && (
          <section className="section-box full">
            <h3>Outreach Drafts</h3>
            <ul className="list">
              {drafts.map((d) => (
                <li key={d.id}>
                  <div className="meta-row">
                    <strong>{d.subject}</strong>
                    <span className={`pill${d.status === "approved" ? "" : ""}`}>{d.status}</span>
                  </div>
                  <p style={{ margin: "6px 0 0", fontSize: "13px", color: "var(--muted)", whiteSpace: "pre-wrap" }}>
                    {d.body.slice(0, 200)}{d.body.length > 200 ? "…" : ""}
                  </p>
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Tasks */}
        {tasks.length > 0 && (
          <section className="section-box">
            <h3>Open Tasks</h3>
            <ul className="list">
              {tasks.map((t) => (
                <li key={t.id}>
                  {t.title}
                  {t.due_at && <span className="pill" style={{ marginLeft: "6px" }}>Due {t.due_at}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* Activity log */}
        <section className="section-box full">
          <h3>Activity</h3>
          <ul className="list">
            {interactions.map((i) => (
              <li key={i.id} style={{ fontSize: "13px" }}>
                <span style={{ color: "var(--muted)" }}>{i.occurred_at.slice(0, 10)}</span>
                {" — "}
                {i.body}
              </li>
            ))}
          </ul>
          <div style={{ display: "flex", gap: "8px", marginTop: "12px" }}>
            <input
              value={noteText}
              onChange={(e) => setNoteText(e.target.value)}
              placeholder="Add a note…"
              onKeyDown={(e) => e.key === "Enter" && addNote()}
            />
            <button className="text-button" onClick={addNote}>Add</button>
          </div>
        </section>
      </div>
    </div>
  );
}
