import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";

type Params = { params: Promise<{ runId: string }> };

// GET /api/jobs/status/[runId] — poll the current status of a research run.
export async function GET(_req: Request, { params }: Params) {
  const { runId } = await params;

  const { data, error } = await supabase
    .from("clinic_research_runs")
    .select("id, status, error, started_at, finished_at")
    .eq("id", runId)
    .single();

  if (error) return NextResponse.json({ error: error.message }, { status: 404 });
  return NextResponse.json(data);
}
