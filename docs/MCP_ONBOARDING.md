# DocMap TikTok Intelligence — Claude setup guide

**For:** Marketing and content team (no coding experience needed)  
**Scope:** **TikTok only** — ~40 @docmap videos, comments, hooks, and strategy notes  
**Last updated:** 2026-07-10  
**Need help?** Ask Jack or whoever manages team passwords.

> **Note:** Clinic sales, doctor outreach, and other DocMap data are **not** part of this connector yet. This guide is only for TikTok marketing intelligence.

---

## What is this?

This connects **Claude Desktop** to **DocMap’s TikTok data** — views, saves, transcripts, hooks, comments, A/B tests, playbooks, and a **decision log** (what we committed to do next and whether it worked).

Once set up, you can **chat with Claude** and ask things like:

- “Which TikTok videos performed best last month?”
- “What are people asking in the comments on our top posts?”
- “We used two different hooks on the same video — which one won?”
- “What should we film next about endometriosis?”
- “Log that we’re reposting surgical-photos with the direct CTA — check it in a week.”
- “Which decisions are due for review?”

Claude looks up **real numbers and quotes from our videos** and should include **links or titles** — not guess from the internet.

Think of it as giving Claude a **read-only pass** to our TikTok performance library, plus a shared memory of **learnings** and **commitments**.

---

## What’s in the library?

| Data | What you get |
|------|----------------|
| **~40 TikTok videos** | Views, likes, saves, shares, engagement |
| **Transcripts** | What was said in each video |
| **Hooks** | Spoken line, caption opening, and on-screen text (where captured) |
| **Comments** | What viewers asked — cost, NHS, specialists, symptoms, etc. |
| **A/B tests** | Same video posted with different hooks — which performed better |
| **Insights** | Approved takeaways from analysis (“what we observed”) |
| **Decision log** | Commitments for next actions + later outcome checks |
| **Playbooks / constitution** | Standing strategy rules (changed rarely, by a human) |

Data refreshes automatically: **comments daily**, full update **weekly**. Brand-new posts may take a few days to show up.

---

## How Claude’s memory layers work

These are **not** the same thing. Use the right one:

| Layer | Answers… | Example |
|-------|----------|---------|
| **A/B learning** | In *this* hook pair, who won? | “Direct CTA beat Q&A open on surgical-photos.” |
| **Insight** | What did we *observe* / learn? | “Imperative surgical CTAs outperform soft interview opens.” |
| **Decision** | What will we *do next*, and how will we judge it? | “Repost surgical-photos with imperative CTA. Success = saves/1k in top quartile within 7 days.” |
| **Constitution** | What do we *always* believe? | Standing rule pasted into playbook files (rare) |

**Rule of thumb:** Insights and A/B = past. Decisions = future commitment + later check. Constitution = only after something keeps proving true.

When you agree on a next action in chat, say so clearly (e.g. “Log that decision”) so Claude writes it to the decision log — not only into an insight.

---

## What can you ask Claude to do?

### Performance & rankings

| You can ask… | Claude can show… |
|--------------|------------------|
| “Top 10 videos by views” | Ranked list with stats |
| “Best posts by saves” or “engagement” | Same, sorted different ways |
| “How did we do since [date]?” | Recent batch with strong vs weak posts |
| “Compare our best and worst endometriosis videos” | Side-by-side stats and hooks |

### Deep dive on one video

| You can ask… | Claude can show… |
|--------------|------------------|
| “Break down this video: [paste link or ID]” | Full transcript, caption, hooks, comment themes |
| “What hook did we use on video [ID]?” | Spoken, caption, and on-screen hook text |
| “What did people ask in the comments?” | Common questions and themes |

### Comments & audience questions

| You can ask… | Claude can show… |
|--------------|------------------|
| “What do viewers ask most on our TikToks?” | Themes across comments (cost, waiting lists, etc.) |
| “What questions came up on our top-performing posts?” | Comment analysis tied to performance |

### Hooks & A/B tests

| You can ask… | Claude can show… |
|--------------|------------------|
| “Did we test two hooks on the same content?” | A/B pairs and which version won |
| “Which hook style wins most often?” | Patterns from A/B history |
| “This video underperformed — suggest a better hook” | Ideas based on top performers (you approve before filming) |
| “Save what we learned from this A/B test” | Stores an approved note for next time (only after you confirm) |

### Strategy & planning

