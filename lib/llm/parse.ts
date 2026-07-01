/**
 * Robustly parses JSON from an LLM response.
 * Handles markdown code fences (```json ... ```) and leading/trailing whitespace.
 * Mirrors the _parse_json function from the Python repo's llm_enrichment.py.
 */
export function parseLlmJson<T = unknown>(text: string): T {
  // Strip markdown code fences if present.
  const fenceMatch = text.match(/```(?:json)?\s*([\s\S]+?)\s*```/);
  const clean = (fenceMatch?.[1] ?? text).trim();
  return JSON.parse(clean) as T;
}
