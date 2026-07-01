import json, re, os
from pathlib import Path
from slugify import slugify
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(Path(".env"))
client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=os.environ["OPENROUTER_API_KEY"])

sample = json.loads(Path("gynae_sample.json").read_text())
comm_keywords = [
    "communicat", "respond", "reply", "follow.up", "follow up", "email", "phone",
    "call back", "message", "contact", "reach", "inform", "told", "notif",
    "update", "result", "feedback", "hear back", "get back", "no response",
    "ignored", "unanswered", "unreachable", "voicemail", "discharge", "letter",
    "report", "aftercare", "after care", "post.op", "post op",
]

comm_reviews = []
for c in sample:
    slug = slugify(c["name"])
    raw_f = Path("data") / f"{slug}.json"
    if not raw_f.exists():
        continue
    for r in json.loads(raw_f.read_text(encoding="utf-8")).get("reviews", []):
        if any(re.search(kw, r.get("text", "").lower()) for kw in comm_keywords):
            comm_reviews.append({"clinic": c["name"], "rating": r["rating"], "text": r["text"]})

print(f"Analysing {len(comm_reviews)} communication reviews...")

formatted = "\n---\n".join(
    f"[{r['rating']}*] {r['clinic']}\n{r['text']}" for r in comm_reviews
)

n = len(comm_reviews)
prompt = (
    f"You are analysing {n} negative reviews from London gynaecology and fertility clinics, "
    "all relating to communication problems.\n\n"
    "Classify across FOUR dimensions:\n\n"
    "1. RESPONSE TYPE: No response at all vs slow/delayed response vs wrong/conflicting information?\n"
    "2. JOURNEY STAGE: When did the failure happen?\n"
    "   - pre_appointment: enquiring about services, asking questions before becoming a patient\n"
    "   - booking_admin: trying to book, scheduling errors, cancellations\n"
    "   - during_treatment: communication failures while actively being treated\n"
    "   - post_treatment: follow-up after procedures, getting results, aftercare\n"
    "   - complaint_handling: trying to raise or resolve a formal complaint\n"
    "3. CHANNEL: Phone, email, patient coordinator, or in-person?\n"
    "4. WHAT WAS SOUGHT: What was the patient actually trying to get?\n\n"
    f"Reviews:\n{formatted[:90000]}\n\n"
    "Return ONLY JSON:\n"
    "{\n"
    '  "response_type": {\n'
    '    "no_response": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "slow_response": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "wrong_information": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]}\n'
    "  },\n"
    '  "journey_stage": {\n'
    '    "pre_appointment": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "booking_admin": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "during_treatment": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "post_treatment": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]},\n'
    '    "complaint_handling": {"count": <int>, "pct": <float>, "description": "...", "quotes": ["q1","q2"]}\n'
    "  },\n"
    '  "channel": {\n'
    '    "phone": {"count": <int>, "pct": <float>},\n'
    '    "email": {"count": <int>, "pct": <float>},\n'
    '    "patient_coordinator": {"count": <int>, "pct": <float>},\n'
    '    "in_person": {"count": <int>, "pct": <float>}\n'
    "  },\n"
    '  "what_sought": [\n'
    '    {"name": "e.g. Test results", "count": <int>, "pct": <float>, "quotes": ["q1","q2"]}\n'
    "  ],\n"
    '  "key_insight": "3-4 sentences on when, how, and what patients are failing to get"\n'
    "}"
)

resp = client.chat.completions.create(
    model="deepseek/deepseek-chat-v3-0324",
    messages=[
        {"role": "system", "content": "Patient experience analyst. Return only valid JSON."},
        {"role": "user", "content": prompt},
    ],
    max_tokens=3000,
    temperature=0.1,
)
text = resp.choices[0].message.content.strip()
if text.startswith("```"):
    lines = text.splitlines()
    text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

result = json.loads(text)
Path("data/communication_breakdown.json").write_text(
    json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
)

print()
print("=" * 60)
print("KEY INSIGHT")
print("=" * 60)
print(result["key_insight"])

print()
print("RESPONSE TYPE — lack of response vs slow vs wrong info")
print("-" * 60)
for k, v in result["response_type"].items():
    label = k.replace("_", " ").title()
    print(f"  {label:<25} {v['count']:3d} reviews  {v['pct']}%")
    print(f"  {v['description']}")
    for q in v.get("quotes", [])[:2]:
        print(f'    > "{q}"')
    print()

print("JOURNEY STAGE — when in the patient journey")
print("-" * 60)
for k, v in result["journey_stage"].items():
    label = k.replace("_", " ").title()
    print(f"  {label:<25} {v['count']:3d} reviews  {v['pct']}%")
    print(f"  {v['description']}")
    for q in v.get("quotes", [])[:2]:
        print(f'    > "{q}"')
    print()

print("CHANNEL — how were patients trying to reach the clinic?")
print("-" * 60)
for k, v in result["channel"].items():
    label = k.replace("_", " ").title()
    print(f"  {label:<25} {v['count']:3d}  {v['pct']}%")

print()
print("WHAT WERE PATIENTS TRYING TO GET?")
print("-" * 60)
for item in sorted(result["what_sought"], key=lambda x: -x["count"]):
    print(f"  {item['count']:3d}  {item['pct']}%  {item['name']}")
    for q in item.get("quotes", [])[:1]:
        print(f'    > "{q}"')
