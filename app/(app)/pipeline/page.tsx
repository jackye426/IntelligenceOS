"use client";

import { useEffect, useState } from "react";
import type { ClinicAccount, PipelineStage } from "@/types/database";

const STAGES: PipelineStage[] = [
  "Identified", "Researching", "Contact found", "Outreach drafted",
  "Contacted", "Replied", "Meeting booked", "Demo completed",
  "Proposal sent", "Won", "Lost", "Paused",
];

export default function PipelinePage() {
  const [accounts, setAccounts] = useState<ClinicAccount[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/accounts")
      .then((r) => r.json())
      .then((data) => { setAccounts(data); setLoading(false); });
  }, []);

  // Only render stages that have at least one account.
  const activeStages = STAGES.filter((s) => accounts.some((a) => a.pipeline_stage === s));

  return (
    <>
      <header className="topbar">
        <div>
          <p className="eyebrow">Sales pipeline</p>
          <h1>Pipeline</h1>
        </div>
        <span className="pill">{accounts.length} accounts</span>
      </header>

      {loading ? (
        <p style={{ color: "var(--muted)" }}>Loading…</p>
      ) : (
        <div className="pipeline-board" style={{ overflowX: "auto" }}>
          {activeStages.map((stage) => {
            const stageAccounts = accounts.filter((a) => a.pipeline_stage === stage);
            return (
              <section key={stage} className="pipeline-column">
                <h2>
                  {stage}
                  <span className="pill">{stageAccounts.length}</span>
                </h2>
                {stageAccounts.map((a) => (
                  <article key={a.id} className="deal-card">
                    <a href={`/accounts?selected=${a.id}`} style={{ textDecoration: "none", color: "inherit" }}>
                      <strong>{a.name}</strong>
                    </a>
                    {a.next_action && <span style={{ fontSize: "13px", color: "var(--muted)" }}>{a.next_action}</span>}
                    <span className="meta-row">
                      <span className="pill">Owner: {a.owner_user}</span>
                      {a.next_action_due_at && <span className="pill">Due {a.next_action_due_at}</span>}
                      <span className="pill">Fit {a.fit_score}</span>
                    </span>
                  </article>
                ))}
              </section>
            );
          })}

          {activeStages.length === 0 && (
            <p style={{ color: "var(--muted)" }}>No accounts in the pipeline yet.</p>
          )}
        </div>
      )}
    </>
  );
}