| You can ask… | Claude can show… |
|--------------|------------------|
| “Give me a TikTok briefing on [topic]” | Stats + comments + playbook notes in one answer |
| “Suggest 5 new angles for pre-surgery content” | Ideas grounded in what’s already working |
| “What should we film next week?” | Recommendations from performance + comment gaps |

### Decisions (commit → check later)

| You can ask… | Claude should… |
|--------------|----------------|
| “Log that we’re reposting [video] with [hook] — success = [metric] in 7 days” | Save a **decision** (not only an insight) |
| “What decisions are due?” | List open items past their review date |
| “Did last week’s repost work?” | Pull live metrics, propose a verdict, wait for you to confirm |
| “Cancel that — we’re not filming it” | Mark the decision cancelled with a reason |

**Good decision (say this kind of thing):**  
*“Repost surgical-photos with the imperative CTA (‘always ask for photos’). Success = saves per 1k views in the top quartile of the last 30 days within 7 days.”*

**Too vague (don’t leave it like this):**  
*“Maybe try better hooks on surgery content sometime.”*

**Best first question to try:**  
*“Give me a TikTok content briefing on endometriosis — what’s working and what people ask in comments.”*

---

## Weekly TikTok review (suggested routine)

Use this in your Monday content meeting or solo review:

1. **Strategy brief** — constitution, approved learnings, open decisions  
2. **Due decisions first** — close anything due before planning new posts (Claude proposes a verdict from metrics; **you** confirm)  
3. **Cohort since last Monday** — check for a staleness warning if results look empty  
4. **Underperformers** — discuss why a post flopped → draft insight → you say **approve**  
5. **A/B / variant groups** — hook packaging comparisons; save A/B learnings when the pair takeaway is clear  
6. **Commit next actions** — when the team agrees what to film/repost, ask Claude to **log the decision** with success criteria  
7. **Hook suggestions** — only after the brief; you approve hooks before filming  
8. **Rare:** promote a stable learning into the playbook (human pastes — never automatic)

**Important:** If a date filter returns nothing, check for a staleness warning — the library may be behind the live TikTok channel, not that posting stopped.

Claude pulls live data each time — you don’t need to export spreadsheets first.

---

## What this cannot do (yet)

- **Clinic or doctor data** — not connected (coming later)
- **Instagram** — limited; TikTok is the main dataset today
- **Post new TikToks or edit videos** — read-only
- **Guarantee viral hits** — it shows what worked before, not predictions

If Claude says it has no data, the video may be too new or the system may still be updating — try again later or ask Jack.

---

## What you need before starting

