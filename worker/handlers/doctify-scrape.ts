import { chromium, type Browser, type Page, type Request as PWRequest } from "playwright";
import { supabase } from "@/lib/supabase";
import { getBoss, JOBS } from "@/lib/boss";

// Semaphore to cap concurrent Playwright browsers.
const MAX_CONCURRENT = 4;
let activeBrowsers = 0;

async function waitForSlot(): Promise<void> {
  while (activeBrowsers >= MAX_CONCURRENT) {
    await new Promise((r) => setTimeout(r, 500));
  }
}

interface DoctifyClinic {
  clinic_name: string;
  doctify_url: string;
  website_url: string | null;
  location: string | null;
  specialty_tags: string[];
  specialist_count: number | null;
  review_count: number | null;
  raw_json: Record<string, unknown>;
}

/**
 * Intercepts Doctify's internal JSON API to extract clinic cards.
 * Doctify is a React SPA — the structured data comes through XHR/fetch
 * calls rather than server-rendered HTML. We capture those responses.
 */
async function interceptDoctifyPage(page: Page, url: string): Promise<DoctifyClinic[]> {
  const clinics: DoctifyClinic[] = [];
  const intercepted: Record<string, unknown>[] = [];

  // Capture JSON API responses from Doctify's backend.
  page.on("response", async (response) => {
    const resUrl = response.url();
    if (!resUrl.includes("api.doctify.com") && !resUrl.includes("doctify.com/api")) return;
    try {
      const json = await response.json();
      intercepted.push(json);
    } catch {
      // Not JSON or empty — skip.
    }
  });

  await page.goto(url, { waitUntil: "networkidle", timeout: 30_000 });

  // Give XHR responses a moment to be captured.
  await page.waitForTimeout(2000);

  // Try to extract from intercepted API responses first.
  for (const json of intercepted) {
    const extracted = extractFromApiResponse(json);
    clinics.push(...extracted);
  }

  // If API interception got nothing, fall back to DOM scraping.
  if (clinics.length === 0) {
    const domClinics = await extractFromDom(page);
    clinics.push(...domClinics);
  }

  return clinics;
}

/** Parse Doctify's clinic listing API response shape. */
function extractFromApiResponse(json: Record<string, unknown>): DoctifyClinic[] {
  const results: DoctifyClinic[] = [];

  // Doctify returns listings under various keys depending on the endpoint.
  const items = (
    (json?.data as unknown[]) ??
    (json?.results as unknown[]) ??
    (json?.practices as unknown[]) ??
    (json?.clinics as unknown[]) ??
    []
  ) as Record<string, unknown>[];

  for (const item of items) {
    if (!item?.name && !item?.practice_name) continue;

    const name = String(item.name ?? item.practice_name ?? "");
    const slug = String(item.slug ?? item.url_slug ?? "");
    const website = extractWebsite(item);

    results.push({
      clinic_name: name,
      doctify_url: slug ? `https://www.doctify.com/uk/${slug}` : "",
      website_url: website,
      location: String(item.city ?? item.location ?? item.address ?? ""),
      specialty_tags: extractTags(item),
      specialist_count: Number(item.practitioners_count ?? item.specialist_count ?? 0) || null,
      review_count: Number(item.reviews_count ?? item.review_count ?? 0) || null,
      raw_json: item,
    });
  }

  return results;
}

/** DOM fallback: scrape clinic cards directly from the rendered page. */
async function extractFromDom(page: Page): Promise<DoctifyClinic[]> {
  return page.evaluate(() => {
    const cards = document.querySelectorAll("[class*='practice'], [class*='clinic'], [data-testid*='result']");
    const results: DoctifyClinic[] = [];

    cards.forEach((card) => {
      const nameEl = card.querySelector("h2, h3, [class*='name'], [class*='title']");
      const name = nameEl?.textContent?.trim();
      if (!name) return;

      const link = card.querySelector("a");
      const href = link?.getAttribute("href") ?? "";
      const websiteLink = Array.from(card.querySelectorAll("a")).find(
        (a) => a.href.includes("http") && !a.href.includes("doctify.com")
      );

      results.push({
        clinic_name: name,
        doctify_url: href.startsWith("http") ? href : `https://www.doctify.com${href}`,
        website_url: websiteLink?.href ?? null,
        location: card.querySelector("[class*='location'], [class*='address']")?.textContent?.trim() ?? null,
        specialty_tags: [],
        specialist_count: null,
        review_count: null,
        raw_json: { source: "dom_fallback" },
      });
    });

    return results;
  });
}

