"""Observe published X ranking code. Never execute it or change playbooks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPO = "xai-org/x-algorithm"
BASELINE = "52d45989090e63992ba04e4f6cfccd73bf8cc05c"
PARAMS = "home-mixer/params/param.rs"
SCORING = "xai-value-model/scoring.rs"
FUNCTIONS = {
    SCORING: ("weighted_terms", "offset_score", "fuse_heads", "multiplicative_score", "diversity_multiplier"),
    "xai-value-model/weights.rs": ("reply_weight_for", "dwell_weight_for"),
    "xai-value-model/inputs.rs": ("bidirectional_boost_eligible",),
    "home-mixer/scorers/author_cold_start.rs": ("cold_start_base_eligible", "apply_cold_start", "sample_reward"),
}
FILES = (PARAMS, *FUNCTIONS, "README.md")
SHA = re.compile(r"[0-9a-f]{40}\Z")
MACRO_START = re.compile(r"\bparam!\s*\(\s*(\w+)")
PARAM = re.compile(r'\s*(\w+)\s*,\s*([\w:<>]+)\s*,\s*"([^"]+)"\s*,\s*(.*?)\s*,?\s*$', re.S)
TERM = re.compile(r'\(\s*"([a-z_]+)"\s*,\s*apply\s*\(')
# Blank ordinary comments and strings without moving offsets. Unknown syntax must
# still satisfy the structural checks before it can replace the last good snapshot.
NON_CODE = re.compile(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"', re.S)
MAX_BYTES = 1_000_000
MAX_HISTORY = 104

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _read(url: str) -> str:
    req = Request(url, headers={"User-Agent": "IntelligenceOS-X-Algorithm-Watch"})
    with build_opener(NoRedirect()).open(req, timeout=12) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("upstream file exceeds size limit")
    return data.decode("utf-8")


def _sha(value: str) -> str:
    if not isinstance(value, str) or not SHA.fullmatch(value):
        raise ValueError("expected an exact 40-character GitHub commit SHA")
    return value


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _mask(code: str) -> str:
    return NON_CODE.sub(lambda m: " " * len(m[0]), code)


def _end(code: str, pos: int, opening: str, closing: str) -> int:
    level = 0
    for i in range(pos, len(code)):
        c = code[i]
        if c == opening:
            level += 1
        elif c == closing:
            level -= 1
            if level == 0:
                return i
    raise ValueError("unbalanced upstream Rust")


def _function(src: str, name: str) -> tuple[str, str]:
    masked = _mask(src)
    matches = list(re.finditer(rf"\bfn\s+{re.escape(name)}\b", masked))
    if len(matches) != 1:
        raise ValueError(f"missing or ambiguous upstream function: {name}")
    start = matches[0].start()
    brace = masked.index("{", matches[0].end())
    end = _end(masked, brace, "{", "}")
    return src[start:brace], src[brace:end + 1]


def _canonical(code: str) -> str:
    # Ignore formatting and comments, but preserve string contents and token
    # boundaries (e.g. don't turn "a b" and "ab" into the same logic).
    code = NON_CODE.sub(lambda m: " " if m[0].startswith("/") else m[0], code)
    return json.dumps(re.findall(r'"(?:\\.|[^"\\])*"|\w+|[^\s\w]', code))


def parse_snapshot(files: dict[str, str], commit: str, commit_date: str | None = None) -> dict:
    if set(files) != set(FILES) or any(not contents.strip() for contents in files.values()):
        raise ValueError("incomplete upstream source set")
    params, logic = {}, {}
    source = files[PARAMS]
    masked = _mask(source)
    for hit in MACRO_START.finditer(masked):
        name = hit[1]
        if not (name.endswith("Weight") or "ColdStart" in name or name in {
            "LowImpressionsMaxPositionRatio", "BidirectionalFollowReplyWeightBoost",
            "BidirectionalFollowDwellWeightBoost",
        }):
            continue
        start = masked.index("(", hit.start())
        end = _end(masked, start, "(", ")")
        match = PARAM.fullmatch(source[start + 1:end])
        if not match or name in params:
            raise ValueError(f"unparsed or duplicate upstream parameter: {name}")
        _, kind, key, default = match.groups()
        default = default.strip()
        scalar: str | bool | float | int = default
        if kind == "bool":
            if default not in ("true", "false"):
                raise ValueError(f"unsupported boolean default: {name}")
            scalar = default == "true"
        elif re.fullmatch(r"[fiu]\d+", kind):
            try:
                scalar = float(default) if kind.startswith("f") else int(default)
            except ValueError as exc:
                raise ValueError(f"unsupported numeric default: {name}") from exc
            if isinstance(scalar, float) and not math.isfinite(scalar):
                raise ValueError(f"non-finite default: {name}")
        params[name] = {"key": key, "type": kind, "default": scalar}
    # Versioned invariants distinguish parser breakage from ordinary additions or
    # removals. If the entire layout changes, update the parser before accepting it.
    if len(params) < 10:
        raise ValueError("parameter layout changed")
    header, body = _function(files[SCORING], "weighted_terms")
    size = re.search(r";\s*(\d+)\s*\]\s*$", header)
    terms = {}
    masked_body = _mask(body)
    for term in TERM.finditer(body):
        if term[1] in terms:
            raise ValueError("duplicate scoring term")
        opening = term.end() - 1
        end = _end(masked_body, opening, "(", ")")
        terms[term[1]] = _canonical(body[opening + 1:end])
    if not size or len(terms) != int(size[1]) or not terms:
        raise ValueError("scoring tuple layout changed")
    for path, names in FUNCTIONS.items():
        for name in names:
            if name == "weighted_terms":
                # The structured term diff is less noisy; the logic hash also
                # covers gating and changes to how the weight is computed.
                fragment = body
            else:
                sig, block = _function(files[path], name)
                fragment = sig + block
            logic[name] = _hash(_canonical(fragment))
    return {"commit": _sha(commit), "commit_date": commit_date, "params": params,
            "terms": terms, "logic_hashes": logic,
            "file_sha256": {p: _hash(files[p]) for p in FILES}}


def diff(before: dict, after: dict) -> list[dict]:
    result = []
    for group in ("params", "terms", "logic_hashes", "file_sha256"):
        left, right = before[group], after[group]
        for name in sorted(left.keys() | right.keys()):
            old, new = left.get(name), right.get(name)
            if old == new:
                continue
            kind = {"params": "parameter", "terms": "scoring_term",
                    "logic_hashes": "logic", "file_sha256": "source_file"}[group]
            entry = {"kind": kind, "name": name, "before": old, "after": new,
                     "change": "added" if name not in left else "removed" if name not in right else "changed"}
            if group == "params" and old and new and name.endswith("Weight"):
                a, b = old["default"], new["default"]
                if type(a) in (float, int) and type(b) in (float, int) and a:
                    relative = (b - a) / abs(a)
                    if math.isfinite(relative):
                        entry["relative_change"] = relative
            result.append(entry)
    return result


def _atomic_write(path: Path, data: dict) -> None:
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as out:
        pending = Path(out.name)
        try:
            json.dump(data, out, indent=2, sort_keys=True, allow_nan=False)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
            out.close()
            os.replace(pending, path)
        finally:
            pending.unlink(missing_ok=True)


def _state(state: Path) -> dict:
    if not state.exists():
        return {"schema": 1, "repo": REPO, "history": []}
    data = json.loads(state.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("repo") != REPO or not isinstance(data.get("history"), list):
        raise ValueError("invalid watcher state; refusing to overwrite it")
    return data


def _snapshot(commit: str, get, commit_date: str | None = None) -> dict:
    commit = _sha(commit)
    root = f"https://raw.githubusercontent.com/{REPO}/{commit}"
    return parse_snapshot({path: get(f"{root}/{path}") for path in FILES}, commit, commit_date)


def run_watch(state_dir: Path, *, get=_read) -> dict:
    """Atomically persist a successful observation and return a non-sensitive summary."""
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    path = state_dir / "snapshots.json"
    with (state_dir / "watch.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"status": "skipped_overlap"}
        state = _state(path)
        history = state["history"]
        head = json.loads(get(f"https://api.github.com/repos/{REPO}/commits/main"))
        commit = _sha(head["sha"])
        date = head.get("commit", {}).get("committer", {}).get("date")
        if history and history[-1]["commit"] == commit:
            return {"status": "unchanged", "commit": commit, "changes": 0}
        # First run preserves an explicit published baseline; a failed second
        # parse aborts the whole write rather than silently losing the diff.
        if not history and commit != BASELINE:
            history.append({**_snapshot(BASELINE, get), "previous": None, "changes": [],
                            "captured_at": datetime.now(timezone.utc).isoformat()})
        fresh = _snapshot(commit, get, date)
        previous = history[-1] if history else None
        changes = diff(previous, fresh) if previous else []
        history.append({**fresh, "previous": previous["commit"] if previous else None,
                        "changes": changes, "captured_at": datetime.now(timezone.utc).isoformat()})
        state["history"] = history[-MAX_HISTORY:]
        _atomic_write(path, state)
        return {"status": "observed", "commit": commit, "previous": previous["commit"] if previous else None, "changes": len(changes),
            "source": f"https://github.com/{REPO}/tree/{commit}"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "show"))
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    result = run_watch(args.state_dir) if args.command == "run" else _state(args.state_dir / "snapshots.json")
    if args.command == "show":
        result = result["history"][-1] if result["history"] else {"status": "no_snapshot"}
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
