import OpenAI from "openai";

// OpenRouter is API-compatible with the OpenAI SDK.
// Point the base URL at OpenRouter and set the API key.
export const openrouter = new OpenAI({
  baseURL: "https://openrouter.ai/api/v1",
  apiKey: process.env.OPENROUTER_API_KEY!,
  defaultHeaders: {
    // OpenRouter requires a site URL and title for attribution.
    "HTTP-Referer": "https://docmap.co",
    "X-Title": "DocMap Intelligence OS",
  },
});

// Default model — overridden per-call when needed.
// Set OPENROUTER_MODEL in .env to change globally.
export const DEFAULT_MODEL =
  process.env.OPENROUTER_MODEL ?? "openai/gpt-4o-mini";

// Cheap model used for the judge pass and embeddings.
export const JUDGE_MODEL =
  process.env.OPENROUTER_JUDGE_MODEL ?? "openai/gpt-4o-mini";
