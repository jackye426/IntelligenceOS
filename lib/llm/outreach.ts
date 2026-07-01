import { openrouter, DEFAULT_MODEL } from "@/lib/openrouter";
import { parseLlmJson } from "@/lib/llm/parse";
import { OUTREACH_SYSTEM_PROMPT } from "@/lib/llm/prompts";
import type { ClinicAccount, ClinicObservation, ClinicSource } from "@/types/database";

interface DraftInput {
  account: ClinicAccount;
  observations: ClinicObservation[];
  sources: ClinicSource[];
  tone: string;
}

interface DraftOutput {
  subject: string;
  body: string;
}

const TONE_INSTRUCTIONS: Record<string, string> = {
  direct: "Be direct and professional. Lead with the specific observation, then the value.",
  warm:   "Be warm and approachable. Acknowledge the clinic's work before the observation.",
  brief:  "Be concise. No more than 3 short paragraphs. Every sentence must earn its place.",
};

export async function generateOutreachDraft(input: DraftInput): Promise<DraftOutput> {
  const { account, observations, sources, tone } = input;

  const observationSummary = observations
    .slice(0, 5)
    .map((o) => `- [${o.category}] ${o.text}`)
    .join("\n");

  const sourceContext = sources
    .slice(0, 5)
    .map((s) => `Page: ${s.title} (${s.url})\n${s.raw_text.slice(0, 600)}`)
    .join("\n\n---\n\n");

  const userMessage = `
Clinic: ${account.name}
Website: ${account.website_url}
Sales angle: ${account.sales_angle ?? "Pending research"}
Tone requested: ${tone} — ${TONE_INSTRUCTIONS[tone] ?? ""}

Key observations:
${observationSummary || "No approved observations yet — write based on general website context below."}

Website context:
${sourceContext || "No website content available yet."}
  `.trim();

  const completion = await openrouter.chat.completions.create({
    model: DEFAULT_MODEL,
    messages: [
      { role: "system", content: OUTREACH_SYSTEM_PROMPT },
      { role: "user", content: userMessage },
    ],
    temperature: 0.7,
  });

  const raw = completion.choices[0]?.message?.content ?? "";

  try {
    return parseLlmJson<DraftOutput>(raw);
  } catch {
    // If JSON parsing fails, return a fallback structure.
    return {
      subject: `Patient journey opportunity for ${account.name}`,
      body: raw,
    };
  }
}
