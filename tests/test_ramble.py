"""Ramble capture: Haiku's answer, the rules fallback, and recordings.

Run: .venv/bin/python -m unittest discover tests
Haiku and Whisper are faked here; no key or model is needed.
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.pop("ANTHROPIC_API_KEY", None)

from grocery_app import create_app, sorter, recordings, transcribe  # noqa: E402
from grocery_app.config import Config  # noqa: E402
from grocery_app.models import db, Item, ListItem, Recording  # noqa: E402

CATALOG = ["MILK", "ONIONS", "SOURDOUGH BREAD", "CHICKEN GROUND", "HALF N HALF", "EGGS"]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["RECORDINGS_DIR"] = self.tmp.name

        class C(Config):
            TESTING = True
            SQLALCHEMY_DATABASE_URI = "sqlite:///" + os.path.join(self.tmp.name, "t.db")
            APP_PASSWORD = None
        self.app = create_app(C)
        self.client = self.app.test_client()
        with self.app.app_context():
            for n in CATALOG:
                db.session.add(Item(name=n, category="Dairy", source="local"))
            db.session.commit()

    def tearDown(self):
        os.environ.pop("RECORDINGS_DIR", None)
        with self.app.app_context():
            db.session.remove()
            db.engine.dispose()
        self.tmp.cleanup()

    def on_list(self):
        with self.app.app_context():
            return {li.item.name: li.qty for li in ListItem.query.all()}


class ToEntries(unittest.TestCase):
    cats = ["Produce", "Dairy", "Other"]

    def test_matches_case_and_drops_made_up_catalog_names(self):
        answer = {"items": [
            {"catalog_name": "milk", "new_name": "", "qty": "2", "category": ""},
            {"catalog_name": "OAT MILK", "new_name": "", "qty": "", "category": "Dairy"},
            {"catalog_name": "", "new_name": "onions", "qty": "", "category": "Produce"},
            {"catalog_name": "", "new_name": "", "qty": "", "category": ""},
            {"catalog_name": "", "new_name": "leeks", "qty": "", "category": "Nope"},
        ]}
        self.assertEqual(sorter.to_entries(answer, CATALOG, self.cats), [
            ("MILK", None, "2", None),
            (None, "OAT MILK", None, "Dairy"),   # not in the catalog: new, not a dangling match
            ("ONIONS", None, None, None),        # Haiku said "new" but it's there
            (None, "LEEKS", None, None),         # unknown category -> None (Other later)
        ])


class Capture(Base):
    def test_haiku_reads_the_ramble(self):
        entries = [("MILK", None, None, None), ("ONIONS", None, "2", None),
                   ("SOURDOUGH BREAD", None, None, None), (None, "ALMOND MILK", None, "Dairy")]
        with mock.patch.object(sorter, "available", return_value=True), \
                mock.patch.object(sorter, "read", return_value=entries) as read:
            r = self.client.post("/api/capture", data="uh we need milk, a couple onions, "
                                 "the good bread and almond milk", content_type="text/plain")
        self.assertEqual(r.status_code, 201)
        body = r.get_json()
        self.assertEqual(body["reader"], "haiku")
        self.assertEqual(body["new"], ["ALMOND MILK"])
        self.assertIn("2 onions", body["summary"])
        self.assertIn("CHICKEN GROUND", read.call_args[0][1])  # the catalog went to Haiku
        self.assertEqual(self.on_list(), {"MILK": "1", "ONIONS": "2", "SOURDOUGH BREAD": "1",
                                          "ALMOND MILK": "1"})
        with self.app.app_context():
            self.assertEqual(Item.query.filter_by(name="ALMOND MILK").one().category, "Dairy")

    def test_falls_back_to_rules_when_haiku_fails(self):
        with mock.patch.object(sorter, "available", return_value=True), \
                mock.patch.object(sorter, "read", side_effect=RuntimeError("down")):
            r = self.client.post("/api/capture", json={"text": "two milks and ground chicken"})
        self.assertEqual(r.get_json()["reader"], "rules")
        self.assertEqual(self.on_list(), {"MILK": "2", "CHICKEN GROUND": "1"})

    def test_no_key_uses_rules(self):
        r = self.client.post("/api/capture", data="eggs and half and half", content_type="text/plain")
        self.assertEqual(r.get_json()["reader"], "rules")
        self.assertEqual(set(self.on_list()), {"EGGS", "HALF N HALF"})

    def test_same_item_twice_in_one_ramble(self):
        entries = [("MILK", None, None, None), ("MILK", None, "2", None),
                   (None, "LEEKS", None, None), (None, "leeks", None, None)]
        with mock.patch.object(sorter, "available", return_value=True), \
                mock.patch.object(sorter, "read", return_value=entries):
            r = self.client.post("/api/capture", data="x", content_type="text/plain")
        self.assertEqual(r.status_code, 201)
        self.assertEqual(self.on_list(), {"MILK": "2", "LEEKS": "1"})

    def test_empty(self):
        self.assertEqual(self.client.post("/api/capture", data="", content_type="text/plain").status_code, 400)


class Recordings(Base):
    def post(self, **kw):
        return self.client.post("/api/record", data=b"fake audio", content_type="audio/mp4", **kw)

    def test_queued_then_filed(self):
        with mock.patch.object(transcribe, "available", return_value=True):
            r = self.post()
        self.assertEqual(r.status_code, 202)
        self.assertIn("Got it", r.get_json()["summary"])
        rid = r.get_json()["id"]
        with self.app.app_context():
            rec = db.session.get(Recording, rid)
            self.assertTrue(os.path.exists(os.path.join(self.tmp.name, rec.audio)))
            self.assertTrue(rec.audio.endswith(".m4a"))
            with mock.patch.object(transcribe, "transcribe_file", return_value="milk and eggs"):
                self.assertTrue(recordings.process_next())
            self.assertFalse(recordings.process_next())
            rec = db.session.get(Recording, rid)
            self.assertEqual((rec.status, rec.text, rec.reader), ("filed", "milk and eggs", "rules"))
            self.assertIn("added", rec.summary)
        self.assertEqual(set(self.on_list()), {"MILK", "EGGS"})
        listing = self.client.get("/api/recordings").get_json()["recordings"]
        self.assertEqual(listing[0]["status"], "filed")

    def test_wait_returns_the_result(self):
        def fake_wait(rid, seconds):  # what the worker in the other process would have done
            with mock.patch.object(transcribe, "transcribe_file", return_value="onions"):
                recordings.process_next()
            return db.session.get(Recording, rid)
        with mock.patch.object(recordings, "wait_for", side_effect=fake_wait) as w:
            r = self.post(query_string={"wait": "500"})
        self.assertEqual(w.call_args[0][1], 75)  # capped
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.get_json()["summary"], "added onions")

    def test_silence_fails_and_retry_requeues(self):
        rid = self.post().get_json()["id"]
        with self.app.app_context():
            with mock.patch.object(transcribe, "transcribe_file", return_value=""):
                recordings.process_next()
            self.assertEqual(db.session.get(Recording, rid).status, "failed")
        self.assertEqual(self.client.post(f"/api/recordings/{rid}/retry").status_code, 200)
        self.assertEqual(self.client.post(f"/api/recordings/{rid}/retry").status_code, 404)

    def test_error_keeps_transcript_and_adds_nothing(self):
        rid = self.post().get_json()["id"]
        with self.app.app_context():
            with mock.patch.object(transcribe, "transcribe_file", return_value="milk"), \
                    mock.patch("grocery_app.views.add_spoken", side_effect=RuntimeError("boom")):
                recordings.process_next()
            rec = db.session.get(Recording, rid)
            self.assertEqual((rec.status, rec.text, rec.error), ("failed", "milk", "boom"))
        self.assertEqual(self.on_list(), {})

    def test_interrupted_requeued_twice_then_failed(self):
        with self.app.app_context():
            a = Recording(audio="a.m4a", status="transcribing", attempts=1)
            b = Recording(audio="b.m4a", status="transcribing", attempts=2)
            db.session.add_all([a, b])
            db.session.commit()
            recordings.requeue_interrupted()
            self.assertEqual((a.status, b.status), ("queued", "failed"))

    def test_empty_body(self):
        r = self.client.post("/api/record", data=b"", content_type="audio/mp4")
        self.assertEqual(r.status_code, 400)


class Prompt(unittest.TestCase):
    def test_whisper_prompt_is_capped(self):
        p = transcribe.prompt_for([f"ITEM NUMBER {i}" for i in range(500)])
        self.assertLess(len(p), 760)
        self.assertTrue(p.startswith("A grocery list. item number 0"))

    def test_haiku_schema_and_prompt(self):
        s = sorter.output_schema(["Produce", "Other"])
        self.assertEqual(s["properties"]["items"]["items"]["properties"]["category"]["enum"],
                         ["Produce", "Other", ""])
        self.assertIn("MILK", sorter.system_prompt(CATALOG, ["Produce"]))


if __name__ == "__main__":
    unittest.main()
