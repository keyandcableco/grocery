"""Claude Haiku turns a grocery ramble into list entries.

"uh we need milk, a couple onions, the good bread, and we're low on that
almond milk" -> MILK, 2 ONIONS, ... matched to the names already in the
catalog, with a store category picked for anything new.

Same pattern as the GTD tracker's tagger.py: nothing here is required. With
no ANTHROPIC_API_KEY, no internet, an error or a refusal, views.py falls back
to the word rules in voice.py, so a capture is never lost. Only the spoken
text, the catalog names and the category names go to Anthropic.

Capture only: Haiku can put things on the list, never take them off.
"""
import concurrent.futures
import json
import os

MODEL = "claude-haiku-5-5"

_client = None
# The call runs here so the caller's wait is a hard limit (the SDK's own
# timeout doesn't cover the DNS lookup).
_pool = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="haiku")


def _api_key():
    return (os.environ.get("ANTHROPIC_API_KEY") or "").strip()


def available():
    """True when a key is set and the SDK is installed."""
    if not _api_key():
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except Exception:
        return False


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=_api_key(), max_retries=0)
    return _client


def system_prompt(catalog, categories):
    return "\n".join([
        "You turn Greg's spoken grocery ramble into grocery list entries. It may be a transcript "
        "with filler words, false starts and misheard words.",
        "Return one entry per thing he wants to buy, in the order said. Leave out anything he "
        "says he doesn't need, already has, or takes back (\"no wait, not eggs\"). Never leave "
        "something out because it's vague or not in the catalog: then it's a new item.",
        "",
        "Matching: if the thing is in the catalog below, set catalog_name to that catalog name "
        "copied exactly, even when he says it differently (\"ground chicken\" = CHICKEN GROUND, "
        "\"tomato\" = TOMATOES, \"the good bread\" = a bread in the catalog if there's one clear "
        "fit). It must be the same product, not one that shares a word: almond milk is not MILK, "
        "bread is not BREAD FLOUR or BREADCRUMBS. If nothing "
        "in the catalog fits, leave catalog_name empty, set new_name to a short name in capitals "
        "in the catalog's style without filler like \"the good\" (\"the good bread\" -> BREAD, "
        "\"that almond milk\" -> ALMOND MILK), and pick its category from the list. For a catalog match, new_name is empty and category is \"\".",
        "",
        "qty: only an amount he says, short, like \"2\", \"1 bag\", \"2 lbs\", \"a dozen\" -> "
        "\"12\", \"a couple\" -> \"2\", \"a few\" -> \"3\". Leave it empty when he doesn't say one "
        "(\"some milk\", \"milk\", \"a milk\").",
        "",
        "Catalog (one name per line):",
        *catalog,
        "",
        "Categories: " + ", ".join(categories),
    ])


def output_schema(categories):
    entry = {
        "type": "object",
        "properties": {
            "catalog_name": {"type": "string"},
            "new_name": {"type": "string"},
            "qty": {"type": "string"},
            "category": {"type": "string", "enum": [*categories, ""]},
        },
        "required": ["catalog_name", "new_name", "qty", "category"],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"items": {"type": "array", "items": entry}},
            "required": ["items"], "additionalProperties": False}


def _ask_haiku(text, catalog, categories, wait):
    import anthropic
    try:
        response = _get_client().with_options(timeout=wait).messages.create(
            model=MODEL,
            max_tokens=4000,
            output_config={"effort": "low", "format": {"type": "json_schema",
                                                       "schema": output_schema(categories)}},
            system=system_prompt(catalog, categories),
            messages=[{"role": "user", "content": f"Greg's grocery ramble:\n{text}"}],
        )
    except anthropic.APIError as e:
        raise RuntimeError(f"{type(e).__name__}: {e}"[:300]) from e
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"Haiku stopped early ({response.stop_reason})")
    answer = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(answer)
    except ValueError as e:
        raise RuntimeError("Haiku's answer wasn't valid JSON") from e


MAX_ITEMS = 60  # one ramble never adds more


def to_entries(answer, catalog, categories):
    """Haiku's answer -> [(catalog_name or None, new_name or None, qty or None, category or None)].

    A catalog_name that isn't really in the catalog (case aside) is treated as
    a new name, so a made-up match can't point at nothing."""
    by_lower = {n.lower(): n for n in catalog}
    cats = {c.lower(): c for c in categories}
    out = []
    for raw in (answer.get("items") or [])[:MAX_ITEMS]:
        if not isinstance(raw, dict):
            continue
        clean = lambda k: " ".join(str(raw.get(k) or "").split())
        name, new, qty = clean("catalog_name"), clean("new_name"), clean("qty")
        hit = by_lower.get(name.lower()) if name else None
        if not hit:
            new = (new or name).upper()
            hit = by_lower.get(new.lower())  # Haiku called a catalog item "new"
        if hit:
            out.append((hit, None, qty or None, None))
        elif new:
            out.append((None, new[:80], qty or None, cats.get(clean("category").lower())))
    return out


def read(text, catalog, categories, wait=30):
    """The entries in this ramble (possibly none), or raises RuntimeError."""
    if not available():
        raise RuntimeError("no Anthropic API key set")
    job = _pool.submit(_ask_haiku, text, list(catalog), list(categories), wait)
    try:
        answer = job.result(timeout=wait + 5)
    except concurrent.futures.TimeoutError:
        raise RuntimeError(f"no answer from Haiku in {wait} s") from None
    return to_entries(answer, catalog, categories)
