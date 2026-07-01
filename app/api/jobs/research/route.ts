import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { getBoss, JOBS } from "@/lib/boss";

// POST /api/jobs/research — queue a website research run for an existing account.
export async function POST(req: Request) {
  const { account_id } = await req.json();

  if (!account_id) {
    return NextResponse.json({ error: "account_id is required" }, { status: 400 });
  }

  // Fetch the account to validate it exists and get its website URL.
  const { data: account, error: fetchErr } = await supabase
    .from("clinic_accounts")
    .select("id, name, website_url")
    .eq("id", account_id)
    .is("deleted_at", null)
    .single();

  if (fetchErr || !account) {
    return NextResponse.json({ error: "Account not found" }, { status: 404 });
  }

  // Derive allowed domain from the website URL (SSRF protection: we only
  // ever fetch pages on this domain during the research run).
  const allowed_domain = new URL(account.website_url).hostname;

  // Create the research run record first so the UI can show its status.
  const { data: run, error: runErr } = await supabase
    .from("clinic_research_runs")
    .insert({
      clinic_account_id: account_id,
      submitted_url: account.website_url,
      allowed_domain,
      status: "queued",
    })
    .select()
    .single();

  if (runErr) return NextResponse.json({ error: runErr.message }, { status: 500 });

  // Push the job to pg-boss.
  const boss = await getBoss();
  await boss.send(JOBS.WEBSITE_RESEARCH, {
    run_id: run.id,
    account_id,
    website_url: account.website_url,
    allowed_domain,
  });

  // Advance account stage to Researching if still at Identified.
  const { data: current } = await supabase
    .from("clinic_accounts")
    .select("pipeline_stage")
    .eq("id", account_id)
    .single();

  if (current?.pipeline_stage === "Identified") {
    await supabase.from("clinic_accounts").update({ pipeline_stage: "Researching" }).eq("id", account_id);
    await supabase.from("pipeline_stage_history").insert({
      clinic_account_id: account_id,
      from_stage: "Identified",
      to_stage: "Researching",
      changed_by_user: "system",
      reason: "Research run queued",
    });
  }

  return NextResponse.json({ ok: true, run_id: run.id }, { status: 201 });
}
