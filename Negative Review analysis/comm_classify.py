"""
Per-review communication classifier.
Sends reviews in batches of 25, gets a label for every single one,
then aggregates. No estimation — every review gets counted.
"""
import json, re, os, time, hashlib
from pathlib import Path
from slugify import slugify
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(".env"))
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])

CACHE = Path("data/comm_classified_reviews.json")
CACHE_INDEX = Path("data/comm_label_cache.json")  # keyed by stable review ID

# ── 1. Collect communication-related reviews ──────────────────────────────
sample = json.loads(Path("gynae_sample.json").read_text())
comm_keywords = [
    "communicat", "respond", "reply", "follow.up", "follow up", "email", "phone",
    "call back", "message", "contact", "reach", "inform", "told", "notif",
    "update", "result", "feedback", "hear back", "get back", "no response",
    "ignored", "unanswered", "unreachable", "voicemail", "discharge", "letter",
    "report", "aftercare", "after care", "post.op", "post op",
]
def review_id(clinic, text):
    """Stable content-based ID — survives list reordering."""
    return hashlib.md5(f"{clinic}||{text[:300]}".encode()).hexdigest()

comm_reviews = []
for c in sample:
    slug = slugify(c["name"])
    raw_f = Path("data") / f"{slug}.json"
    if not raw_f.exists():
        continue
    for r in json.loads(raw_f.read_text(encoding="utf-8")).get("reviews", []):
        if any(re.search(kw, r.get("text", "").lower()) for kw in comm_keywords):
            comm_reviews.append({
                "id": review_id(c["name"], r.get("text", "")),
                "clinic": c["name"],
                "rating": r["rating"],
                "text": r["text"],
                "label": None,
            })

print(f"Reviews to classify: {len(comm_reviews)}")

# ── 2. Classify per review (batches of 25) ────────────────────────────────
BATCH = 25
SYSTEM = (
    "You are a patient experience analyst. "
    "Classify patient reviews exactly as instructed. Return only valid JSON."
)

INSTRUCTIONS = """Classify each review by these four fields. Use ONLY the allowed values.

stage (when in the patient journey did the communication fail?):
  pre_appointment  — patient was enquiring about services or trying to book for the first time
  booking_admin    — existing patient trying to schedule, reschedule, or dealing with admin errors
  during_treatment — patient is mid-treatment and cannot get updates, instructions, or clarity
  post_treatment   — patient has finished treatment and cannot get results, follow-up, or aftercare
  complaint        — patient is trying to raise or resolve a formal complaint

response_type (what kind of communication failure?):
  no_response      — clinic never replied at all (ignored, ghosted, voicemail never returned)
  slow_response    — clinic eventually replied but took an unreasonably long time
  wrong_info       — clinic gave incorrect, conflicting, or misleading information
  other            — communication problem that doesn't fit the above

channel (how was the patient trying to communicate?):
  phone            — telephone calls
  email            — emails or online messages
  coordinator      — through an assigned patient coordinator
  in_person        — face-to-face or during a consultation
  unclear          — cannot tell from the review

what_sought (what was the patient trying to get? pick the single best fit):
  test_results     — blood tests, scan results, lab reports
  appointment      — booking, confirming, or changing an appointment
  treatment_update — next steps, medication instructions, cycle progress
  financial_info   — cost breakdown, invoices, refunds
  complaint_response — acknowledgement or resolution of a complaint
  aftercare        — post-procedure support or discharge guidance
  general_info     — general enquiry about services before committing
  other            — something else"""


