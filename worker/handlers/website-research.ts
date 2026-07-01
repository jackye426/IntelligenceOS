import { createHash } from "crypto";
import { supabase } from "@/lib/supabase";
import { getBoss, JOBS } from "@/lib/boss";
import { extractText, parseSitemapUrls } from "@/lib/extract-text";

const MAX_PAGES = 200;       // Max pages to fetch per research run.
const REQUEST_TIMEOUT = 15_000; // 15 s per page fetch.
const MAX_BYTES = 2_000_000;    // 2 MB HTML cap per page.

// Priority URL keywords — fetch these pages first (mirroring Python repo logic).
const PRIORITY_KEYWORDS = [
  "about", "team", "consultant", "practitioner", "doctor",
  "services", "treatments", "procedures", "conditions",
  "fees", "pricing", "cost", "contact", "referral",
];

// Pages to skip — low-signal noise pages.
const SKIP_PATTERNS = [
  "cookie", "privacy", "terms", "legal", "sitemap",
  "news", "blog", "press", "careers", "jobs",
];

/**
 * Validates the URL is safe to fetch:
 * - Must be HTTPS
 * - Must be on the allowed domain
 * - Must not resolve to a private/loopback IP (basic SSRF protection)
 */
function isAllowedUrl(url: string, allowedDomain: string): boolean {
  try {
    const parsed = new URL(url);
    if (parsed.protocol !== "https:") return false;
    if (parsed.hostname !== allowedDomain && !parsed.hostname.endsWith(`.${allowedDomain}`)) return false;
    // Block obviously private hostnames.
    if (/^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/.test(parsed.hostname)) return false;
    return true;
  } catch {
    return false;
  }
}

function shouldSkipUrl(url: string): boolean {
  const lower = url.toLowerCase();
  return SKIP_PATTERNS.some((p) => lower.includes(p));
}

function priorityScore(url: string): number {
  const lower = url.toLowerCase();
  return PRIORITY_KEYWORDS.filter((kw) => lower.includes(kw)).length;
}

/** Fetch with a timeout; returns null on error. */
async function safeFetch(url: string): Promise<Response | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
    const res = await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "DocMap-Research-Bot/1.0 (internal)" },
      redirect: "follow",
    });
    clearTimeout(timer);
    return res;
  } catch {
    return null;
  }
}

