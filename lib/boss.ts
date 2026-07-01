import PgBoss from "pg-boss";

// pg-boss needs a direct PostgreSQL connection string (not the Supabase REST URL).
// Set DATABASE_URL in .env to: postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
const DATABASE_URL = process.env.DATABASE_URL!;

let boss: PgBoss | null = null;

// Returns a singleton pg-boss instance.
// The first call starts pg-boss; subsequent calls reuse the running instance.
export async function getBoss(): Promise<PgBoss> {
  if (boss) return boss;

  boss = new PgBoss({
    connectionString: DATABASE_URL,
    // Retain completed jobs for 7 days for debugging.
    archiveCompletedAfterSeconds: 60 * 60 * 24 * 7,
    // Retry failed jobs up to 3 times with exponential back-off.
    retryLimit: 3,
    retryDelay: 30,
    retryBackoff: true,
  });

  await boss.start();
  return boss;
}

// Job queue names — centralised so typos are caught at compile time.
export const JOBS = {
  DOCTIFY_SCRAPE:    "doctify_scrape",
  WEBSITE_RESEARCH:  "website_research",
  LLM_EXTRACT:       "llm_extract",
  EMBED_DOCUMENT:    "embed_document",
} as const;
