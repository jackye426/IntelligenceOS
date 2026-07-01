"""
Per-review analyser with parallel clinic processing.

Flow per clinic:
  1. Batch reviews (50 per call) → LLM labels each: {category, sub, severity}
  2. Count labels ourselves → real percentages
  3. Pull top quotes directly from labelled reviews
  4. One final call to generate a 2-sentence summary from the aggregated labels

Parallel: ThreadPoolExecutor processes multiple clinics simultaneously.
Cache: hash-based so re-runs only process new/changed clinics.
"""
import json, os, hashlib, time
from pathlib import Path
from slugify import slugify
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(__file__).parent / ".env")

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

LABEL_CACHE = DATA_DIR / "review_label_cache.json"
MODEL = "deepseek/deepseek-chat-v3-0324"
BATCH_SIZE = 50
MAX_WORKERS = 5

# ── Fixed taxonomy ────────────────────────────────────────────────────────
CATEGORIES = [
    "Communication",
    "Waiting Times",
    "Value for Money",
    "Treatment Quality",
    "Booking & Admin",
    "Staff Attitude",
    "Facilities",
    "Doctor / Consultant",
    "Billing & Invoicing",
    "Other",
]

CATEGORY_LIST = "\n".join(f"  - {c}" for c in CATEGORIES)

LABEL_INSTRUCTIONS = f"""Label each patient review with:
- category: exactly one of:
{CATEGORY_LIST}
  (For "Other" also add a sub field with a short specific label, e.g. "Other: Parking")
- severity: high | medium | low
- key_phrase: a short verbatim phrase (max 12 words) from the review that best captures the complaint

Return a JSON array with one object per review, in the same order as input.
Example: [{{"category":"Communication","severity":"high","key_phrase":"never responded to any of my emails"}}]"""


def _client():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set.")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)


def _review_hash(clinic, text):
    return hashlib.md5(f"{clinic}||{text[:300]}".encode()).hexdigest()


def _load_label_cache():
    if LABEL_CACHE.exists():
        return json.loads(LABEL_CACHE.read_text(encoding="utf-8"))
    return {}


def _save_label_cache(cache):
    LABEL_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def _label_batch(client, clinic_name, batch, cache):
    """Label a batch of reviews. Checks cache first; only calls API for uncached ones."""
    results = [None] * len(batch)
    uncached_idxs = []
    uncached_reviews = []

    for i, r in enumerate(batch):
        h = _review_hash(clinic_name, r["text"])
        if h in cache:
            results[i] = cache[h]
        else:
            uncached_idxs.append(i)
            uncached_reviews.append(r)

    if not uncached_reviews:
        return results

    numbered = "\n\n".join(
        f"[{i+1}] {r['text'][:500]}" for i, r in enumerate(uncached_reviews)
    )
    prompt = f"{LABEL_INSTRUCTIONS}\n\nClinic: {clinic_name}\n\nReviews:\n{numbered}"

    resp = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Return only a valid JSON array, no markdown."},
            {"role": "user", "content": prompt},
        ],
        max_tokens=2000,
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    labels = json.loads(text)
    # Tolerate off-by-one from the LLM — truncate if too many, pad if slightly short
    if abs(len(labels) - len(uncached_reviews)) > 3:
        raise ValueError(f"Got {len(labels)} labels for {len(uncached_reviews)} reviews")
    if len(labels) > len(uncached_reviews):
        labels = labels[:len(uncached_reviews)]
    elif len(labels) < len(uncached_reviews):
        labels += [{"category": "Other", "severity": "medium", "key_phrase": ""}] * (len(uncached_reviews) - len(labels))

    for idx, label, rev in zip(uncached_idxs, labels, uncached_reviews):
        results[idx] = label
        cache[_review_hash(clinic_name, rev["text"])] = label

    return results


def _summarise(client, clinic_name, category_counts, total):
    """One short LLM call to write a 2-sentence plain-English summary."""
    top = sorted(category_counts.items(), key=lambda x: -x[1])[:5]
    lines = ", ".join(f"{cat} ({n} reviews, {round(n/total*100)}%)" for cat, n in top)
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": (
            f"Write a 2-sentence plain-English summary of patient dissatisfaction at "
            f"{clinic_name} based on these complaint counts: {lines}. "
            f"Total negative reviews: {total}. Return only the summary."
        )}],
        max_tokens=200,
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()


