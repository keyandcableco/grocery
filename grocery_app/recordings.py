"""Grocery rambles sent as audio: saved at once, written out by Whisper and
sorted onto the list by one background worker.

gunicorn runs two worker processes; a lock file makes sure only one of them
runs the recording worker (one Whisper model in memory, never the same
recording twice). Either process can take a recording or wait for its
result: they meet in the database.
"""
import fcntl
import logging
import os
import re
import threading
import time
import uuid

from .models import db, Item, Recording
from . import transcribe

log = logging.getLogger("grocery.recordings")

AUDIO_EXTS = {"audio/mp4": ".m4a", "audio/m4a": ".m4a", "audio/x-m4a": ".m4a", "audio/aac": ".aac",
              "audio/3gpp": ".3gp", "audio/amr": ".amr", "audio/ogg": ".ogg", "audio/opus": ".opus",
              "audio/webm": ".webm", "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/mpeg": ".mp3",
              "audio/flac": ".flac"}

_dir = None
_lock_file = None  # held open for the life of the process that runs the worker
_worker_started = False


def init(app):
    global _dir
    _dir = os.environ.get("RECORDINGS_DIR") or os.path.join(app.instance_path, "recordings")
    os.makedirs(_dir, exist_ok=True)


def speech_to_text():
    return transcribe.available()


def save(data, name="", ctype=""):
    """Keep the audio and queue it. -> the Recording (committed)."""
    ext = os.path.splitext(name)[1].lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
        ext = AUDIO_EXTS.get(ctype, ".audio")
    audio = f"{uuid.uuid4()}{ext}"
    with open(os.path.join(_dir, audio), "wb") as f:
        f.write(data)
    rec = Recording(audio=audio, status="queued")
    db.session.add(rec)
    db.session.commit()
    return rec


def wait_for(rid, seconds):
    """The recording once it's filed or failed, or as it stands after `seconds`."""
    end = time.monotonic() + seconds
    while True:
        db.session.expire_all()
        rec = db.session.get(Recording, rid)
        if rec.status in ("filed", "failed") or time.monotonic() >= end:
            return rec
        time.sleep(1)


def retry(rid):
    n = (Recording.query.filter_by(id=rid, status="failed")
         .update({"status": "queued", "error": "", "attempts": 0}))
    db.session.commit()
    return bool(n)


def process_next():
    """Write out and sort the oldest waiting recording. False when none waits.
    The transcript is kept as soon as it's made, so a recording cut off while
    Haiku reads it isn't written out again; its list entries and its "filed"
    land in one commit."""
    from .views import read_spoken, add_spoken  # views imports this module
    rec = Recording.query.filter_by(status="queued").order_by(Recording.created_at, Recording.id).first()
    if rec is None:
        return False
    rec.status, rec.error, rec.attempts = "transcribing", "", (rec.attempts or 0) + 1
    db.session.commit()
    try:
        if not rec.text:
            names = [it.name for it in Item.query.filter_by(active=True)
                     .order_by(Item.times_added.desc()).all()]
            text = transcribe.transcribe_file(os.path.join(_dir, rec.audio), transcribe.prompt_for(names))
            if not text:
                rec.status, rec.error = "failed", "Whisper heard no words in the recording"
                db.session.commit()
                return True
            rec.text = text
            db.session.commit()
        entries, reader = read_spoken(rec.text, wait=60)  # nobody's holding a phone call open
        reply = add_spoken(entries, allow_new=(reader == "haiku"))
        rec.status, rec.reader, rec.summary = "filed", reader, reply["summary"]
        db.session.commit()
    except Exception as e:
        db.session.rollback()  # no half-added list
        log.exception("recording %s failed", rec.id)
        rec = db.session.get(Recording, rec.id)
        rec.status, rec.error = "failed", (str(e)[:300] or type(e).__name__)
        db.session.commit()
    return True


def requeue_interrupted():
    """Recordings cut off by a restart go back in the queue, except one cut off
    twice: it may be what's crashing the app (out of memory, a bad file)."""
    Recording.query.filter(Recording.status == "transcribing", Recording.attempts >= 2,
                           (Recording.text == "") | (Recording.text.is_(None))).update(
        {"status": "failed",
         "error": "Stopped twice while being written out (the app restarted or ran out of memory)."})
    Recording.query.filter_by(status="transcribing").update({"status": "queued"})
    db.session.commit()


def _worker(app):
    while True:
        try:
            with app.app_context():
                busy = process_next()
            if not busy:
                transcribe.unload()  # give the memory back until the next recording
                time.sleep(3)  # the other gunicorn process can't wake this thread, so poll
        except Exception:  # never let the worker die
            log.exception("recording worker")
            time.sleep(30)
            try:  # a row left "transcribing" by a failed commit: only this thread transcribes
                with app.app_context():
                    Recording.query.filter_by(status="transcribing").update({"status": "queued"})
                    db.session.commit()
            except Exception:
                log.exception("recording worker: requeue")


def _elect_and_run(app):
    """Wait for the lock (the other gunicorn process may hold it, and give it
    up when it exits or is reloaded), then be the one worker."""
    global _lock_file
    f = open(os.path.join(_dir, ".worker.lock"), "w")
    fcntl.flock(f, fcntl.LOCK_EX)  # blocks this thread only
    _lock_file = f
    with app.app_context():
        requeue_interrupted()
    _worker(app)


def start_worker(app):
    """Start the worker once per machine (not without Whisper: recordings wait)."""
    global _worker_started
    if _worker_started or not transcribe.available():
        return
    threading.Thread(target=_elect_and_run, args=(app,), name="recording-worker", daemon=True).start()
    _worker_started = True
