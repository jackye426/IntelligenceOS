#!/usr/bin/env bash
# Live smoke: Doctify London Gynaecology (~25 specialists after load-more).
# Not run in CI by default (flaky / network).
set -euo pipefail
URL="${1:-https://www.doctify.com/uk/practice/london-gynaecology-harley-street#specialists}"
python3 -m gtm_pipeline doctify extract --url "$URL" --dry-run
