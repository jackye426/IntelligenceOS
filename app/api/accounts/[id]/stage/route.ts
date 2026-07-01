import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import type { PipelineStage } from "@/types/database";

const VALID_STAGES: PipelineStage[] = [
  "Identified", "Researching", "Contact found", "Outreach drafted",
  "Contacted", "Replied", "Meeting booked", "Demo completed",
  "Proposal sent", "Won", "Lost", "Paused",
];

type Params = { params: Promise<{ id: string }> };

// POST /api/accounts/[id]/stage — advance or change the pipeline stage.
export async function POST(req: Request, { params }: Params) {
  const { id } = await params;
  const { to_stage, reason, changed_by_user = "internal" } = await req.json();

  if (!VALID_STAGES.includes(to_stage)) {
    return NextResponse.json({ error: `Invalid stage: ${to_stage}` }, { status: 400 });
  }

  // Fetch current stage to record in history.
  const { data: account, error: fetchErr } = await supabase
    .from("clinic_accounts")
    .select("pipeline_stage")
    .eq("id", id)
    .single();

  if (fetchErr) return NextResponse.json({ error: fetchErr.message }, { status: 404 });

  // Update the account.
  const { error: updateErr } = await supabase
    .from("clinic_accounts")
    .update({ pipeline_stage: to_stage })
    .eq("id", id);

  if (updateErr) return NextResponse.json({ error: updateErr.message }, { status: 500 });

  // Write immutable history entry.
  await supabase.from("pipeline_stage_history").insert({
    clinic_account_id: id,
    from_stage: account.pipeline_stage as PipelineStage,
    to_stage: to_stage as PipelineStage,
    changed_by_user,
    reason: reason ?? null,
  });

  // Log as an interaction.
  await supabase.from("clinic_interactions").insert({
    clinic_account_id: id,
    type: "system_event",
    body: `Stage changed from "${account.pipeline_stage}" to "${to_stage}".${reason ? ` Reason: ${reason}` : ""}`,
    created_by_user: changed_by_user,
  });

  return NextResponse.json({ ok: true, to_stage });
}