function extractWebsite(item: Record<string, unknown>): string | null {
  const w = item.website_url ?? item.website ?? item.url;
  if (typeof w === "string" && w.startsWith("http") && !w.includes("doctify")) return w;
  return null;
}

function extractTags(item: Record<string, unknown>): string[] {
  const raw = item.specialties ?? item.specialty_tags ?? item.categories ?? [];
  if (!Array.isArray(raw)) return [];
  return raw.map((t) => String((t as Record<string, unknown>)?.name ?? t)).filter(Boolean);
}

/**
 * Handles pagination: follows "next page" links up to 50 pages per listing URL.
 * Doctify uses either URL query params (?page=2) or JS-rendered pagination.
 */
async function scrapeAllPages(browser: Browser, startUrl: string): Promise<DoctifyClinic[]> {
  const allClinics: DoctifyClinic[] = [];
  const MAX_PAGES = 50;
  let currentUrl: string | null = startUrl;
  let pageIndex = 1;

  while (currentUrl && pageIndex <= MAX_PAGES) {
    const page = await browser.newPage();
    try {
      const clinics = await interceptDoctifyPage(page, currentUrl);
      if (clinics.length === 0) break; // no more results
      allClinics.push(...clinics);

      // Try to find a "next page" link.
      currentUrl = await page.evaluate((idx) => {
        const next = document.querySelector(`a[href*="page=${idx + 1}"], [aria-label="Next page"] a, [rel="next"]`);
        return (next as HTMLAnchorElement)?.href ?? null;
      }, pageIndex);
    } finally {
      await page.close();
    }
    pageIndex++;
    // Polite delay between pages.
    await new Promise((r) => setTimeout(r, 1500));
  }

  return allClinics;
}

// ── Job handler ───────────────────────────────────────────────────────────────

export async function handleDoctifyScrape(job: { data: { doctify_url: string } }) {
  const { doctify_url } = job.data;
  console.log(`[doctify] Starting scrape: ${doctify_url}`);

  await waitForSlot();
  activeBrowsers++;
  const browser = await chromium.launch({ headless: true });

  try {
    const clinics = await scrapeAllPages(browser, doctify_url);
    console.log(`[doctify] Found ${clinics.length} clinics`);

    const boss = await getBoss();

    for (const clinic of clinics) {
      if (!clinic.clinic_name || !clinic.doctify_url) continue;

      // Upsert into doctify_profiles (unique on doctify_url).
      const { data: profile } = await supabase
        .from("doctify_profiles")
        .upsert(
          {
            clinic_name: clinic.clinic_name,
            doctify_url: clinic.doctify_url,
            website_url: clinic.website_url,
            location: clinic.location,
            specialty_tags: clinic.specialty_tags,
            specialist_count: clinic.specialist_count,
            review_count: clinic.review_count,
            raw_json: clinic.raw_json,
          },
          { onConflict: "doctify_url" }
        )
        .select("id, website_url")
        .single();

      // If this clinic has a website URL, create an account and queue research.
      if (profile?.website_url) {
        // Create a clinic account if one doesn't exist for this domain.
        const hostname = new URL(profile.website_url).hostname;
        const { data: existing } = await supabase
          .from("clinic_accounts")
          .select("id")
          .ilike("website_url", `%${hostname}%`)
          .is("deleted_at", null)
          .limit(1)
          .single();

        let accountId = existing?.id;

        if (!accountId) {
          const { data: newAccount } = await supabase
            .from("clinic_accounts")
            .insert({
              name: clinic.clinic_name,
              website_url: profile.website_url,
              owner_user: "system",
              pipeline_stage: "Identified",
            })
            .select("id")
            .single();
          accountId = newAccount?.id;

          if (accountId) {
            // Link Doctify profile to the new account.
            await supabase.from("doctify_profiles").update({ clinic_account_id: accountId }).eq("id", profile.id);

            // Queue website research.
            const allowed_domain = hostname;
            const { data: run } = await supabase
              .from("clinic_research_runs")
              .insert({
                clinic_account_id: accountId,
                submitted_url: profile.website_url,
                allowed_domain,
                status: "queued",
              })
              .select("id")
              .single();

            if (run) {
              await boss.send(JOBS.WEBSITE_RESEARCH, {
                run_id: run.id,
                account_id: accountId,
                website_url: profile.website_url,
                allowed_domain,
              });
            }
          }
        }
      }
    }

    console.log(`[doctify] Done. Processed ${clinics.length} profiles.`);
  } finally {
    await browser.close();
    activeBrowsers--;
  }
}
