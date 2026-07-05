import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import type { PipelineStage } from "@/types/database";

// GET /api/accounts — list all non-deleted accounts, newest first.
export async function GET(req: Request) {
  const { searchParams } = new URL(req.url);
  const q = searchParams.get("q")?.trim();
  const limit = parseInt(searchParams.get("limit") || "50", 10);

  let query = supabase
    .from("clinic_accounts")
    .select(`
      id, name, website_url, owner_user, pipeline_stage,
      fit_score, sales_angle, next_action, next_action_due_at,
      created_at, updated_at
    `)
    .is("deleted_at", null)
    .order("created_at", { ascending: false });

  if (q) {
    query = query.ilike("name", `%${q}%`);
  }

  const { data, error } = await query.limit(limit);
  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

// POST /api/accounts — create a new clinic account with an initial manual source.
export async function POST(req: Request) {
  const body = await req.json();
  const { name, website_url, owner_user = "internal", notes } = body;

  if (!name || !website_url) {
    return NextResponse.json({ error: "name and website_url are required" }, { status: 400 });
  }

  // Insert the account.
  const { data: account, error: accountErr } = await supabase
    .from("clinic_accounts")
    .insert({ name, website_url, owner_user })
    .select()
    .single();

  if (accountErr) return NextResponse.json({ error: accountErr.message }, { status: 500 });

  // If notes were provided, create a manual_note source immediately.
  if (notes) {
    await supabase.from("clinic_sources").insert({
      clinic_account_id: account.id,
      type: "manual_note",
      title: "Manual intake",
      raw_text: notes,
      content_hash: Buffer.from(notes).toString("base64").slice(0, 64),
    });
  }

  // Write the initial pipeline stage history entry.
  await supabase.from("pipeline_stage_history").insert({
    clinic_account_id: account.id,
    from_stage: null,
    to_stage: "Identified" as PipelineStage,
    changed_by_user: owner_user,
    reason: "Account created",
  });

  // Log the creation interaction.
  await supabase.from("clinic_interactions").insert({
    clinic_account_id: account.id,
    type: "system_event",
    body: "Account created.",
    created_by_user: owner_user,
  });

  return NextResponse.json(account, { status: 201 });
}
