"""
Product Opportunity Discovery Classifier

Classifies every review with a rich multi-dimension label designed to surface
product opportunities, not just complaint categories.

Usage:
    python opportunity_classify.py              # classify all 1,145 reviews
    python opportunity_classify.py --validate   # gold-standard sample of 100 first
    python opportunity_classify.py --aggregate  # skip classification, just re-aggregate
"""
import argparse
import hashlib
import json
import os
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from slugify import slugify

load_dotenv(Path(".env"))

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

LABEL_CACHE   = DATA_DIR / "opportunity_label_cache.json"
REVIEWS_OUT   = DATA_DIR / "opportunity_classified_reviews.json"
SUMMARY_OUT   = DATA_DIR / "opportunity_summary.json"
DEEPDIVE_OUT  = DATA_DIR / "opportunity_deepdives.json"

MODEL  = "deepseek/deepseek-chat-v3-0324"
BATCH  = 15

# ── Taxonomy definitions ─────────────────────────────────────────────────

PRIMARY_LABELS = [
    "inbound_access",
    "appointment_management",
    "pre_visit_information",
    "treatment_coordination",
    "results_delivery",
    "post_treatment_followup",
    "complaint_handling",
    "admin_records",
    "financial_transparency",
    "not_automatable",
]

PATIENT_STAGES = [
    "pre_enquiry", "enquiry", "booking", "pre_visit",
    "consultation", "treatment", "post_treatment", "complaint", "billing",
]

AUTOMATION_TIERS = [
    "bot_solvable", "workflow_solvable", "human_assisted",
    "insight_only", "not_solvable",
]

PRODUCT_SURFACE_MAP = {
    "inbound_access":         "inbound_manager",
    "pre_visit_information":  "inbound_manager",
    "appointment_management": "booking_ops_layer",
    "admin_records":          "booking_ops_layer",
    "treatment_coordination": "patient_pathway_coordinator",
    "results_delivery":       "patient_pathway_coordinator",
    "post_treatment_followup":"patient_pathway_coordinator",
    "financial_transparency": "financial_consent_flow",
    "complaint_handling":     "complaint_triage_monitor",
    "not_automatable":        "out_of_scope",
}

SYSTEM_PROMPT = """You are a product strategist analysing negative patient reviews for a healthcare AI company.
Your job is to classify each review to identify where private clinics are failing operationally,
and what product would have prevented the failure.
Return only valid JSON arrays — no markdown, no explanation."""

LABEL_INSTRUCTIONS = f"""Classify each review with this JSON schema (one object per review):

PRIMARY LABEL — pick exactly one:
  inbound_access         : phone unanswered, email ignored, no reply to messages, can't get through
  appointment_management : booking errors, cancellations, wrong dates, no confirmation, rescheduling failures
  pre_visit_information  : cost/pricing questions, service fit, treatment options — before committing
  treatment_coordination : mid-treatment: no next steps, medication confusion, cycle updates, protocol unclear
  results_delivery       : test/scan results not proactively shared, patient chasing for results
  post_treatment_followup: no aftercare, no check-in after procedure, no discharge guidance
  complaint_handling     : complaint ignored, stonewalled, or got defensive non-response
  admin_records          : lost records, wrong DOB, can't find appointment, data errors
  financial_transparency : surprise charges, quoted one price charged another, hidden add-ons
  not_automatable        : clinical quality, treatment outcomes, staff personality, facilities

SECONDARY LABELS — list 0–2 additional labels from the same set that also apply
PATIENT STAGE — one of: pre_enquiry | enquiry | booking | pre_visit | consultation | treatment | post_treatment | complaint | billing
AUTOMATION TIER — one of:
  bot_solvable      : chatbot handles it directly
  workflow_solvable : needs task management, escalation, or staff handoff
  human_assisted    : AI prepares/routes/summarises but human must act
  insight_only      : useful for clinic intelligence, not directly actionable
  not_solvable      : clinical quality, bad outcome, facilities
ROOT CAUSE — short phrase describing the underlying operational failure (e.g. "no ownership", "no proactive update", "no response SLA")
PRODUCT SURFACE — one of: inbound_manager | booking_ops_layer | patient_pathway_coordinator | financial_consent_flow | complaint_triage_monitor | clinic_intelligence | out_of_scope
SEVERITY — int 1–5 (5 = patient harmed or extremely distressed)
COMMERCIAL RELEVANCE — int 1–5 (5 = directly causes lost bookings, refunds, or reputation damage)
EVIDENCE QUOTE — short verbatim phrase (max 15 words) from the review

Return a JSON array with one object per review, in order:
[{{"primary_label":"...","secondary_labels":["..."],"patient_stage":"...","automation_tier":"...","root_cause":"...","product_surface":"...","severity":4,"commercial_relevance":4,"evidence_quote":"..."}}]"""


