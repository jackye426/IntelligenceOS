import { NextResponse } from "next/server";
import { getBoss, JOBS } from "@/lib/boss";

// POST /api/jobs/doctify — queue a Doctify listing scrape.
// The worker will extract all clinic cards on the page, store them as
// doctify_profiles, and automatically queue website_research for each
// clinic that has a website URL listed.
export async function POST(req: Request) {
  const { doctify_url } = await req.json();

  if (!doctify_url || !doctify_url.includes("doctify.com")) {
    return NextResponse.json({ error: "A valid Doctify URL is required" }, { status: 400 });
  }

  const boss = await getBoss();
  const jobId = await boss.send(JOBS.DOCTIFY_SCRAPE, { doctify_url });

  return NextResponse.json({ ok: true, job_id: jobId }, { status: 201 });
}