- [ ] **Claude Desktop** — [claude.ai/download](https://claude.ai/download)
- [ ] **Access code** — from team password manager (ask Jack)
- [ ] **Node.js** — free install from [nodejs.org](https://nodejs.org) (pick **LTS**, restart PC after)
- [ ] **~10 minutes**

---

## Setup (step by step)

### Step 1 — Install Node.js (one time)

1. Go to [nodejs.org](https://nodejs.org) → download **LTS**
2. Run installer → accept defaults
3. **Restart your computer**

---

### Step 2 — Open Claude’s settings file

**Windows:** Press **Windows + R** → type `%APPDATA%\Claude` → Enter → open **`claude_desktop_config.json`** in Notepad

**Mac:** Finder → **Cmd + Shift + G** → paste `~/Library/Application Support/Claude` → open **`claude_desktop_config.json`**

If the file doesn’t exist, create a new file with that exact name.

---

### Step 3 — Paste these settings

**If the file is empty**, paste everything below.  
**If it already has other connectors**, ask Jack to help merge — don’t delete existing entries.

**Only edit one line:** replace `PASTE_YOUR_ACCESS_CODE_HERE` with the code from the password manager.

The finished line should look like: `"DOCMAP_MCP_AUTH": "Bearer your-long-code-here"`  
(Keep **`Bearer`** and the space before the code.)

```
{
  "mcpServers": {
    "docmap-intelligence": {
      "command": "npx",
      "args": [
        "-y",
        "mcp-remote@latest",
        "https://mcp.docmap.co.uk/mcp",
        "--transport",
        "http-only",
        "--header",
        "Authorization:${DOCMAP_MCP_AUTH}"
      ],
      "env": {
        "DOCMAP_MCP_AUTH": "Bearer PASTE_YOUR_ACCESS_CODE_HERE"
      }
    }
  }
}
```

Save and close. **Never share the access code in Slack or email.**

---

### Step 4 — Restart Claude

1. **Quit** Claude fully (system tray → Exit)
2. Wait 5 seconds
3. Reopen Claude

First launch may take **10–20 seconds** while a small helper downloads — that’s normal.

---

### Step 5 — Check it worked

- Look for the **hammer 🔨 / tools** icon below the chat box
- Click it → **docmap-intelligence** should appear

**Test message:**

> Use DocMap TikTok data: show me the top 5 posts by views and summarise each hook.

You should get real @docmap stats and links — not a generic answer.

---

## Example questions (copy & paste)

**Quick checks**
- “Top 10 TikTok posts by saves per 1k views.”
- “Best performing endometriosis videos — hooks and view counts.”
- “TikTok posts since 1 April 2026, ranked by engagement.”

**Comments & ideas**
- “What do people ask in comments on our highest-reach videos?”
- “Suggest 5 new TikTok topics based on comment questions we haven’t answered.”

**Hooks & experiments**
- “List all hook A/B tests and which version won.”
- “Video [ID] flopped — suggest a hook repackage using our top performers.”

**Meeting prep**
- “Give me a TikTok content briefing for our weekly marketing sync.”
- “Summarise what’s working vs underperforming this month on TikTok.”

**Decisions**
- “Log this decision: [action] — success = [metric] by [date].”
- “List open decisions due for review.”
- “For decision [id], pull metrics and propose a verdict — wait for my confirm.”

---

## Tips for better answers

1. **Ask for links** — “include TikTok URLs for each video.”
2. **Be specific on dates** — “since March 2026” beats “recently.”
3. **One video at a time** — paste the video link or ID for a full breakdown.
4. **If answers sound generic**, say: “Use DocMap TikTok data — don’t guess.”
5. **Hook suggestions** — treat as drafts; your judgment before filming.
6. **Commit decisions out loud** — when you agree what to film/repost, say “log that decision” with a success measure so next week’s chat can check the outcome.
7. **Don’t confuse layers** — “what we learned” → insight/A/B; “what we’ll do next” → decision.
8. **Publish dates** — if a date looks wrong, ask Claude to re-check `posted_at` from DocMap. It must not guess from the video ID.

---

## Important rules

**Do**
- Keep the access code in the password manager only
- Use for internal DocMap marketing planning
- Save A/B learnings only after the team agrees on the takeaway
- Log decisions when you commit to a next action (with a clear success measure)
- Confirm decision outcomes yourself — Claude proposes from metrics; you say yes/no

**Don’t**
- Share the access code publicly
- Assume Claude knows TikTok stats without checking DocMap data
- Film a new hook suggestion without team sign-off
- Put “what we’ll do next” only into an insight — that belongs in the decision log

---

## Something not working?

| Problem | Try this |
|---------|----------|
| “MCP server could not be loaded” | Settings must use the full block above (`npx` + `mcp-remote`), not just a website URL. Ask Jack for a fresh copy. |
| No tools / hammer icon | Quit Claude fully, check Node.js installed, wait 20 sec on reopen. |
| Generic answers, no stats | Say: “Query DocMap TikTok intelligence.” |
| Empty / no videos | Data may be updating — retry later or ask Jack. |
| “Unauthorized” | Access code wrong or missing `Bearer ` before the code. |

**IT / technical help:** [`mcp_team_setup.md`](mcp_team_setup.md)

---

## FAQ

**Do I need to code?**  
No.

**TikTok only?**  
Yes — for now. Clinic and outreach data will be added separately later.

**What’s the difference between an insight and a decision?**  
Insight = what we learned from past posts. Decision = what we will do next and how we’ll judge it later. A/B learning = who won in a specific hook pair.

**How fresh is the data?**  
Comments: daily. Full refresh: weekly.

**Phone?**  
Computer + Claude Desktop only.

**Cost?**  
Normal Claude account; DocMap hosts the connector.

---

## Quick reference

| | |
|---|---|
| **What it covers** | @docmap TikTok (~40 videos) |
| **Connector name** | docmap-intelligence |
| **Access code** | Team password manager |
| **Settings file (Windows)** | `%APPDATA%\Claude\claude_desktop_config.json` |
| **Test question** | “Top 5 TikTok posts by views with hooks.” |

---

## More prompts (optional)

TikTok-focused examples: [`mcp_prompt_guide.md`](mcp_prompt_guide.md) (TikTok sections)
