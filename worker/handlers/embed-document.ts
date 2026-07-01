import { createHash } from "crypto";
import { supabase } from "@/lib/supabase";
import { openrouter } from "@/lib/openrouter";

const EMBEDDING_MODEL = process.env.OPENROUTER_EMBEDDING_MODEL ?? "openai/text-embedding-3-small";

export async function handleEmbedDocument(job: {
  data: {
    entity_type: string;
    entity_id: string;
    content: string;
    source_table?: string;
    source_title?: string;
    source_url?: string;
    sensitivity?: string;
    metadata?: Record<string, unknown>;
  };
}) {
  const {
    entity_type,
    entity_id,
    content,
    source_table,
    source_title,
    source_url,
    sensitivity = "internal",
    metadata = {},
  } = job.data;
  if (!content.trim()) return;

  console.log(`[embed] Embedding ${entity_type} ${entity_id}`);

  const embeddingRes = await openrouter.embeddings.create({
    model: EMBEDDING_MODEL,
    input: content.slice(0, 8000),
  });

  const vector = embeddingRes.data[0]?.embedding;
  if (!vector) throw new Error("No embedding returned");

  const chunkIndex = 0;
  const contentHash = createHash("sha256").update(content).digest("hex");

  const row = {
    entity_type,
    entity_id,
    content,
    embedding: vector as unknown as string,
    source_table: source_table ?? entity_type,
    source_title: source_title ?? null,
    source_url: source_url ?? null,
    chunk_index: chunkIndex,
    content_hash: contentHash,
    sensitivity,
    owner_scope: "docmap",
    metadata,
  };

  await supabase.from("document_embeddings").upsert(row, {
    onConflict: "entity_type,entity_id,chunk_index",
  });

  console.log(`[embed] Done: ${entity_type} ${entity_id}`);
}
