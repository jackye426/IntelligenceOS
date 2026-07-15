"""Smoke tests for pipeline job helpers (no network)."""

from gtm_pipeline.pipeline_jobs import get_job, list_jobs, start_job


def test_start_job_completes():
    def _fn():
        return {"ok": True, "n": 1}

    job_id = start_job("test", _fn, meta={"x": 1})
    # Wait briefly for daemon thread
    import time

    for _ in range(50):
        job = get_job(job_id)
        assert job is not None
        if job["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    job = get_job(job_id)
    assert job is not None
    assert job["status"] == "completed"
    assert job["result"] == {"ok": True, "n": 1}
    assert any(j["id"] == job_id for j in list_jobs())
