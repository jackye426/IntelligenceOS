import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { generateOutreachDraft } from "@/lib/llm/outreach";

type Params = { params: Promise<{ id: string }> };

// GET /api/accounts/[id]/outreach — list all drafts for this account.
export async function GET(_req: Request, { params }: Params) {
  const { id } = await params;

  const { data, error } = await supabase
    .from("outreach_drafts")
    .select("*")
    .eq("clinic_account_id", id)
    .order("created_at", { ascending: false });

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data);
}

// POST /api/accounts/[id]/outreach/generate — generate a new draft via LLM.
export async function POST(req: Request, { params }: Params) {
  const { id } = await params;
  const { tone = "direct", run_id } = await req.json();

  // Load the account profile and its approved observations + sources.
  const [accountRes, obsRes, sourcesRes] = await Promise.all([
    supabase.from("clinic_accounts").select("*").eq("id", id).single(),
    supabase.from("clinic_observations").select("*").eq("clinic_account_id", id).eq("review_status", "approved"),
    supabase.from("clinic_sources").select("id, clinic_account_id, type, url, title, captured_at, raw_text, content_hash, approved_for_use").eq("clinic_account_id", id).eq("approved_for_use", true).limit(10),
  ]);

  if (accountRes.error) return NextResponse.json({ error: accountRes.error.message }, { status: 404 });

  const draft = await generateOutreachDraft({
    account: accountRes.data,
    observations: obsRes.data ?? [],
    sources: sourcesRes.data ?? [],
    tone,
  });

  const { data, error } = await supabase
    .from("outreach_drafts")
    .insert({
      clinic_account_id: id,
      subject: draft.subject,
      body: draft.body,
      tone,
      status: "draft",
      generated_from_run_id: run_id ?? null,
    })
    .select()
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 500 });
  return NextResponse.json(data, { status: 201 });
}
