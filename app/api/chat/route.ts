import { NextResponse } from "next/server";
import { supabase } from "@/lib/supabase";
import { openrouter, DEFAULT_MODEL } from "@/lib/openrouter";
import type { ChatCompletionMessageParam } from "openai/resources/chat/completions";

const EMBEDDING_MODEL = process.env.OPENROUTER_EMBEDDING_MODEL ?? "openai/text-embedding-3-small";
const TOP_K = 8; // chunks to retrieve per query

const SYSTEM_PROMPT = `
You are an internal assistant for DocMap, a UK healthcare patient-navigation company.
You have access to DocMap's clinic intelligence database: clinic profiles, patient journey
observations, outreach drafts, and interaction history.

Answer questions accurately using only the provided context.
For each claim, cite the source by referring to the entity (e.g. "London Gynaecology — observation").
If the context doesn't contain enough information, say so clearly.
Do not invent clinic-specific details.
`.trim();

export async function POST(req: Request) {
  const { query, messages = [] } = await req.json();
  if (!query) return NextResponse.json({ error: "query is required" }, { status: 400 });

  // ── Step 1: Embed the user query ─────────────────────────────────────────
  const embeddingRes = await openrouter.embeddings.create({
    model: EMBEDDING_MODEL,
    input: query.slice(0, 2000),
  });

  const queryVector = embeddingRes.data[0]?.embedding;
  if (!queryVector) return NextResponse.json({ error: "Embedding failed" }, { status: 500 });

  // ── Step 2: Retrieve top-k similar documents via pgvector ────────────────
  const { data: chunks, error: rpcError } = await supabase.rpc("match_documents", {
    query_embedding: queryVector,
    match_count: TOP_K,
    filter_type: null,
    max_sensitivity: "confidential",
  });

  if (rpcError) return NextResponse.json({ error: rpcError.message }, { status: 500 });

  // ── Step 3: Build context string from retrieved chunks ───────────────────
  const context = (chunks ?? [])
    .map(
      (c: {
        entity_type: string;
        entity_id: string;
        content: string;
        source_title?: string | null;
        source_url?: string | null;
        similarity: number;
      }) => {
        const label = c.source_title
          ? `${c.source_title} (${c.entity_type})`
          : `${c.entity_type} ${c.entity_id}`;
        return `[${label}] (similarity: ${c.similarity.toFixed(2)})\n${c.content}`;
      }
    )
    .join("\n\n---\n\n");

  // ── Step 4: Generate answer ───────────────────────────────────────────────
  const historyMessages = (messages as ChatCompletionMessageParam[]).slice(-10);

  const completion = await openrouter.chat.completions.create({
    model: DEFAULT_MODEL,
    messages: [
      { role: "system", content: SYSTEM_PROMPT } as ChatCompletionMessageParam,
      { role: "system", content: `Retrieved context:\n\n${context}` } as ChatCompletionMessageParam,
      ...historyMessages,
      { role: "user", content: query } as ChatCompletionMessageParam,
    ],
    temperature: 0.3,
  });

  const answer = completion.choices[0]?.message?.content ?? "";

  return NextResponse.json({
    answer,
    sources: (chunks ?? []).map(
      (c: {
        entity_type: string;
        entity_id: string;
        content: string;
        source_title?: string | null;
        source_url?: string | null;
        chunk_index?: number;
      }) => ({
        entity_type: c.entity_type,
        entity_id: c.entity_id,
        source_title: c.source_title ?? null,
        source_url: c.source_url ?? null,
        chunk_index: c.chunk_index ?? 0,
        snippet: c.content.slice(0, 120),
      })
    ),
  });
}
