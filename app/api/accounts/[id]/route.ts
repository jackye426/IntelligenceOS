import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

type Params = { params: Promise<{ id: string }> };

// GET /api/accounts/[id] — full account detail with related records.
export async function GET(_req: Request, { params }: Params) {
  const { id } = await params;

  const [accountRes, sourcesRes, observationsRes, contactsRes, interactionsRes, draftsRes, tasksRes, runsRes] =
    await Promise.all([
      supabase.from("clinic_accounts").select("*").eq("id", id).is("deleted_at", null).single(),
      supabase.from("clinic_sources").select("*").eq("clinic_account_id", id).order("captured_at", { ascending: false }),
      supabase.from("clinic_observations").select("*").eq("clinic_account_id", id).neq("review_status", "rejected"),
      supabase.from("clinic_contacts").select("*").eq("clinic_account_id", id).neq("review_status", "rejected"),
      supabase.from("clinic_interactions").select("*").eq("clinic_account_id", id).order("occurred_at", { ascending: false }).limit(50),
      supabase.from("outreach_drafts").select("*").eq("clinic_account_id", id).order("created_at", { ascending: false }),
      supabase.from("account_tasks").select("*").eq("clinic_account_id", id).neq("status", "cancelled").order("due_at"),
      supabase.from("clinic_research_runs").select("id, status, submitted_url, started_at, finished_at, error, created_at").eq("clinic_account_id", id).order("created_at", { ascending: false }).limit(10),
    ]);

  if (accountRes.error) return NextResponse.json({ error: accountRes.error.message }, { status: 404 });

  return NextResponse.json({
    account: accountRes.data,
    sources: sourcesRes.data ?? [],
    observations: observationsRes.data ?? [],
    contacts: contactsRes.data ?? [],
    interactions: interactionsRes.data ?? [],
    drafts: draftsRes.data ?? [],
    tasks: tasksRes.data ?? [],
    research_runs: runsRes.data ?? [],
  });
}

// PATCH /api/accounts/[id] — update mutable account fields.
export async function PATCH(req: Request, { params }: Params) {
  const { id } = await params;
  const body = await req.json();

  // Only allow updating safe fields; never let callers touch id or timestamps.
  const allowed = [
    "name", "website_url", "owner_user",
    "fit_score", "sales_angle", "next_action", "next_action_due_at",
  ] as const;

  const update: Record<string, unknown> = {};
  for (const key of allowed) {
    if (key in body) update[key] = body[key];
  }

  if (Object.keys(update).length === 0) {
    return NextResponse.json({ error: "No valid fields to update" }, { status: 400 });
  }

  update.updated_at = new Date().toISOString();

  const { data, error } = await supabase
    .from("clinic_accounts")
    .update(update)
    .eq("id", id)
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

// DELETE /api/accounts/[id] — soft delete.
export async function DELETE(_req: Request, { params }: Params) {
  const { id } = await params;

  const { error } = await supabase
    .from("clinic_accounts")
    .update({ deleted_at: new Date().toISOString() })
    .eq("id", id);

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json({ ok: true });
}
