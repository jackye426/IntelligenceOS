import unittest
from urllib.error import HTTPError
from unittest.mock import patch
import social_metrics as job

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.rows = {
            "tiktok": [{"id":"123456", "view_count":0, "like_count":9, "timestamp":1795342752},
                       {"id":"123457", "view_count":20, "timestamp":1795342752}],
            "instagram": [{"id":"345678", "shortcode":"aBc_1", "likes":7, "timestamp":1795342752}]
        }

    def fetch(self, platform):
        return lambda handle: self.rows[platform]

    def save(self, platform, handle, observation, captured_at):
        self.events.append(("save", platform, handle, observation[-1], captured_at))

    def run_refresh(self, **kwargs):
        return job.refresh(save=self.save, clock=lambda: "2026-11-23T00:00:00Z",
                           fetchers=kwargs.pop("fetchers", {p:self.fetch(p) for p in job.TARGETS}),
                           **kwargs)

    def test_every_count_is_saved_before_embedding_401(self):
        def embed():
            self.events.append(("embed",))
            raise HTTPError("https://example.invalid", 401, "unauthorized", {}, None)
        actual = self.run_refresh(enrich=embed)
        self.assertEqual(self.events[-1], ("embed",))
        self.assertEqual(len(self.events), 7)
        self.assertEqual({(e[1],e[2]) for e in self.events[:-1]},
            {("tiktok","docmap"),("tiktok","endobowelsurgeon"),
             ("instagram","docmapuk"),("instagram","endobowelsurgeon")})
        self.assertIn({"views":0,"likes":9}, [e[3] for e in self.events[:-1]])
        self.assertEqual(actual["enrichment"], {"status":"failed","error_type":"HTTPError"})
        self.assertTrue(all(v["status"]=="saved" for k,v in actual.items() if k!="enrichment"))

    def test_fetch_error_and_missing_counts_do_not_stamp_freshness(self):
        def tiktok(handle):
            if handle == "docmap":
                raise RuntimeError("fetch failed")
            return [{"id":"123456", "view_count":None}]
        actual = self.run_refresh(
            enrich=lambda:self.fail("don't enrich old cached artifacts"),
            fetchers={"tiktok":tiktok, "instagram":self.fetch("instagram")})
        self.assertEqual(actual["tiktok:docmap"]["status"], "fetch_failed")
        self.assertEqual(actual["tiktok:endobowelsurgeon"]["status"], "no_fresh_observations")
        self.assertEqual(len(self.events),2)
        self.assertTrue(all(e[1]=="instagram" for e in self.events))

    def test_existing_third_party_tiktok_backend(self):
        with patch.object(job.subprocess, "check_output",return_value=b'{"entries": []}') as run:
            job.tiktok_posts("endobowelsurgeon")
        cmd = run.call_args.args[0]
        self.assertIn("yt_dlp",cmd)
        self.assertIn("https://www.tiktok.com/@endobowelsurgeon",cmd)

if __name__ == "__main__":
    unittest.main()