/** Extract all href links from an HTML page on the same domain. */
function extractLinks(html: string, baseUrl: string, allowedDomain: string): string[] {
  const urls: string[] = [];
  const hrefRegex = /href=["']([^"'#?]+)/g;
  let match;
  while ((match = hrefRegex.exec(html)) !== null) {
    try {
      const resolved = new URL(match[1], baseUrl).href;
      if (isAllowedUrl(resolved, allowedDomain) && !shouldSkipUrl(resolved)) {
        urls.push(resolved);
      }
    } catch { /* malformed href */ }
  }
  return Array.from(new Set(urls));
}

// ── Job handler ───────────────────────────────────────────────────────────────

export async function handleWebsiteResearch(job: {
  data: {
    run_id: string;
    account_id: string;
    website_url: string;
    allowed_domain: string;
  };
}) {
  const { run_id, account_id, website_url, allowed_domain } = job.data;

  const setStatus = async (status: string, error?: string) => {
    await supabase.from("clinic_research_runs").update({
      status,
      ...(error ? { error } : {}),
      ...(status === "fetching" ? { started_at: new Date().toISOString() } : {}),
      ...(["needs_review", "failed"].includes(status) ? { finished_at: new Date().toISOString() } : {}),
    }).eq("id", run_id);
  };

  try {
    await setStatus("fetching");

    // ── Step 1: Discover URLs via sitemap ──────────────────────────────────
    let urlsToFetch: string[] = [];

    const sitemapUrls = [
      `https://${allowed_domain}/sitemap.xml`,
      `https://${allowed_domain}/sitemap_index.xml`,
    ];

    for (const sitemapUrl of sitemapUrls) {
      const res = await safeFetch(sitemapUrl);
      if (res && res.ok) {
        const xml = await res.text();
        const found = parseSitemapUrls(xml).filter((u) => isAllowedUrl(u, allowed_domain) && !shouldSkipUrl(u));
        urlsToFetch.push(...found);
        // If sitemap_index, fetch sub-sitemaps too.
        if (xml.includes("<sitemapindex")) {
          for (const subUrl of found) {
            if (subUrl.endsWith(".xml")) {
              const subRes = await safeFetch(subUrl);
              if (subRes?.ok) {
                const subXml = await subRes.text();
                const subUrls = parseSitemapUrls(subXml).filter((u) => isAllowedUrl(u, allowed_domain) && !shouldSkipUrl(u));
                urlsToFetch.push(...subUrls);
              }
            }
          }
        }
        if (urlsToFetch.length > 0) break;
      }
    }

    // ── Step 2: Fallback to homepage crawl if no sitemap ──────────────────
    if (urlsToFetch.length === 0) {
      urlsToFetch = [website_url];
      const res = await safeFetch(website_url);
      if (res?.ok) {
        const html = await res.text();
        urlsToFetch.push(...extractLinks(html, website_url, allowed_domain));
      }
    }

    // Remove duplicates and cap.
    urlsToFetch = Array.from(new Set(urlsToFetch)).slice(0, MAX_PAGES);

    // Sort: priority pages first, then alphabetical.
    urlsToFetch.sort((a, b) => priorityScore(b) - priorityScore(a) || a.localeCompare(b));

    console.log(`[research] ${run_id}: fetching ${urlsToFetch.length} URLs for ${allowed_domain}`);

    // ── Step 3: Fetch each page and store as ClinicSource ─────────────────
    for (const pageUrl of urlsToFetch) {
      const res = await safeFetch(pageUrl);
      if (!res || !res.ok) continue;

      // Reject non-HTML responses (PDFs, images, etc.).
      const contentType = res.headers.get("content-type") ?? "";
      if (!contentType.includes("text/html") && !contentType.includes("text/plain")) continue;

      // Enforce size cap before reading.
      const contentLength = Number(res.headers.get("content-length") ?? 0);
      if (contentLength > MAX_BYTES) continue;

      const html = await res.text();
      if (html.length > MAX_BYTES) continue;

      const rawText = extractText(html, pageUrl);
      if (rawText.length < 50) continue; // skip empty / near-empty pages

      // Derive a title from the HTML <title> tag.
      const titleMatch = html.match(/<title[^>]*>([^<]+)<\/title>/i);
      const title = titleMatch?.[1]?.trim() || new URL(pageUrl).pathname || pageUrl;

      // Deduplicate by content hash — don't store the same page twice.
      const contentHash = createHash("sha256").update(rawText).digest("hex").slice(0, 64);
      const { data: existing } = await supabase
        .from("clinic_sources")
        .select("id")
        .eq("clinic_account_id", account_id)
        .eq("content_hash", contentHash)
        .limit(1)
        .single();

      if (existing) continue;

      await supabase.from("clinic_sources").insert({
        clinic_account_id: account_id,
        type: "website_page",
        url: pageUrl,
        title,
        raw_text: rawText,
        content_hash: contentHash,
        approved_for_use: true,
      });

      // Polite delay.
      await new Promise((r) => setTimeout(r, 500));
    }

    // ── Step 4: Mark run as extracting, queue LLM extraction ─────────────
    await setStatus("extracting");

    const boss = await getBoss();
    await boss.send(JOBS.LLM_EXTRACT, { run_id, account_id });

    console.log(`[research] ${run_id}: done fetching, LLM extraction queued.`);
  } catch (err) {
    console.error(`[research] ${run_id}:`, err);
    await setStatus("failed", String(err));
  }
}
