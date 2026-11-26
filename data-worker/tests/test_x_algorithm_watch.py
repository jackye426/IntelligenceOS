import fcntl
import json

import pytest

from x_algorithm_watch import BASELINE, FILES, FUNCTIONS, PARAMS, SCORING, parse_snapshot, run_watch

NEW = "a" * 40
THIRD = "b" * 40


def source(weight=5.0, follow=50_000, term="reply"):
    files = dict.fromkeys(FILES, "sample")
    prefix = '\n'.join(f'param!(Other{i}Weight, f64, "other_{i}", 2.0);' for i in range(10))
    files[PARAMS] = f'{prefix}\nparam!(ReplyWeight, f64, "reply", {weight});\n' \
                    f'param!(ColdStartFollowerCap, i64, "cap", {follow});'
    for path, names in FUNCTIONS.items():
        files[path] = '\n'.join(f"fn {name}() {{ let x = 0; }}" for name in names if name != "weighted_terms")
    files[SCORING] += f'\nfn weighted_terms() -> [(&\'static str, f64); 1] ' \
                      f'{{ [("{term}", apply(product(scores.a, scores.b), weights.reply, ))] }}'
    return files


def fetch(sha, versions, calls):
    def get(url):
        calls.append(url)
        if url == "https://api.github.com/repos/xai-org/x-algorithm/commits/main":
            return json.dumps({"sha": sha})
        prefix = "https://raw.githubusercontent.com/xai-org/x-algorithm/"
        assert url.startswith(prefix)
        version, file = url.removeprefix(prefix).split("/", 1)
        assert file in FILES
        return versions[version][file]
    return get


def test_seed_diff_and_no_unchanged_download(tmp_path):
    calls = []
    get = fetch(NEW, {BASELINE: source(), NEW: source(8.0, 49_000, "quote")}, calls)
    assert run_watch(tmp_path, get=get)["previous"] == BASELINE
    state = tmp_path / "snapshots.json"
    saved = json.loads(state.read_text())["history"]
    assert [x["commit"] for x in saved] == [BASELINE, NEW]
    by_name = {(x["kind"], x["name"]): x for x in saved[-1]["changes"]}
    assert by_name[("parameter", "ReplyWeight")]["relative_change"] == 0.6
    assert by_name[("parameter", "ColdStartFollowerCap")]["after"]["default"] == 49_000
    assert by_name[("scoring_term", "reply")]["change"] == "removed"
    assert by_name[("scoring_term", "quote")]["change"] == "added"
    assert by_name[("logic", "weighted_terms")]["change"] == "changed"
    calls.clear()
    assert run_watch(tmp_path, get=get)["status"] == "unchanged"
    assert len(calls) == 1


def test_invalid_or_partial_upstream_does_not_replace_snapshot(tmp_path):
    run_watch(tmp_path, get=fetch(BASELINE, {BASELINE: source()}, []))
    state = tmp_path / "snapshots.json"
    before = state.read_bytes()
    invalid = source()
    invalid[SCORING] = invalid[SCORING].replace("; 1]", "; 2]")
    with pytest.raises(ValueError, match="scoring tuple"):
        run_watch(tmp_path, get=fetch(NEW, {NEW: invalid}, []))
    partial = source()
    partial.pop("README.md")
    with pytest.raises(KeyError):
        run_watch(tmp_path, get=fetch(THIRD, {THIRD: partial}, []))
    with pytest.raises(ValueError, match="40-character"):
        run_watch(tmp_path, get=fetch("../HEAD", {}, []))
    assert state.read_bytes() == before


def test_overlap_is_noop(tmp_path):
    with (tmp_path / "watch.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        calls = []
        assert run_watch(tmp_path, get=fetch(BASELINE, {}, calls))["status"] == "skipped_overlap"
    assert not calls


def test_formatting_only_is_not_a_logic_change():
    original, edited = source(), source()
    edited[SCORING] = edited[SCORING].replace("let x = 0;", "let  x = 0 ; /* note */")
    a, b = parse_snapshot(original, BASELINE), parse_snapshot(edited, NEW)
    assert a["logic_hashes"] == b["logic_hashes"]
    assert a["file_sha256"] != b["file_sha256"]