def _client():
    key = os.environ.get("OPENROUTER_API_KEY")
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set.")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=key)


def _hash(clinic, text):
    return hashlib.md5(f"{clinic}||{text[:300]}".encode()).hexdigest()


def _load_cache():
    return json.loads(LABEL_CACHE.read_text(encoding="utf-8")) if LABEL_CACHE.exists() else {}


def _save_cache(cache):
    LABEL_CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")


def load_all_reviews():
    """Load every review from every clinic's scraped JSON."""
    sample = json.loads(Path("gynae_sample.json").read_text())
    reviews = []
    for c in sample:
        slug = slugify(c["name"])
        f = DATA_DIR / f"{slug}.json"
        if not f.exists():
            continue
        for r in json.loads(f.read_text(encoding="utf-8")).get("reviews", []):
            if r.get("text", "").strip():
                reviews.append({
                    "id": _hash(c["name"], r["text"]),
                    "clinic": c["name"],
                    "rating": r["rating"],
                    "text": r["text"],
                    "label": None,
                })
    return reviews


def classify_batch(client, batch, cache):
    """Classify a batch; check cache first, call API only for uncached reviews."""
    results = [None] * len(batch)
    uncached_idxs, uncached = [], []

    for i, r in enumerate(batch):
        if r["id"] in cache:
            results[i] = cache[r["id"]]
        else:
            uncached_idxs.append(i)
            uncached.append(r)

    if not uncached:
        return results

    numbered = "\n\n".join(
        f"[{i+1}] ({r['clinic']}, {r['rating']}*)\n{r['text'][:500]}"
        for i, r in enumerate(uncached)
    )
    prompt = f"{LABEL_INSTRUCTIONS}\n\nReviews:\n{numbered}"

    resp = _client().chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        max_tokens=4000,
        temperature=0,
    )
    text = resp.choices[0].message.content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    labels = json.loads(text)
    if abs(len(labels) - len(uncached)) > 3:
        raise ValueError(f"Got {len(labels)} labels for {len(uncached)} reviews")
    if len(labels) > len(uncached):
        labels = labels[:len(uncached)]
    elif len(labels) < len(uncached):
        labels += [{"primary_label": "not_automatable", "secondary_labels": [],
                    "patient_stage": "unclear", "automation_tier": "not_solvable",
                    "root_cause": "unknown", "product_surface": "out_of_scope",
                    "severity": 1, "commercial_relevance": 1,
                    "evidence_quote": ""}] * (len(uncached) - len(labels))

    for i, label, rev in zip(uncached_idxs, labels, uncached):
        results[i] = label
        cache[rev["id"]] = label

    return results


