"""Whisper writes out a grocery recording, here on the server.

The same setup as the GTD tracker and the shop app (faster-whisper on the CPU,
int8): the audio never leaves the Pi, and the model is downloaded once into
WHISPER_DIR (the stack shares the shop's whisper_models folder). medium.en
holds about 2 GB while loaded, so it's dropped whenever the queue runs empty.
WHISPER_MODEL=small.en is about three times faster; "off" turns recordings off
(they wait in the queue).

faster-whisper is optional: without it the app runs normally and recordings
just wait.
"""
import gc
import logging
import os
from pathlib import Path

WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "medium.en")
WHISPER_DIR = Path(os.environ.get("WHISPER_DIR", Path(__file__).resolve().parent.parent / "whisper_models"))

log = logging.getLogger("grocery.transcribe")
_model = None
_said_why = False


def available():
    global _said_why
    if WHISPER_MODEL == "off":
        return False
    try:
        import faster_whisper  # noqa: F401
        return True
    except Exception as e:
        if not _said_why:
            log.warning("Recordings will wait: faster-whisper won't load (%s: %s)", type(e).__name__, e)
            _said_why = True
        return False


def _get_model():
    global _model
    if _model is None:
        from faster_whisper import WhisperModel
        WHISPER_DIR.mkdir(parents=True, exist_ok=True)
        # Leave a core free so the pages and the other apps stay responsive.
        threads = int(os.environ.get("WHISPER_THREADS", max(1, (os.cpu_count() or 2) - 1)))
        _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8",
                              cpu_threads=threads, download_root=str(WHISPER_DIR))
    return _model


def unload():
    global _model
    if _model is not None:
        _model = None
        gc.collect()


def prompt_for(names):
    """Whisper's spelling hint: the most-bought catalog names. Whisper only
    reads the last ~224 tokens of a prompt, so keep it short."""
    hint = "A grocery list. "
    for n in names:
        if len(hint) + len(n) > 700:
            break
        hint += n.lower() + ", "
    return hint.rstrip(", ") + "."


def transcribe_file(path, prompt=""):
    """Plain transcript text of one audio file."""
    segments, _info = _get_model().transcribe(
        str(path),
        beam_size=5,
        vad_filter=True,
        initial_prompt=prompt or None,
        condition_on_previous_text=False,  # with a prompt, True can loop and drop sentences
    )
    return " ".join(s.text.strip() for s in segments).strip()
