from marketing_pipeline.tiktok.stages.collect_comments import needs_refresh
from marketing_pipeline.tiktok.stages.import_playbooks import import_playbooks
from marketing_pipeline.tiktok.sync.playbooks import _parse_frontmatter


def test_needs_refresh_missing_file(tmp_path, monkeypatch):
    from marketing_pipeline import config

    monkeypatch.setattr(config, "COMMENTS_RAW_DIR", tmp_path)
    assert needs_refresh("123") is True


def test_frontmatter_skips_draft():
    text = "---\nstatus: draft\n---\n\nBody"
    meta, body = _parse_frontmatter(text)
    assert meta["status"] == "draft"
    assert "Body" in body


def test_import_playbooks_creates_index(tmp_path, monkeypatch):
    from marketing_pipeline import config

    monkeypatch.setattr(config, "PLAYBOOKS_DIR", tmp_path)
    monkeypatch.setattr(config, "ANALYSIS_DIR", tmp_path / "analysis")
    src = tmp_path / "instruction.txt"
    src.write_text("Create high-intent patient action videos.", encoding="utf-8")

    from marketing_pipeline.tiktok.stages import import_playbooks as mod

    result = mod.import_playbooks({"content-instruction.md": src})
    assert "content-instruction.md" in result
    assert (tmp_path / "playbook_index.json").exists()
