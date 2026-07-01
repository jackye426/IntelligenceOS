import { load } from "cheerio";
import { Readability } from "@mozilla/readability";
import { JSDOM } from "jsdom";

// Maximum characters to keep per page — matches Python repo's MAX_TEXT_CHARS.
const MAX_CHARS = 12_000;

/**
 * Extracts clean readable text from an HTML string.
 * Tries @mozilla/readability first (article mode); falls back to
 * Cheerio body-text stripping for pages that aren't article-shaped.
 */
export function extractText(html: string, url: string): string {
  try {
    const dom = new JSDOM(html, { url });
    const reader = new Readability(dom.window.document);
    const article = reader.parse();
    if (article?.textContent) {
      return article.textContent.replace(/\s+/g, " ").trim().slice(0, MAX_CHARS);
    }
  } catch {
    // Readability can throw on malformed HTML — fall through to Cheerio.
  }

  // Cheerio fallback: strip scripts/styles and grab body text.
  const $ = load(html);
  $("script, style, noscript, nav, footer, header, [aria-hidden='true']").remove();
  const text = $("body").text().replace(/\s+/g, " ").trim();
  return text.slice(0, MAX_CHARS);
}

/**
 * Parses sitemap XML and returns all <loc> URLs found.
 * Handles both sitemap index files and regular sitemaps.
 */
export function parseSitemapUrls(xml: string): string[] {
  const $ = load(xml, { xmlMode: true });
  const urls: string[] = [];
  $("loc").each((_, el) => {
    const href = $(el).text().trim();
    if (href) urls.push(href);
  });
  return urls;
}
