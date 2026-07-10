# Component vocabulary (working)

**Status:** Stub — fill after first full-library `extract-components` pass.  
**Last updated:** 2026-07-10

Do **not** treat this as frozen enums in code until labels cover ~80% of videos.

## Hook types (preferred — already in schema)

- myth_correction
- warning
- direct_question
- symptom_recognition
- unexpected_fact
- authority_statement
- personal_story
- list_promise
- outcome_promise
- contrarian_claim
- other

## Soft labels to cluster after pass 1

| Field | Notes |
|-------|--------|
| `hook.emotional_mechanism_raw` | e.g. fear, validation, urgency, competence-gap |
| `topic.primary_raw` | content topic (not comment theme) |
| `speaker.type_raw` | liz / patient / mixed / voiceover |
| `format_raw` | expert_monologue / faq_reply / interview_qa / … |
| `cta.requested_action_raw` | follow / save / comment / link_in_bio / book |

## Funnel (fixed)

TOFU | MOFU | BOFU | unclear — see `docs/EXECUTION_PLAN_VIDEO_COMPONENTS.md` for metric join rules.
