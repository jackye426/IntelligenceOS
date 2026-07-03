"""Tests for pipeline data bootstrap."""

from __future__ import annotations

import io
import tarfile

from marketing_pipeline.bootstrap import seed_from_github


def test_seed_from_github_tarball(tmp_path, monkeypatch):
    from marketing_pipeline import config

    data_root = tmp_path / "data"
    trans = data_root / "transcripts"
    trans.mkdir(parents=True)
    master = trans / "ALL_COMPLETE_TRANSCRIPTS.txt"

    monkeypatch.setattr(config, "DATA_ROOT", data_root)
    monkeypatch.setattr(config, "TRANSCRIPTS_DIR", trans)
    monkeypatch.setattr(config, "MASTER_TRANSCRIPTS", master)
    monkeypatch.setattr(config, "CATALOG_DIR", data_root / "catalog")
    monkeypatch.setattr(config, "COMMENTS_RAW_DIR", data_root / "comments_raw")
    monkeypatch.setattr(config, "ANALYSIS_DIR", data_root / "analysis")
    monkeypatch.setattr(config, "EXPORTS_DIR", data_root / "exports")
    monkeypatch.setattr(config, "PLAYBOOKS_DIR", data_root / "playbooks")
    monkeypatch.setattr(config, "MEDIA_DIR", data_root / "media")
    monkeypatch.setattr(config, "OCR_CACHE_DIR", data_root / "ocr")
    monkeypatch.setattr(config, "YT_META_DIR", data_root / "yt_meta")

    buf = io.BytesIO()
    inner = "IntelligenceOS-main/marketing-pipeline/tiktok/data/transcripts/ALL_COMPLETE_TRANSCRIPTS.txt"
    payload = b"VIDEO 1\nvideo_id: 1\n"
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        info = tarfile.TarInfo(name=inner)
        info.size = len(payload)
        tar.addfile(info, io.BytesIO(payload))
    buf.seek(0)

    class FakeResponse:
        content = buf.getvalue()

        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert "codeload.github.com" in url
            return FakeResponse()

    import marketing_pipeline.bootstrap as mod

    monkeypatch.setattr(mod.httpx, "Client", FakeClient)

    assert seed_from_github() is True
    assert master.exists()
    assert b"VIDEO 1" in master.read_bytes()
