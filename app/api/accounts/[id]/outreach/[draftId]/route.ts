import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

type Params = { params: Promise<{ id: string; draftId: string }> };

// PATCH /api/accounts/[id]/outreach/[draftId] — update or approve a draft.
export async function PATCH(req: Request, { params }: Params) {
  const { id, draftId } = await params;
  const body = await req.json();

  const update: Record<string, unknown> = {};

  if ("subject" in body) update.subject = body.subject;
  if ("body" in body) update.body = body.body;
  if ("tone" in body) update.tone = body.tone;

  // Approving a draft is a one-way transition.
  if (body.status === "approved") {
    update.status = "approved";
    update.approved_by_user = body.approved_by_user ?? "internal";
    update.approved_at = new Date().toISOString();

    // Automatically advance the account stage to "Outreach drafted" if still earlier.
    const { data: account } = await supabase
      .from("clinic_accounts")
      .select("pipeline_stage")
      .eq("id", id)
      .single();

    const earlyStages = ["Identified", "Researching", "Contact found"];
    if (account && earlyStages.includes(account.pipeline_stage)) {
      await supabase.from("clinic_accounts").update({ pipeline_stage: "Outreach drafted" }).eq("id", id);
      await supabase.from("pipeline_stage_history").insert({
        clinic_account_id: id,
        from_stage: account.pipeline_stage,
        to_stage: "Outreach drafted",
        changed_by_user: update.approved_by_user as string,
        reason: "Outreach draft approved",
      });
    }

    // Log the approval as an interaction.
    await supabase.from("clinic_interactions").insert({
      clinic_account_id: id,
      type: "system_event",
      body: "Outreach draft approved by owner.",
      created_by_user: update.approved_by_user as string,
    });
  }

  if (["sent_elsewhere", "archived"].includes(body.status)) {
    update.status = body.status;
  }

  const { data, error } = await supabase
    .from("outreach_drafts")
    .update(update)
    .eq("id", draftId)
    .eq("clinic_account_id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}
