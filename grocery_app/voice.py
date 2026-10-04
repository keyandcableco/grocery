"""Turn a spoken sentence into grocery list entries.

"we need two milks, ground chicken and a bag of tortilla chips" ->
    [("MILK", "2"), ("CHICKEN GROUND", None), ("TORTILLA CHIPS", "1 bag")]

Speech is matched against the catalog, not trusted as-is:
- plurals and word order don't matter ("ground chicken" finds CHICKEN GROUND,
  "tomato" finds TOMATOES, "half and half" finds HALF N HALF);
- names with "and" in them survive the split on "and";
- an unbroken run of catalog names with no "and" between them ("eggs milk
  bread") still splits into separate items.
Anything that doesn't match comes back as a new name, in the words spoken.
"""
import re

SEPARATORS = {",", "and", "also", "plus", "then", "&"}
FILLERS = {"some", "more", "of", "the", "few", "bit", "like", "uh", "um",
           "maybe", "another", "too", "please", "little", "extra"}
LEAD_PHRASES = [  # stripped from the start, longest first
    "can you add", "could you add", "please add", "add", "put", "we need",
    "i need", "need", "we're out of", "were out of", "we are out of",
    "out of", "get", "buy", "grab", "pick up", "we need to get",
]
TAIL_PHRASES = [  # stripped from the end
    "to the grocery list", "to the shopping list", "to the list",
    "on the grocery list", "on the list", "to my list", "to groceries",
    "to grocery", "to the groceries", "please",
]
NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}
UNITS = {  # singular form -> plural for display
    "bag": "bags", "box": "boxes", "can": "cans", "bottle": "bottles",
    "jar": "jars", "pack": "packs", "package": "packages", "carton": "cartons",
    "gallon": "gallons", "pound": "lbs", "lb": "lbs", "loaf": "loaves",
    "loave": "loaves", "bunch": "bunches", "head": "heads", "bar": "bars",
    "block": "blocks", "tub": "tubs", "container": "containers",
}


def singular(w):
    if len(w) <= 3 or w.endswith(("ss", "us", "is")):
        return w
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith(("ches", "shes", "xes", "zes", "sses", "oes")):
        return w[:-2]
    if w.endswith("s"):
        return w[:-1]
    return w


def tokenize(text):
    """-> [(normalized, raw)], commas kept as ',' tokens."""
    text = text.lower().replace("&", " and ").replace("-", " ")
    text = re.sub(r"['’]", "", text)
    text = re.sub(r"[,.;:!?]", " , ", text)
    text = re.sub(r"[^a-z0-9, ]", " ", text)
    out = []
    for raw in text.split():
        norm = "," if raw == "," else singular(raw)
        if norm == "n":  # HALF N HALF
            norm = "and"
        out.append((norm, raw))
    return out


def name_keys(norm_words):
    """Lookup keys for a run of normalized words: any word order, or run together."""
    return (" ".join(sorted(norm_words)), "".join(norm_words))


def build_index(items):
    """items: iterable of (name, rank). Higher rank wins a key collision."""
    index, longest, best = {}, 1, {}
    for name, rank in items:
        words = [n for n, _ in tokenize(name) if n != ","]
        if not words:
            continue
        longest = max(longest, len(words))
        for key in name_keys(words):
            if key not in best or rank > best[key]:
                index[key], best[key] = name, rank
    return index, longest


def _strip_phrases(toks):
    norms = lambda: [n for n, _ in toks]
    changed = True
    while changed and toks:
        changed = False
        while toks and toks[0][0] == ",":
            toks, changed = toks[1:], True
        while toks and toks[-1][0] == ",":
            toks, changed = toks[:-1], True
        for p in sorted(LEAD_PHRASES, key=len, reverse=True):
            pw = [singular(w) for w in p.split()]
            if norms()[:len(pw)] == pw and len(toks) > len(pw):
                toks, changed = toks[len(pw):], True
                break
        for p in sorted(TAIL_PHRASES, key=len, reverse=True):
            pw = [singular(w) for w in p.split()]
            if len(toks) > len(pw) and norms()[-len(pw):] == pw:
                toks, changed = toks[:-len(pw)], True
                break
    return toks


def _protect(toks, index, longest):
    """Glue catalog names that contain a separator word into one token."""
    out, i = [], 0
    while i < len(toks):
        for m in range(min(longest, len(toks) - i), 1, -1):
            span = [n for n, _ in toks[i:i + m]]
            if SEPARATORS & set(span) and span[0] not in SEPARATORS \
                    and span[-1] not in SEPARATORS \
                    and any(k in index for k in name_keys(span)):
                out.append((" ".join(span), " ".join(r for _, r in toks[i:i + m])))
                i += m
                break
        else:
            out.append(toks[i])
            i += 1
    return out


def _parse_qty(toks, i):
    """Read an optional leading quantity. -> (qty string or None, next index)."""
    n, j, unit = None, i, None
    word = lambda k: toks[k][0] if k < len(toks) else None
    if word(j) and word(j).isdigit():
        n, j = int(word(j)), j + 1
    elif word(j) in NUMBERS:
        n, j = NUMBERS[word(j)], j + 1
    elif word(j) in ("a", "an"):
        j += 1
    if word(j) == "couple":
        n, j = 2, j + 1
    if word(j) == "dozen":
        n, j = (n or 1) * 12, j + 1
    if word(j) in UNITS and j + 1 < len(toks):
        unit, j = word(j), j + 1
    if word(j) == "of" and j > i:
        j += 1
    if unit:
        count = n or 1
        return f"{count} {UNITS[unit] if count > 1 else unit}", j
    return (str(n) if n is not None else None), j


def _skip_fillers(toks, i):
    while i < len(toks) and toks[i][0] in FILLERS:
        i += 1
    return i


def _segment(toks, index, longest):
    """Cover a chunk entirely with catalog names. -> [(name, qty)] or None."""
    memo = {}

    def seg(i):
        if i in memo:
            return memo[i]
        i = _skip_fillers(toks, i)
        if i >= len(toks):
            return []
        qty, k = _parse_qty(toks, i)
        k = _skip_fillers(toks, k)
        result = None
        for m in range(min(longest, len(toks) - k), 0, -1):
            span = [w for n, _ in toks[k:k + m] for w in n.split()]
            hit = next((index[key] for key in name_keys(span) if key in index), None)
            if hit:
                rest = seg(k + m)
                if rest is not None:
                    result = [(hit, qty)] + rest
                    break
        memo[i] = result
        return result

    return seg(0)


def parse_spoken(text, index, longest):
    """-> list of (catalog_name or None, new_name or None, qty or None)."""
    toks = _protect(_strip_phrases(tokenize(text)), index, longest)
    chunks, cur = [], []
    for t in toks + [(",", ",")]:
        if t[0] in SEPARATORS:
            if cur:
                chunks.append(cur)
            cur = []
        else:
            cur.append(t)

    out = []
    for chunk in chunks:
        found = _segment(chunk, index, longest)
        if found:
            out += [(name, None, qty) for name, qty in found]
            continue
        i = _skip_fillers(chunk, 0)
        qty, i = _parse_qty(chunk, i)
        i = _skip_fillers(chunk, i)
        words = [r for _, r in chunk[i:]]
        while words and singular(words[-1]) in FILLERS:
            words.pop()
        if words:
            out.append((None, " ".join(words).upper(), qty))
    return out
