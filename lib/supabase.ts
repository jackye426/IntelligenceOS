import { createClient } from "@supabase/supabase-js";

const url = process.env.NEXT_PUBLIC_SUPABASE_URL!;
const key = process.env.SUPABASE_KEY!;

// Service-role client — never exposed to the browser.
// Used in API routes and server components only.
// The Database generic is intentionally omitted here: Supabase's complex
// generic inference conflicts with our hand-authored types. Response types
// are asserted explicitly at each call site using the types in types/database.ts.
export const supabase = createClient(url, key);