def run_classification(reviews, validate_only=False):
    """Classify reviews sequentially (no thread pool — no cache race condition)."""
    cache = _load_cache()

    to_classify = [r for r in reviews if r["id"] not in cache]
    already_done = len(reviews) - len(to_classify)

    if validate_only:
        # Sample 100 uncached reviews for gold-standard check
        random.seed(42)
        to_classify = random.sample(to_classify, min(100, len(to_classify)))
        print(f"Gold-standard validation: classifying {len(to_classify)} sample reviews")
    else:
        print(f"Total reviews:       {len(reviews)}")
        print(f"Already cached:      {already_done}")
        print(f"To classify:         {len(to_classify)}")

    total_batches = -(-len(to_classify) // BATCH)  # ceiling division
    client = _client()
    classified = 0
    skipped = 0

    for start in range(0, len(to_classify), BATCH):
        batch_reviews = to_classify[start:start + BATCH]
        batch_num = start // BATCH + 1
        try:
            labels = classify_batch(client, batch_reviews, cache)
            for rev, label in zip(batch_reviews, labels):
                rev["label"] = label
            classified += len(batch_reviews)
            print(f"  batch {batch_num}/{total_batches}: {len(batch_reviews)} classified", flush=True)
            _save_cache(cache)
        except Exception as e:
            print(f"  batch {batch_num}/{total_batches}: FAILED — {e}")
            skipped += len(batch_reviews)
            time.sleep(1)

    # Apply cached labels to all reviews
    for rev in reviews:
        if rev["label"] is None and rev["id"] in cache:
            rev["label"] = cache[rev["id"]]

    labelled = [r for r in reviews if r.get("label")]
    print(f"\nLabelled: {len(labelled)} / {len(reviews)}")
    return reviews


def aggregate(reviews):
    """Compute opportunity summary from labelled reviews."""
    labelled = [r for r in reviews if r.get("label")]
    total = len(labelled)

    primary_counts   = Counter(r["label"]["primary_label"]  for r in labelled)
    stage_counts     = Counter(r["label"]["patient_stage"]   for r in labelled)
    tier_counts      = Counter(r["label"]["automation_tier"] for r in labelled)
    surface_counts   = Counter(r["label"]["product_surface"] for r in labelled)

    # Secondary labels (ownership gap detection)
    secondary_flat = []
    ownership_gap_reviews = []
    for r in labelled:
        for sl in r["label"].get("secondary_labels", []):
            secondary_flat.append(sl)
        rc = r["label"].get("root_cause", "").lower()
        if any(kw in rc for kw in ["ownership", "no one", "passed", "chasing", "no sla", "no follow"]):
            ownership_gap_reviews.append(r)

    # Per-product-surface aggregation
    surfaces = defaultdict(lambda: {
        "reviews": [], "primary_labels": Counter(),
        "stages": Counter(), "tiers": Counter(),
        "severity_sum": 0, "commercial_sum": 0,
        "root_causes": Counter(), "quotes": [],
    })
    for r in labelled:
        ps = r["label"].get("product_surface", "out_of_scope")
        surfaces[ps]["reviews"].append(r)
        surfaces[ps]["primary_labels"][r["label"]["primary_label"]] += 1
        surfaces[ps]["stages"][r["label"]["patient_stage"]] += 1
        surfaces[ps]["tiers"][r["label"]["automation_tier"]] += 1
        surfaces[ps]["severity_sum"] += r["label"].get("severity", 3)
        surfaces[ps]["commercial_sum"] += r["label"].get("commercial_relevance", 3)
        rc = r["label"].get("root_cause", "")
        if rc:
            surfaces[ps]["root_causes"][rc] += 1
        eq = r["label"].get("evidence_quote", "")
        if eq and len(surfaces[ps]["quotes"]) < 5:
            surfaces[ps]["quotes"].append({"clinic": r["clinic"], "quote": eq})

    def tier_score(tier_counter):
        scores = {"bot_solvable": 5, "workflow_solvable": 4, "human_assisted": 3,
                  "insight_only": 2, "not_solvable": 0}
        total_t = sum(tier_counter.values())
        if not total_t: return 0
        return round(sum(scores.get(t, 0) * n for t, n in tier_counter.items()) / total_t, 1)

    def freq_score(count, total):
        pct = count / total * 100
        if pct >= 20: return 5
        if pct >= 12: return 4
        if pct >= 7:  return 3
        if pct >= 3:  return 2
        return 1

    surface_summaries = []
    for surface_name, data in surfaces.items():
        count = len(data["reviews"])
        if count == 0: continue
        avg_sev  = round(data["severity_sum"] / count, 1)
        avg_comm = round(data["commercial_sum"] / count, 1)
        t_score  = tier_score(data["tiers"])
        f_score  = freq_score(count, total)
        stage_spread = len([s for s, n in data["stages"].items() if n >= 2])

        must_have = round(f_score + avg_sev + avg_comm + t_score + stage_spread, 1)

        surface_summaries.append({
            "product_surface": surface_name,
            "count": count,
            "pct": round(count / total * 100, 1),
            "must_have_score": must_have,
            "avg_severity": avg_sev,
            "avg_commercial_relevance": avg_comm,
            "automation_tier_score": t_score,
            "stage_spread": stage_spread,
            "top_primary_labels": [
                {"label": l, "count": n}
                for l, n in data["primary_labels"].most_common(3)
            ],
            "top_stages": [
                {"stage": s, "count": n}
                for s, n in data["stages"].most_common(3)
            ],
            "top_root_causes": [
                {"cause": c, "count": n}
                for c, n in data["root_causes"].most_common(5)
            ],
            "quotes": data["quotes"],
        })

    surface_summaries.sort(key=lambda x: -x["must_have_score"])

    summary = {
        "total_reviews": total,
        "automatable": total - primary_counts.get("not_automatable", 0),
        "not_automatable": primary_counts.get("not_automatable", 0),
        "ownership_gap_count": len(ownership_gap_reviews),
        "primary_label_counts": dict(primary_counts.most_common()),
        "patient_stage_counts": dict(stage_counts.most_common()),
        "automation_tier_counts": dict(tier_counts.most_common()),
        "product_surfaces": surface_summaries,
    }

    SUMMARY_OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    REVIEWS_OUT.write_text(json.dumps(reviews, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== PRODUCT OPPORTUNITY MAP ===")
    print(f"Total labelled:    {total}")
    print(f"Automatable:       {summary['automatable']}  ({round(summary['automatable']/total*100,1)}%)")
    print(f"Not automatable:   {summary['not_automatable']}  ({round(summary['not_automatable']/total*100,1)}%)")
    print(f"Ownership gap:     {summary['ownership_gap_count']} reviews mention no ownership/chasing")
    print()
    print(f"{'Product surface':<35} {'Count':>6} {'%':>6} {'Must-have':>10}")
    print("-" * 65)
    for s in surface_summaries:
        print(f"  {s['product_surface']:<33} {s['count']:>6} {str(s['pct'])+'%':>6} {s['must_have_score']:>10}")

    print()
    print("Primary label breakdown:")
    for label, count in primary_counts.most_common():
        pct = round(count / total * 100, 1)
        print(f"  {label:<30} {count:4d}  {pct}%")

    return summary


def deep_dive(summary):
    """For each high-priority surface, ask DeepSeek what specifically is failing."""
    client = _client()
    reviews_data = json.loads(REVIEWS_OUT.read_text(encoding="utf-8"))
    labelled = [r for r in reviews_data if r.get("label")]

    deep_dives = {}
    surfaces_to_dive = [
        s for s in summary["product_surfaces"]
        if s["product_surface"] != "out_of_scope"
        and (s["count"] >= 20 or s["must_have_score"] >= 15)
    ]

    for surface in surfaces_to_dive:
        name = surface["product_surface"]
        surface_reviews = [
            r for r in labelled
            if r["label"].get("product_surface") == name
        ]
        if not surface_reviews:
            continue

        print(f"  Deep dive: {name} ({len(surface_reviews)} reviews)...")

        sample = surface_reviews[:80]  # cap for context
        formatted = "\n---\n".join(
            f"[{r['rating']}*] {r['clinic']}: {r['text'][:400]}"
            for r in sample
        )

        prompt = (
            f"You are analysing {len(sample)} negative reviews from London gynaecology clinics, "
            f"all classified under the product surface '{name}'.\n\n"
            f"Identify the specific failure modes. For each: what exactly is breaking, "
            f"what a product would do to fix it, and the buyer pitch.\n\n"
            f"Reviews:\n{formatted}\n\n"
            f"Return ONLY JSON:\n"
            f'{{"sub_themes": [{{"name": "...", "count": <int>, "pct": <float>, '
            f'"what_is_failing": "...", "product_fix": "...", '
            f'"buyer_pitch": "...", "quotes": ["q1","q2"]}}], '
            f'"headline_finding": "2 sentences on the core operational failure", '
            f'"buyer_pitch": "1-2 sentences how to sell this fix to a clinic owner"}}'
        )

        resp = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "Product strategist. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
        text = resp.choices[0].message.content.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            deep_dives[name] = json.loads(text)
        except Exception as e:
            print(f"    parse failed: {e}")

    DEEPDIVE_OUT.write_text(json.dumps(deep_dives, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nDeep dives saved for {len(deep_dives)} surfaces.")
    return deep_dives


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true", help="Gold-standard sample of 100 reviews only")
    parser.add_argument("--aggregate", action="store_true", help="Skip classification, re-aggregate from cache")
    parser.add_argument("--no-deepdive", action="store_true", help="Skip deep-dive calls")
    args = parser.parse_args()

    reviews = load_all_reviews()
    print(f"Loaded {len(reviews)} reviews from {len(set(r['clinic'] for r in reviews))} clinics")

    if not args.aggregate:
        reviews = run_classification(reviews, validate_only=args.validate)
        if args.validate:
            print("\nValidation complete. Review the output above.")
            print("If labels look accurate, run without --validate to classify all reviews.")
            return

    summary = aggregate(reviews)

    if not args.no_deepdive:
        print("\n--- Deep diving high-priority surfaces ---")
        deep_dive(summary)

    print("\nDone. Files saved:")
    print(f"  {REVIEWS_OUT}")
    print(f"  {SUMMARY_OUT}")
    print(f"  {DEEPDIVE_OUT}")


if __name__ == "__main__":
    main()