def analyze_clinic(clinic_data, refresh=False):
    """Analyse one clinic. Returns structured result with real label counts."""
    clinic_name = clinic_data.get("clinic", "Unknown")
    reviews = [r for r in clinic_data.get("reviews", []) if r.get("text", "").strip()]

    slug = slugify(clinic_name)
    cache_file = DATA_DIR / f"{slug}_analysis.json"

    if cache_file.exists() and not refresh:
        print(f"  [cache] {clinic_name}")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    if not reviews:
        result = {"clinic": clinic_name, "review_count": 0, "categories": [],
                  "summary": "No negative reviews available."}
        cache_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return result

    print(f"  [analyse] {clinic_name} ({len(reviews)} reviews)")
    client = _client()
    label_cache = _load_label_cache()

    # Label every review in batches of BATCH_SIZE
    all_labels = []
    for start in range(0, len(reviews), BATCH_SIZE):
        batch = reviews[start:start + BATCH_SIZE]
        try:
            labels = _label_batch(client, clinic_name, batch, label_cache)
            all_labels.extend(labels)
        except Exception as e:
            print(f"    [warn] batch failed for {clinic_name}: {e}")
            all_labels.extend([None] * len(batch))

    _save_label_cache(label_cache)

    # Aggregate counts from labels
    cat_counts: dict[str, int] = {}
    cat_quotes: dict[str, list] = {}
    cat_severity: dict[str, list] = {}

    for review, label in zip(reviews, all_labels):
        if not label:
            continue
        cat = label.get("category", "Other")
        cat_counts[cat] = cat_counts.get(cat, 0) + 1
        cat_quotes.setdefault(cat, [])
        if len(cat_quotes[cat]) < 3 and label.get("key_phrase"):
            cat_quotes[cat].append(label["key_phrase"])
        cat_severity.setdefault(cat, [])
        cat_severity[cat].append(label.get("severity", "medium"))

    def dominant_severity(sevs):
        for s in ("high", "medium", "low"):
            if sevs.count(s) >= len(sevs) / 2:
                return s
        return "medium"

    total = len(reviews)
    categories = sorted(
        [
            {
                "name": cat,
                "count": count,
                "pct": round(count / total * 100, 1),
                "severity": dominant_severity(cat_severity.get(cat, ["medium"])),
                "quotes": cat_quotes.get(cat, []),
            }
            for cat, count in cat_counts.items()
        ],
        key=lambda x: -x["count"],
    )

    summary = _summarise(client, clinic_name, cat_counts, total)

    result = {"clinic": clinic_name, "review_count": total,
              "categories": categories, "summary": summary}
    cache_file.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [done] {clinic_name}: {len(categories)} categories from {total} labelled reviews")
    return result


def analyze_all(clinics_data, refresh=False):
    """Process all clinics in parallel using a thread pool."""
    results = {}
    active = [d for d in clinics_data if d.get("total_negative", 0) > 0]
    empty = [d for d in clinics_data if d.get("total_negative", 0) == 0]

    # Empty clinics — return stub immediately
    for d in empty:
        results[d["clinic"]] = {"clinic": d["clinic"], "review_count": 0,
                                 "categories": [], "summary": "No negative reviews."}

    print(f"Processing {len(active)} clinics with {MAX_WORKERS} parallel workers...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {pool.submit(analyze_clinic, d, refresh): d["clinic"] for d in active}
        for future in as_completed(futures):
            name = futures[future]
            try:
                results[name] = future.result()
            except Exception as e:
                print(f"  [error] {name}: {e}")
                results[name] = {"clinic": name, "review_count": 0, "categories": [],
                                  "summary": f"Analysis failed: {e}"}

    # Return in original order
    name_order = [d["clinic"] for d in clinics_data]
    return [results[n] for n in name_order if n in results]


def analyze_cross_clinic(all_analyses):
    """Identify themes common across multiple clinics."""
    active = [a for a in all_analyses if a.get("review_count", 0) > 0]
    if not active:
        return {"top_themes": [], "overall_summary": "No data available."}

    client = _client()
    summaries = "\n\n".join(
        f"**{a['clinic']}** ({a['review_count']} reviews)\n"
        f"Top: {', '.join(c['name'] for c in a['categories'][:4])}"
        for a in active
    )

    resp = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": "Patient experience analyst. Return only valid JSON."},
            {"role": "user", "content": (
                "Identify the top recurring themes across these London gynaecology and fertility clinics.\n\n"
                f"{summaries}\n\n"
                "Return JSON:\n"
                '{"top_themes":[{"name":"...","affected_clinics":["..."],"prevalence":"high|medium|low",'
                '"description":"..."}],'
                '"overall_summary":"3-4 sentence executive summary"}'
            )},
        ],
        max_tokens=2000,
        temperature=0.2,
    )
    return _parse_json(resp.choices[0].message.content)


def _parse_json(text):
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        s, e = text.find("{"), text.rfind("}") + 1
        if s >= 0 and e > s:
            try:
                return json.loads(text[s:e])
            except Exception:
                pass
    return {"categories": [], "summary": "Parsing failed.", "top_themes": []}
