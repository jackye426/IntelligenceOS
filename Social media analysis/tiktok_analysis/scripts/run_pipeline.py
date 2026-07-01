"""Refresh TikTok metadata, download media, transcribe, build metrics JSON."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
AUDIO = ROOT / "audio"
META = DATA / "yt_meta"

VIDEOS = [
    ("7629626326927805718", "Amy / endo community 30k"),
    ("7631307430890048790", "Liz Bruen intro endo nurse carousel"),
    ("7630900114982210838", "Liz laparoscopy 360 / excision hook"),
    ("7631220659770690818", "Excision vs ablation explainer"),
    ("7633862545228434710", "9-year diagnosis delay part 1"),
    ("7634274846117104918", "9-year diagnosis part 2"),
    ("7635716747869424918", "8 min GP WhatsApp prep"),
    ("7636091017875197207", "Endo belly"),
]


def tt_url(aid: str) -> str:
    return f"https://www.tiktok.com/@docmap/video/{aid}"


def run_yt_dlp_json(aid: str) -> dict:
    META.mkdir(parents=True, exist_ok=True)
    out = META / f"{aid}.json"
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "--dump-json",
        "--no-download",
        "-o",
        str(META / "%(id)s"),
        tt_url(aid),
    ]
    raw = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
    data = json.loads(raw.decode("utf-8"))
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def existing_media(aid: str) -> Path | None:
    for ext in ("mp4", "webm", "m4a", "mp3"):
        p = AUDIO / f"{aid}.{ext}"
        if p.exists():
            return p
    return None


def download_media(aid: str) -> Path:
    AUDIO.mkdir(parents=True, exist_ok=True)
    dest_tpl = str(AUDIO / f"{aid}.%(ext)s")
    cmd = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-warnings",
        "-f",
        "best",
        "-o",
        dest_tpl,
        tt_url(aid),
    ]
    subprocess.check_call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    p = existing_media(aid)
    if p:
        return p
    raise FileNotFoundError(f"no media for {aid}")


MEDICAL_TOPIC_HINT = re.compile(
    r"endo|endometriosis|period|pain|symptom|diagnos|women|girl|school|patient|gp|doctor|"
    r"nurse|fatigue|cycle|laparoscopy|uterus|gyn|pelvic|hormone|womb|surgery|clinic|treatment|"
    r"mri|ovaries|bowel|appointment|specialist",
    re.I,
)


def is_garbage_transcript(
    full_text: str, *, caption_hint: str | None = None
) -> bool:
    """Carousel / music-only TikTok audio often yields no usable speech."""
    t = full_text.strip()
    if not t:
        return True
    tl = t.lower()
    if len(t) < 18:
        return True
    words = tl.split()
    if len(words) <= 2 and len(t) < 40:
        return True
    if words and len(set(words)) == 1 and words[0] == "music":
        return True
    if re.fullmatch(r"(music\s*)+", tl):
        return True
    words_clean = [w.strip(".,!?") for w in tl.split() if w.strip(".,!?")]
    if len(words_clean) >= 3:
        noise_tokens = {"music", "you", "yeah", "uh", "um"}
        noise_hits = sum(1 for w in words_clean if w in noise_tokens)
        if noise_hits / len(words_clean) >= 0.6:
            return True
    # Whisper "vocals" captions on instrumental / slideshow audio
    if "♪" in t or "music playing" in tl or "piano play" in tl:
        return True
    # Generic outros with no substantive content (common on template/carousel exports)
    if re.search(
        r"today'?s video|see you (guys )?in the next|peace out|thanks for watching",
        tl,
    ):
        return True
    # Caption is clearly on-topic but ASR never touches the topic (song/slideshow hallucination)
    if caption_hint and len(t) < 600:
        if MEDICAL_TOPIC_HINT.search(caption_hint) and not MEDICAL_TOPIC_HINT.search(
            full_text
        ):
            return True
    return False


def remove_transcript_artifacts(aid: str) -> None:
    out_dir = DATA / "transcripts"
    for name in (f"{aid}.json", f"{aid}.txt", f"{aid}_FULL.txt", f"{aid}_COMPLETE.txt"):
        p = out_dir / name
        if p.exists():
            p.unlink()


def transcribe(
    path: Path,
    aid: str,
    *,
    model_size: str = "small",
    caption_hint: str | None = None,
) -> tuple[list[dict], str]:
    from faster_whisper import WhisperModel

    out_dir = DATA / "transcripts"
    out_dir.mkdir(parents=True, exist_ok=True)
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    # No initial_prompt: on sparse/music-heavy TikTok audio it can be hallucinated as fake speech.
    segments, info = model.transcribe(
        str(path),
        language="en",
        beam_size=5,
        condition_on_previous_text=True,
        vad_filter=False,
    )
    rows = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segments]
    full_text = " ".join(r["text"] for r in rows if r["text"]).strip()
    if is_garbage_transcript(full_text, caption_hint=caption_hint):
        remove_transcript_artifacts(aid)
        print(f" skip low-signal transcript (carousel/music-only?) {aid}")
        return [], ""
    payload = {
        "video_id": aid,
        "source_media": path.name,
        "whisper_model": model_size,
        "language": getattr(info, "language", None),
        "duration_after_vad": getattr(info, "duration", None),
        "full_text": full_text,
        "segments": rows,
    }
    (out_dir / f"{aid}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [f"[{r['start']:.1f}-{r['end']:.1f}] {r['text']}" for r in rows]
    (out_dir / f"{aid}.txt").write_text("\n".join(lines), encoding="utf-8")
    (out_dir / f"{aid}_FULL.txt").write_text(full_text + ("\n" if full_text else ""), encoding="utf-8")
    return rows, full_text


def write_complete_transcript(
    aid: str,
    full_text: str,
    *,
    title: str | None,
    description: str | None,
    webpage_url: str | None = None,
) -> None:
    """Spoken text plus official TikTok copy (needed when slideshow audio has no real speech)."""
    out_dir = DATA / "transcripts"
    lines = [
        f"video_id: {aid}\n",
        f"url: {webpage_url or tt_url(aid)}\n",
        "\n",
        "## Spoken transcript (Whisper automatic speech recognition, English)\n",
        (full_text.strip() if full_text.strip() else "(No clear speech detected in the downloaded audio track.)"),
        "\n",
    ]
    t = (title or "").strip()
    d = (description or "").strip()
    if t or d:
        lines.append("\n## TikTok title and description (verbatim from post metadata)\n\n")
        # TikTok `title` is often a truncated duplicate of `description`; prefer full description.
        if d and t:
            td = t.rstrip("….").strip()
            if d.startswith(td) or td in d[:120]:
                lines.append(d.rstrip() + "\n")
            else:
                lines.append(f"{t}\n\n{d.rstrip()}\n")
        elif d:
            lines.append(d.rstrip() + "\n")
        else:
            lines.append(t + "\n")
    (out_dir / f"{aid}_COMPLETE.txt").write_text("".join(lines), encoding="utf-8")


def ensure_complete_transcript(aid: str, meta: dict) -> None:
    """Build {id}_COMPLETE.txt from latest transcript JSON + TikTok metadata."""
    jp = DATA / "transcripts" / f"{aid}.json"
    if not jp.exists():
        ct = DATA / "transcripts" / f"{aid}_COMPLETE.txt"
        if ct.exists():
            ct.unlink()
        return
    data = json.loads(jp.read_text(encoding="utf-8"))
    full_text = data.get("full_text")
    if full_text is None and isinstance(data, list):
        full_text = " ".join(s.get("text", "") for s in data).strip()
    write_complete_transcript(
        aid,
        full_text or "",
        title=meta.get("title"),
        description=meta.get("description"),
        webpage_url=meta.get("webpage_url"),
    )


def main():
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--skip-download", action="store_true")
    p.add_argument("--skip-transcribe", action="store_true")
    p.add_argument(
        "--force-transcribe",
        action="store_true",
        help="Overwrite existing transcript files",
    )
    p.add_argument(
        "--whisper-model",
        default="small",
        help="faster-whisper model: tiny, base, small, medium, large-v3, ...",
    )
    args = p.parse_args()

    metrics = []
    for aid, label in VIDEOS:
        print("meta", aid)
        meta = run_yt_dlp_json(aid)
        views = int(meta.get("view_count") or 0)
        likes = int(meta.get("like_count") or 0)
        comments = int(meta.get("comment_count") or 0)
        shares = int(meta.get("repost_count") or 0)
        saves = int(str(meta.get("save_count") or "0").replace(",", "") or 0)
        dur = float(meta.get("duration") or 0)
        metrics.append(
            {
                "video_id": aid,
                "label": label,
                "url": tt_url(aid),
                "title": meta.get("title"),
                "description": meta.get("description"),
                "duration_sec": dur,
                "view_count": views,
                "like_count": likes,
                "comment_count": comments,
                "share_count": shares,
                "save_count": saves,
                "like_per_1k_views": round(1000 * likes / views, 4) if views else None,
                "comment_per_1k_views": round(1000 * comments / views, 4) if views else None,
                "share_per_1k_views": round(1000 * shares / views, 4) if views else None,
                "save_per_1k_views": round(1000 * saves / views, 4) if views else None,
            }
        )
        media_path = existing_media(aid)
        if not args.skip_download:
            if media_path is None:
                try:
                    media_path = download_media(aid)
                    print(" downloaded", media_path.name)
                except subprocess.CalledProcessError:
                    print(" download failed", aid)
                    continue
            else:
                print(" skip download exists", aid)
        if not args.skip_transcribe:
            tr_path = DATA / "transcripts" / f"{aid}.txt"
            if tr_path.exists() and not args.force_transcribe:
                print(" skip transcribe exists", aid)
            else:
                try:
                    use = media_path or existing_media(aid)
                    if use is None:
                        use = download_media(aid)
                    print(" transcribe", aid, f"model={args.whisper_model}")
                    transcribe(
                        use,
                        aid,
                        model_size=args.whisper_model,
                        caption_hint=meta.get("description"),
                    )
                except Exception as e:
                    print(" transcribe error", aid, e)
        ensure_complete_transcript(aid, meta)

    metrics.sort(key=lambda x: x["view_count"] or 0, reverse=True)
    (DATA / "metrics_refresh.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("wrote", DATA / "metrics_refresh.json")


if __name__ == "__main__":
    main()
