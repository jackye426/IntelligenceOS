/**
 * One-time seed: embed all doctor_recommendation_events into document_embeddings.
 *
 * Run after:
 *   1. sql/003_doctor_outreach.sql has been run in Supabase
 *   2. sync_whatsapp_and_history_to_supabase.py has populated doctor_recommendation_events
 *
 * Usage:
 *   npx tsx scripts/seed-embeddings.ts
 */

import "dotenv/config";
import { createClient } from "@supabase/supabase-js";
import OpenAI from "openai";
import { createHash } from "crypto";

const supabase = createClient(
  process.env.NEXT_PUBLIC_SUPABASE_URL!,
  process.env.SUPABASE_KEY!
);

const openrouter = new OpenAI({
  apiKey: process.env.OPENROUTER_API_KEY!,
  baseURL: "https://openrouter.ai/api/v1",
});

const EMBEDDING_MODEL =
  process.env.OPENROUTER_EMBEDDING_MODEL ?? "openai/text-embedding-3-small";

// Strip WhatsApp phone numbers (e.g. +447700900000 or 07700 900000)
// and replace with a stable anonymous ID derived from the number.
function anonymisePhoneNumbers(text: string): string {
  return text.replace(
    /(\+?(?:44|0)\s*\d[\d\s\-()]{8,14}\d)/g,
    (match) => {
      const id = createHash("sha256").update(match.replace(/\s/g, "")).digest("hex").slice(0, 8);
      return `[CONTACT:${id}]`;
    }
  );
}

// Build the text to embed for a recommendation event.
// Combines rationale + raw_block, preferring rationale as the lead.
function buildContent(event: {
  display_name: string | null;
  title: string | null;
  rationale: string | null;
  raw_block: string | null;
  profile_url: string | null;
}): string {
  const parts: string[] = [];

  if (event.display_name) {
    const name = event.title ? `${event.title} ${event.display_name}` : event.display_name;
    parts.push(`Practitioner: ${name}`);
  }
  if (event.profile_url) {
    parts.push(`Profile: ${event.profile_url}`);
  }
  if (event.rationale) {
    parts.push(`Recommendation rationale: ${event.rationale}`);
  }
  if (event.raw_block) {
    parts.push(`Full recommendation block:\n${anonymisePhoneNumbers(event.raw_block)}`);
  }

  return parts.join("\n\n").trim();
}

async function embedOne(event: {
  event_id: string;
  practitioner_id: string;
  display_name: string | null;
  title: string | null;
  rationale: string | null;
  raw_block: string | null;
  profile_url: string | null;
}): Promise<void> {
  const content = buildContent(event);
  if (!content) return;

  const res = await openrouter.embeddings.create({
    model: EMBEDDING_MODEL,
    input: content.slice(0, 8000),
  });

  const vector = res.data[0]?.embedding;
  if (!vector) throw new Error(`No embedding returned for event ${event.event_id}`);

  // Upsert by event_id (entity_type + entity_id pair is the natural key).
  const { data: existing } = await supabase
    .from("document_embeddings")
    .select("id")
    .eq("entity_type", "recommendation_event")
    .eq("entity_id", event.event_id)
    .limit(1)
    .single();

  if (existing) {
    await supabase
      .from("document_embeddings")
      .update({ content, embedding: vector as unknown as string })
      .eq("id", existing.id);
  } else {
    await supabase.from("document_embeddings").insert({
      entity_type: "recommendation_event",
      entity_id: event.event_id,
      content,
      embedding: vector as unknown as string,
    });
  }
}

async function main() {
  console.log("[seed-embeddings] Loading recommendation events...");

  const { data: events, error } = await supabase
    .from("doctor_recommendation_events")
    .select("event_id, practitioner_id, display_name, title, rationale, raw_block, profile_url")
    .order("recommended_at", { ascending: true });

  if (error) {
    console.error("[seed-embeddings] Failed to load events:", error.message);
    process.exit(1);
  }

  const total = events?.length ?? 0;
  console.log(`[seed-embeddings] ${total} events to embed.`);

  let done = 0;
  let skipped = 0;
  let failed = 0;

  for (const event of events ?? []) {
    const content = buildContent(event);
    if (!content) {
      skipped++;
      continue;
    }

    try {
      await embedOne(event);
      done++;
      if (done % 10 === 0) {
        console.log(`[seed-embeddings] ${done}/${total} embedded...`);
      }
      // Polite delay to avoid rate limits.
      await new Promise((r) => setTimeout(r, 300));
    } catch (err) {
      console.error(`[seed-embeddings] Failed for ${event.event_id}:`, err);
      failed++;
    }
  }

  console.log(
    `[seed-embeddings] Done. Embedded: ${done}, Skipped (no content): ${skipped}, Failed: ${failed}`
  );
}

main().catch((err) => {
  console.error("[seed-embeddings] Fatal:", err);
  process.exit(1);
});
