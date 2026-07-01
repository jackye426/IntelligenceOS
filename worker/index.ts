/**
 * DocMap Intelligence OS — Background Worker
 *
 * Boots pg-boss and registers handlers for all job types.
 * Run with: npm run worker
 *
 * This process is separate from the Next.js dev server.
 * Both must be running for ingestion pipelines to execute.
 */

import "dotenv/config";
import PgBoss from "pg-boss";
import { getBoss, JOBS } from "@/lib/boss";
import { handleDoctifyScrape } from "./handlers/doctify-scrape";
import { handleWebsiteResearch } from "./handlers/website-research";
import { handleLlmExtract } from "./handlers/llm-extract";
import { handleEmbedDocument } from "./handlers/embed-document";

// pg-boss v10 WorkHandler receives Job<T>[] (an array, even for single jobs).
// This wrapper maps single-job handlers into the v10 signature.
function wrap<T>(fn: (job: { data: T }) => Promise<void>) {
  return async (jobs: PgBoss.Job<T>[]) => {
    await Promise.all(jobs.map(fn));
  };
}

async function main() {
  console.log("[worker] Starting DocMap Intelligence OS worker…");

  const boss = await getBoss();

  // Register job handlers.
  // Each handler receives the job object; pg-boss handles retries and failures.
  await boss.work(JOBS.DOCTIFY_SCRAPE,   wrap(handleDoctifyScrape));
  await boss.work(JOBS.WEBSITE_RESEARCH, wrap(handleWebsiteResearch));
  await boss.work(JOBS.LLM_EXTRACT,      wrap(handleLlmExtract));
  await boss.work(JOBS.EMBED_DOCUMENT,   wrap(handleEmbedDocument));

  console.log("[worker] Registered handlers:");
  console.log(`  - ${JOBS.DOCTIFY_SCRAPE}   (2 concurrent)`);
  console.log(`  - ${JOBS.WEBSITE_RESEARCH} (4 concurrent)`);
  console.log(`  - ${JOBS.LLM_EXTRACT}      (2 concurrent)`);
  console.log(`  - ${JOBS.EMBED_DOCUMENT}   (4 concurrent)`);
  console.log("[worker] Ready. Waiting for jobs…");

  // Keep the process alive.
  process.on("SIGTERM", async () => {
    console.log("[worker] Shutting down…");
    await boss.stop();
    process.exit(0);
  });

  process.on("SIGINT", async () => {
    console.log("[worker] Shutting down…");
    await boss.stop();
    process.exit(0);
  });
}

main().catch((err) => {
  console.error("[worker] Fatal error:", err);
  process.exit(1);
});
