"""
Builds the full communication analysis data object for the HTML report.
Reads comm_classified_reviews.json and produces a structured summary
saved to data/comm_report_data.json.
"""
import json, re
from pathlib import Path
from collections import Counter, defaultdict
from slugify import slugify

sample = json.loads(Path("gynae_sample.json").read_text())

comm_keywords = [
    "communicat", "respond", "reply", "follow.up", "follow up", "email", "phone",
    "call back", "message", "contact", "reach", "inform", "told", "notif",
    "update", "result", "feedback", "hear back", "get back", "no response",
    "ignored", "unanswered", "unreachable", "voicemail", "discharge", "letter",
    "report", "aftercare", "after care", "post.op", "post op",
]

# ── Load all reviews + comm subset ───────────────────────────────────────
all_reviews = []
for c in sample:
    slug = slugify(c["name"])
    f = Path("data") / f"{slug}.json"
    if not f.exists(): continue
    for r in json.loads(f.read_text(encoding="utf-8")).get("reviews", []):
        if r.get("text", "").strip():
            all_reviews.append({**r, "clinic": c["name"]})

comm_reviews_raw = [
    r for r in all_reviews
    if any(re.search(kw, r.get("text", "").lower()) for kw in comm_keywords)
]

# ── Load labels ───────────────────────────────────────────────────────────
classified_data = json.loads(Path("data/comm_classified_reviews.json").read_text(encoding="utf-8"))
classified = [r for r in classified_data if r.get("label")]
total = len(classified)

# ── Helper: pct ───────────────────────────────────────────────────────────
def pct(n, d): return round(n / d * 100, 1) if d else 0

# ── Stage breakdown ───────────────────────────────────────────────────────
STAGES   = ["during_treatment", "post_treatment", "booking_admin", "pre_appointment", "complaint"]
RESP     = ["wrong_info", "no_response", "slow_response", "other"]
CHANNELS = ["phone", "email", "in_person", "coordinator", "unclear"]
SOUGHT   = ["treatment_update", "test_results", "appointment", "financial_info",
            "complaint_response", "general_info", "aftercare", "other"]

stage_counts   = Counter(r["label"]["stage"]          for r in classified)
resp_counts    = Counter(r["label"]["response_type"]   for r in classified)
channel_counts = Counter(r["label"]["channel"]         for r in classified)
sought_counts  = Counter(r["label"]["what_sought"]     for r in classified)

# Stage × response_type matrix
stage_resp = defaultdict(Counter)
for r in classified:
    stage_resp[r["label"]["stage"]][r["label"]["response_type"]] += 1

# Stage × what_sought matrix
stage_sought = defaultdict(Counter)
for r in classified:
    stage_sought[r["label"]["stage"]][r["label"]["what_sought"]] += 1

# Channel × response_type
chan_resp = defaultdict(Counter)
for r in classified:
    chan_resp[r["label"]["channel"]][r["label"]["response_type"]] += 1

# Top 15 label combinations
combo_counts = Counter()
for r in classified:
    l = r["label"]
    combo_counts[(l["stage"], l["response_type"], l["what_sought"])] += 1

# Clinic breakdown by stage
clinic_stage   = defaultdict(Counter)
clinic_channel = defaultdict(Counter)
for r in classified:
    clinic_stage[r["clinic"]][r["label"]["stage"]] += 1
    clinic_channel[r["clinic"]][r["label"]["channel"]] += 1

clinic_profiles = []
for clinic, stage_c in clinic_stage.items():
    t = sum(stage_c.values())
    if t < 3: continue
    top_stage = stage_c.most_common(1)[0]
    clinic_profiles.append({
        "clinic": clinic,
        "total_comm": t,
        "stages": {s: {"count": stage_c.get(s, 0), "pct": pct(stage_c.get(s, 0), t)} for s in STAGES},
        "top_stage": top_stage[0],
        "top_stage_pct": pct(top_stage[1], t),
    })
clinic_profiles.sort(key=lambda x: -x["total_comm"])

# Rating breakdown of comm reviews
rating_counts = Counter(r["rating"] for r in comm_reviews_raw)

# ── Build output ──────────────────────────────────────────────────────────
out = {
    "meta": {
        "total_reviews": len(all_reviews),
        "comm_reviews_keyword": len(comm_reviews_raw),
        "comm_reviews_classified": total,
        "comm_pct_of_all": pct(len(comm_reviews_raw), len(all_reviews)),
        "rating_breakdown": {str(k): v for k, v in sorted(rating_counts.items())},
    },
    "stage": [
        {
            "name": s,
            "count": stage_counts.get(s, 0),
            "pct": pct(stage_counts.get(s, 0), total),
            "dominant_response": max(RESP, key=lambda rt: stage_resp[s].get(rt, 0)),
            "response_breakdown": {
                rt: {
                    "count": stage_resp[s].get(rt, 0),
                    "pct": pct(stage_resp[s].get(rt, 0), stage_counts.get(s, 1)),
                    "is_dominant": rt == max(RESP, key=lambda x: stage_resp[s].get(x, 0)),
                }
                for rt in RESP
            },
            "top_sought": [
                {"name": k, "count": v}
                for k, v in stage_sought[s].most_common(3)
            ],
        }
        for s in STAGES
    ],

    "response_type": [
        {"name": rt, "count": resp_counts.get(rt, 0), "pct": pct(resp_counts.get(rt, 0), total)}
        for rt in RESP
    ],
    "channel": [
        {
            "name": ch,
            "count": channel_counts.get(ch, 0),
            "pct": pct(channel_counts.get(ch, 0), total),
            "top_response": chan_resp[ch].most_common(1)[0][0] if chan_resp[ch] else "—",
            "top_response_pct": pct(chan_resp[ch].most_common(1)[0][1], channel_counts.get(ch, 1)) if chan_resp[ch] else 0,
        }
        for ch in CHANNELS
    ],
    "what_sought": [
        {"name": ws, "count": sought_counts.get(ws, 0), "pct": pct(sought_counts.get(ws, 0), total)}
        for ws in SOUGHT
    ],
    "top_combinations": [
        {
            "stage": combo[0], "response_type": combo[1], "what_sought": combo[2],
            "count": count, "pct": pct(count, total),
        }
        for combo, count in combo_counts.most_common(15)
    ],
    "clinic_profiles": clinic_profiles,
}

Path("data/comm_report_data.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)

print(f"Total reviews:              {out['meta']['total_reviews']}")
print(f"Comm-related (keyword):     {out['meta']['comm_reviews_keyword']} ({out['meta']['comm_pct_of_all']}%)")
print(f"Comm-related (classified):  {out['meta']['comm_reviews_classified']}")
print(f"Saved to data/comm_report_data.json")