def classify_batch(batch):
    """Send a batch of reviews; get back one label object per review."""
    numbered = "\n\n".join(
        f"[{i+1}] ({r['clinic']}, {r['rating']}*)\n{r['text'][:600]}"
        for i, r in enumerate(batch)
    )
    prompt = (
        f"{INSTRUCTIONS}\n\n"
        f"Classify these {len(batch)} reviews. "
        f"Return a JSON array of {len(batch)} objects, one per review, in order:\n"
        '[{"stage":"...","response_type":"...","channel":"...","what_sought":"..."},...]\n\n'
        f"Reviews:\n{numbered}"
    )
    resp = client.chat.completions.create(
        model="deepseek/deepseek-chat-v3-0324",
        messages=[
            {"role": "system", "content": SYSTEM},
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
    if not isinstance(labels, list):
        raise ValueError(f"Expected list, got: {type(labels)}")
    return labels


# Load label cache (keyed by stable review ID) — safe across dataset expansions
label_cache = {}
if CACHE_INDEX.exists():
    label_cache = json.loads(CACHE_INDEX.read_text(encoding="utf-8"))

for rev in comm_reviews:
    if rev["id"] in label_cache:
        rev["label"] = label_cache[rev["id"]]

to_classify = [i for i, r in enumerate(comm_reviews) if r["label"] is None]
print(f"Already classified: {len(comm_reviews) - len(to_classify)}")
print(f"Remaining:          {len(to_classify)}")

batches_done = 0
for start in range(0, len(to_classify), BATCH):
    idxs = to_classify[start:start + BATCH]
    batch = [comm_reviews[i] for i in idxs]
    try:
        labels = classify_batch(batch)
        if len(labels) != len(batch):
            print(f"  [warn] batch {start//BATCH+1}: got {len(labels)} labels for {len(batch)} reviews — skipping")
            continue
        for i, label in zip(idxs, labels):
            comm_reviews[i]["label"] = label
            label_cache[comm_reviews[i]["id"]] = label
        batches_done += 1
        print(f"  batch {start//BATCH+1}/{-(-len(to_classify)//BATCH)}: classified {len(idxs)} reviews", flush=True)
        # Save label cache after every batch so we can resume safely
        CACHE_INDEX.write_text(json.dumps(label_cache, ensure_ascii=False, indent=2), encoding="utf-8")
        CACHE.write_text(json.dumps(comm_reviews, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        print(f"  [error] batch {start//BATCH+1}: {e}")
        time.sleep(2)

# ── 3. Aggregate ──────────────────────────────────────────────────────────
classified = [r for r in comm_reviews if r.get("label")]
total = len(classified)
print(f"\nSuccessfully classified: {total} / {len(comm_reviews)}")

def counts(field):
    tally = {}
    for r in classified:
        val = r["label"].get(field, "unclear")
        tally[val] = tally.get(val, 0) + 1
    return sorted(tally.items(), key=lambda x: -x[1])

def top_quotes(field, value, n=3):
    return [r["text"][:200] for r in classified if r["label"].get(field) == value][:n]

print()
print("=" * 60)
print(f"STAGE — when in the patient journey  (n={total})")
print("=" * 60)
for val, count in counts("stage"):
    pct = round(count / total * 100, 1)
    print(f"  {val:<22} {count:4d}  {pct}%")
    for q in top_quotes("stage", val, 2):
        print(f'    > "{q[:120]}"')
    print()

print("=" * 60)
print(f"RESPONSE TYPE  (n={total})")
print("=" * 60)
for val, count in counts("response_type"):
    pct = round(count / total * 100, 1)
    print(f"  {val:<22} {count:4d}  {pct}%")
    for q in top_quotes("response_type", val, 2):
        print(f'    > "{q[:120]}"')
    print()

print("=" * 60)
print(f"CHANNEL  (n={total})")
print("=" * 60)
for val, count in counts("channel"):
    pct = round(count / total * 100, 1)
    print(f"  {val:<22} {count:4d}  {pct}%")

print()
print("=" * 60)
print(f"WHAT WERE PATIENTS TRYING TO GET?  (n={total})")
print("=" * 60)
for val, count in counts("what_sought"):
    pct = round(count / total * 100, 1)
    print(f"  {val:<22} {count:4d}  {pct}%")
    for q in top_quotes("what_sought", val, 1):
        print(f'    > "{q[:120]}"')
    print()

# Save final aggregated results
summary = {
    "total_classified": total,
    "stage": {v: {"count": c, "pct": round(c/total*100,1), "quotes": top_quotes("stage", v)} for v,c in counts("stage")},
    "response_type": {v: {"count": c, "pct": round(c/total*100,1), "quotes": top_quotes("response_type", v)} for v,c in counts("response_type")},
    "channel": {v: {"count": c, "pct": round(c/total*100,1)} for v,c in counts("channel")},
    "what_sought": {v: {"count": c, "pct": round(c/total*100,1), "quotes": top_quotes("what_sought", v)} for v,c in counts("what_sought")},
}
Path("data/communication_breakdown.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
)
print("\nSaved to data/communication_breakdown.json")
