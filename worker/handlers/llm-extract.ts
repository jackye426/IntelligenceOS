import { supabase } from "@/lib/supabase";
import { getBoss, JOBS } from "@/lib/boss";
import { openrouter, DEFAULT_MODEL, JUDGE_MODEL } from "@/lib/openrouter";
import { parseLlmJson } from "@/lib/llm/parse";
import { ENRICHMENT_SYSTEM_PROMPT, JUDGE_SYSTEM_PROMPT } from "@/lib/llm/prompts";

const MAX_CONTEXT_CHARS = 80_000; // total chars sent to the LLM across all pages
const MAX_RETRIES = 2;

interface EnrichmentResult {
  fit_score: number;
  fit_reason: string;
  clinic_summary: string;
  services: string[];
  key_people: { name: string; role: string }[];
  patient_journey_observations: {
    category: string;
    text: string;
    confidence: number;
    source_url: string;
  }[];
  best_sales_angle: string;
  possible_objection: string;
  ideal_patient_type: string;
}

interface JudgeResult {
  approved: boolean;
  reason: string;
}

async function callEnrichment(userMessage: string, retries = 0): Promise<EnrichmentResult> {
  const completion = await openrouter.chat.completions.create({
    model: DEFAULT_MODEL,
    messages: [
      { role: "system", content: ENRICHMENT_SYSTEM_PROMPT },
      { role: "user", content: userMessage },
    ],
    temperature: 0.2, // Low temperature for structured extraction.
  });

  const raw = completion.choices[0]?.message?.content ?? "";
  try {
    return parseLlmJson<EnrichmentResult>(raw);
  } catch {
    if (retries < MAX_RETRIES) return callEnrichment(userMessage, retries + 1);
    throw new Error(`Failed to parse LLM JSON after ${MAX_RETRIES} retries: ${raw.slice(0, 200)}`);
  }
}

async function callJudge(enrichmentJson: string): Promise<JudgeResult> {
  const completion = await openrouter.chat.completions.create({
    model: JUDGE_MODEL,
    messages: [
      { role: "system", content: JUDGE_SYSTEM_PROMPT },
      { role: "user", content: enrichmentJson },
    ],
    temperature: 0,
  });
  const raw = completion.choices[0]?.message?.content ?? '{"approved":true,"reason":"No issues found"}';
  try {
    return parseLlmJson<JudgeResult>(raw);
  } catch {
    return { approved: true, reason: "Judge parse failed — defaulting to approved" };
  }
}

// ── Job handler ───────────────────────────────────────────────────────────────

export async function handleLlmExtract(job: { data: { run_id: string; account_id: string } }) {
  const { run_id, account_id } = job.data;
  console.log(`[llm-extract] Starting for run ${run_id}`);

  try {
    // Load the account and all approved sources.
    const [accountRes, sourcesRes] = await Promise.all([
      supabase.from("clinic_accounts").select("*").eq("id", account_id).single(),
      supabase.from("clinic_sources")
        .select("id, title, url, raw_text")
        .eq("clinic_account_id", account_id)
        .eq("approved_for_use", true)
        .order("captured_at", { ascending: false }),
    ]);

    if (accountRes.error) throw new Error(accountRes.error.message);
    const account = accountRes.data;
    const sources = sourcesRes.data ?? [];

    if (sources.length === 0) {
      throw new Error("No approved sources to extract from");
    }

    // Build the context string — concatenate page texts up to token budget.
    let contextChars = 0;
    const pageContexts: string[] = [];
    for (const source of sources) {
      const chunk = `--- Page: ${source.title} (${source.url}) ---\n${source.raw_text}`;
      if (contextChars + chunk.length > MAX_CONTEXT_CHARS) break;
      pageContexts.push(chunk);
      contextChars += chunk.length;
    }

    const userMessage = `
Clinic: ${account.name}
Website: ${account.website_url}

Website pages (${pageContexts.length} of ${sources.length} total):

${pageContexts.join("\n\n")}
    `.trim();

    // ── Enrichment call ───────────────────────────────────────────────────
    const result = await callEnrichment(userMessage);

    // ── Judge pass ────────────────────────────────────────────────────────
    const judge = await callJudge(JSON.stringify(result));
    if (!judge.approved) {
      console.warn(`[llm-extract] Judge rejected run ${run_id}: ${judge.reason}`);
      // Still save, but mark observations as draft for human review.
    }

    // ── Persist results ───────────────────────────────────────────────────

    // Update account-level fields.
    await supabase.from("clinic_accounts").update({
      fit_score: result.fit_score,
      sales_angle: result.best_sales_angle,
    }).eq("id", account_id);

    const VALID_CATEGORIES = new Set(["patient_journey", "pricing", "service", "contact_route", "positioning"]);

    // Upsert observations — link each to the source page it came from.
    for (const obs of result.patient_journey_observations) {
      const category = VALID_CATEGORIES.has(obs.category) ? obs.category : "patient_journey";
      const matchedSource = sources.find((s) => s.url === obs.source_url);
      await supabase.from("clinic_observations").insert({
        clinic_account_id: account_id,
        source_id: matchedSource?.id ?? null,
        category: category as "patient_journey" | "pricing" | "service" | "contact_route" | "positioning",
        text: obs.text,
        confidence: Math.min(1, Math.max(0, obs.confidence ?? 0.5)),
        review_status: judge.approved ? "approved" : "draft",
      });
    }

    // Upsert contacts (key people found on the site).
    for (const person of result.key_people) {
      if (!person.name) continue;
      await supabase.from("clinic_contacts").insert({
        clinic_account_id: account_id,
        name: person.name,
        role: person.role ?? "Unknown",
        confidence: 0.7,
        review_status: judge.approved ? "approved" : "draft",
      });
    }

    // Log extraction as an interaction.
    await supabase.from("clinic_interactions").insert({
      clinic_account_id: account_id,
      type: "system_event",
      body: `LLM extraction complete. Fit score: ${result.fit_score}. Judge: ${judge.approved ? "approved" : "needs review"} — ${judge.reason}`,
      created_by_user: "system",
    });

    // Mark the run as needs_review (human must approve before outreach).
    await supabase.from("clinic_research_runs").update({
      status: "needs_review",
      finished_at: new Date().toISOString(),
    }).eq("id", run_id);

    // Queue embedding for the updated account profile.
    const boss = await getBoss();
    await boss.send(JOBS.EMBED_DOCUMENT, {
      entity_type: "clinic_account",
      entity_id: account_id,
      content: [
        account.name,
        result.clinic_summary,
        result.best_sales_angle,
        result.patient_journey_observations.map((o) => o.text).join(" "),
      ].filter(Boolean).join("\n"),
    });

    console.log(`[llm-extract] Run ${run_id} complete. Score: ${result.fit_score}`);
  } catch (err) {
    console.error(`[llm-extract] Run ${run_id} failed:`, err);
    await supabase.from("clinic_research_runs").update({
      status: "failed",
      error: String(err),
      finished_at: new Date().toISOString(),
    }).eq("id", run_id);
  }
}
