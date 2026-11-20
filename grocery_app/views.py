import json
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime

from flask import (
    Blueprint, current_app, render_template, request, redirect, url_for,
    jsonify, flash
)
from sqlalchemy import func

from .models import db, Item, ListItem, Category, TripSnapshot, Recording
from .auth import login_required
from .voice import build_index, parse_spoken
from . import recordings, sorter

bp = Blueprint("main", __name__)
log = logging.getLogger("grocery.views")

SOURCE_LABELS = {"local": "Local Grocery", "bulk": "Bulk / Warehouse"}


# ---------------------------------------------------------------- helpers
def _category_order():
    return {c.name: c.sort_order for c in Category.query.all()}


def grouped_list(source_filter=None):
    """Return {(source, category): [rows...]} in aisle order."""
    order = _category_order()
    q = (
        db.session.query(ListItem, Item)
        .join(Item, Item.id == ListItem.item_id)
    )
    if source_filter:
        q = q.filter(Item.source == source_filter)
    grouped = {}
    for li, it in q.all():
        grouped.setdefault((it.source, it.category), []).append((li, it))
    # sort within group by name
    for k in grouped:
        grouped[k].sort(key=lambda pair: pair[1].name.lower())
    # sort the group keys by source then aisle order
    ordered_keys = sorted(
        grouped.keys(),
        key=lambda k: (k[0] != "local", order.get(k[1], 500), k[1])
    )
    return [(k, grouped[k]) for k in ordered_keys]


def format_list_text(source_filter=None):
    blocks = []
    cur_source = None
    for (source, cat), rows in grouped_list(source_filter):
        if source != cur_source:
            blocks.append(f"\n########## {SOURCE_LABELS.get(source, source).upper()} ##########")
            cur_source = source
        blocks.append(f"\n-- {cat} --")
        for li, it in rows:
            mark = "[x]" if li.checked else "[ ]"
            qty = f" ({li.qty})" if li.qty and li.qty != "1" else ""
            blocks.append(f"  {mark} {it.name}{qty}")
    body = "\n".join(blocks).strip()
    return body or "List is empty."


# ---------------------------------------------------------------- list views
@bp.get("/")
@login_required
def view_list():
    return render_template(
        "list.html",
        grouped=grouped_list(),
        source_labels=SOURCE_LABELS,
        recipients=current_app.config.get("DEFAULT_RECIPIENTS", ""),
    )


@bp.get("/skim")
@login_required
def skim():
    """Browse the full catalog to jog memory; flags what's already on the list."""
    on_list = {li.item_id for li in ListItem.query.all()}
    cat = request.args.get("category")
    src = request.args.get("source")
    query = Item.query.filter_by(active=True)
    if cat:
        query = query.filter_by(category=cat)
    if src:
        query = query.filter_by(source=src)
    items = query.order_by(Item.times_added.desc(), Item.category, Item.name).all()

    # "Usual items" = your most frequently added, one tap away
    usuals = (
        Item.query.filter_by(active=True)
        .filter(Item.times_added > 0)
        .order_by(Item.times_added.desc())
        .limit(12).all()
    )
    cats = [c.name for c in Category.query.order_by(Category.sort_order).all()]
    return render_template(
        "skim.html", items=items, usuals=usuals, on_list=on_list,
        categories=cats, sel_cat=cat, sel_src=src, source_labels=SOURCE_LABELS,
    )


# ---------------------------------------------------------------- catalog CRUD
@bp.get("/catalog")
@login_required
def catalog():
    items = Item.query.filter_by(active=True).order_by(Item.category, Item.name).all()
    cats = [c.name for c in Category.query.order_by(Category.sort_order).all()]
    return render_template("catalog.html", items=items, categories=cats,
                           source_labels=SOURCE_LABELS)


@bp.post("/items")
@login_required
def add_item():
    f = request.form
    name = f["name"].strip()
    existing = Item.query.filter(func.lower(Item.name) == name.lower()).first()
    if existing:
        existing.active = True
        existing.category = f["category"]
        existing.source = f.get("source", "local")
        existing.default_qty = f.get("default_qty", "1") or "1"
        existing.note = f.get("note") or None
    else:
        db.session.add(Item(
            name=name, category=f["category"], source=f.get("source", "local"),
            default_qty=f.get("default_qty", "1") or "1", note=f.get("note") or None,
        ))
    db.session.commit()
    flash(f"Saved {name}.")
    return redirect(request.form.get("next") or url_for("main.catalog"))


@bp.post("/items/<int:item_id>/edit")
@login_required
def edit_item(item_id):
    it = Item.query.get_or_404(item_id)
    f = request.form
    it.name = f["name"].strip()
    it.category = f["category"]
    it.source = f.get("source", "local")
    it.default_qty = f.get("default_qty", "1") or "1"
    it.note = f.get("note") or None
    db.session.commit()
    return redirect(url_for("main.catalog"))


@bp.post("/items/<int:item_id>/delete")
@login_required
def remove_item(item_id):
    it = Item.query.get_or_404(item_id)
    it.active = False
    db.session.commit()
    return ("", 204)


# ---------------------------------------------------------------- list mutations
@bp.post("/list/add/<int:item_id>")
@login_required
def add_to_list(item_id):
    it = Item.query.get_or_404(item_id)
    if not ListItem.query.filter_by(item_id=item_id).first():
        db.session.add(ListItem(item_id=item_id, qty=it.default_qty or "1"))
        it.times_added = (it.times_added or 0) + 1
        db.session.commit()
    return _list_reply(item_id, on_list=True)


@bp.post("/list/remove/<int:item_id>")
@login_required
def remove_from_list(item_id):
    li = ListItem.query.filter_by(item_id=item_id).first()
    if li:
        db.session.delete(li)
        db.session.commit()
    return _list_reply(item_id, on_list=False)


@bp.post("/list/qty/<int:item_id>")
@login_required
def set_qty(item_id):
    li = ListItem.query.filter_by(item_id=item_id).first_or_404()
    li.qty = request.form.get("qty", "1") or "1"
    db.session.commit()
    return ("", 204)


@bp.post("/list/check/<int:item_id>")
@login_required
def toggle_check(item_id):
    li = ListItem.query.filter_by(item_id=item_id).first_or_404()
    want = request.form.get("checked")
    # An explicit state makes repeat taps harmless; no state still toggles.
    li.checked = (want == "1") if want in ("0", "1") else not li.checked
    db.session.commit()
    return jsonify(checked=li.checked)


@bp.post("/list/clear")
@login_required
def clear_list():
    ListItem.query.delete()
    db.session.commit()
    return redirect(url_for("main.view_list"))


def read_spoken(text, wait=30):
    """-> (entries, reader). Haiku reads it when it can, else the word rules.
    entries: [(catalog_name or None, new_name or None, qty or None, category or None)]."""
    items = Item.query.all()
    if sorter.available():
        names = [it.name for it in items]
        cats = [c.name for c in Category.query.order_by(Category.sort_order).all()]
        try:
            return sorter.read(text, names, cats, wait=wait), "haiku"
        except Exception as e:
            log.warning("Haiku couldn't read the ramble, using the word rules: %s", e)
    index, longest = build_index(
        (it.name, (1000 if it.active else 0) + (it.times_added or 0)) for it in items
    )
    return [(n, nn, q, None) for n, nn, q in parse_spoken(text, index, longest)], "rules"


def add_spoken(entries, allow_new=True):
    """Put entries on the list (not committed). -> the reply dict with its summary.
    Names that aren't in the catalog are added to it (under Haiku's category,
    or Other), so nothing said is lost; fix them on the Catalog page. With
    allow_new False they're skipped and counted instead (a long recording read
    by the word rules would otherwise fill the catalog with stray phrases)."""
    by_name = {it.name: it for it in Item.query.all()}
    known_cats = {c.name for c in Category.query.all()}
    added, updated, already, new, skipped = [], [], [], [], []
    for name, new_name, qty, category in entries:
        if not allow_new and not by_name.get(name):
            if new_name and new_name.lower() not in {n.lower() for n in by_name}:
                skipped.append(new_name)
                continue
        it = by_name.get(name) if name else None
        if not it and new_name:
            it = Item.query.filter(func.lower(Item.name) == new_name.lower()).first()
        if not it:
            if not new_name:
                continue
            it = Item(name=new_name, category=category if category in known_cats else "Other",
                      source="local", default_qty="1")
            db.session.add(it)
            db.session.flush()
            by_name[it.name] = it
            new.append(it.name)
        it.active = True
        label = f"{qty} {it.name}" if qty else it.name
        li = ListItem.query.filter_by(item_id=it.id).first()
        if li:
            li.checked = False
            if qty and qty != li.qty:
                li.qty = qty
                updated.append(label)
            else:
                already.append(it.name)
        else:
            db.session.add(ListItem(item_id=it.id, qty=qty or it.default_qty or "1"))
            it.times_added = (it.times_added or 0) + 1
            added.append(label)

    # short sentence for a Tasker flash or Say
    parts = []
    if added:
        parts.append("Added " + ", ".join(added))
    if updated:
        parts.append("Updated " + ", ".join(updated))
    if already:
        parts.append("Already on " + ", ".join(already))
    if new:
        parts.append("New to catalog " + ", ".join(new))
    summary = ". ".join(parts).lower() or "Didn't catch any items"
    if skipped:
        summary += (f". Haiku was out, so {len(skipped)} unknown "
                    f"{'phrase was' if len(skipped) == 1 else 'phrases were'} skipped")
    return dict(added=added, updated=updated, already=already, new=new, skipped=skipped,
                summary=summary)


@bp.post("/api/capture")
@login_required
def api_capture():
    """Voice capture: "two milks, ground chicken and eggs", or a whole ramble,
    onto the list. Accepts JSON {"text": ...} or a raw text/plain body
    (easiest from Tasker). Haiku sorts it when ANTHROPIC_API_KEY is set,
    otherwise the word rules in voice.py do."""
    data = request.get_json(silent=True)
    text = data.get("text", "") if isinstance(data, dict) else request.get_data(as_text=True)
    text = (text or "").strip()
    if not text:
        return jsonify(error="empty"), 400
    entries, reader = read_spoken(text)
    reply = add_spoken(entries)
    db.session.commit()
    return jsonify(**reply, reader=reader), 201


@bp.post("/api/record")
@login_required
def api_record():
    """A recording of a ramble, as the raw body (Tasker's HTTP Request with a
    file to send) or a multipart upload. Whisper writes it out on the server
    and it's sorted onto the list in the background. ?wait=N (up to 75) holds
    the reply that many seconds for the result, so Tasker can say what was
    added; otherwise, or if it takes longer, the reply just says it's queued."""
    upload = (next(iter(request.files.values()), None)
              if request.mimetype == "multipart/form-data" else None)
    if upload:
        data, name, ctype = upload.read(), upload.filename or "", upload.mimetype
    else:
        data, name, ctype = request.get_data(), "", request.mimetype
    if not data:
        return jsonify(error="empty"), 400
    rec = recordings.save(data, name, ctype)
    try:
        wait = max(0, min(int(request.args.get("wait", 0)), 75))
    except ValueError:
        wait = 0
    rec = recordings.wait_for(rec.id, wait) if wait else rec
    if rec.status == "filed":
        return jsonify(id=rec.id, status=rec.status, reader=rec.reader,
                       text=rec.text, summary=rec.summary), 201
    if rec.status == "failed":
        return jsonify(id=rec.id, status=rec.status, error=rec.error,
                       summary="Couldn't use that recording: " + rec.error), 201
    summary = ("Got it. Adding it once it's written out." if recordings.speech_to_text()
               else "Saved, but speech-to-text is off here, so it's waiting.")
    return jsonify(id=rec.id, status=rec.status, summary=summary), 202


@bp.get("/api/recordings")
@login_required
def api_recordings():
    """The latest recordings, newest first, with what each heard and added."""
    rows = Recording.query.order_by(Recording.created_at.desc()).limit(10).all()
    return jsonify(recordings=[dict(
        id=r.id, created_at=r.created_at.isoformat(), status=r.status, text=r.text,
        reader=r.reader, summary=r.summary, error=r.error) for r in rows])


@bp.post("/api/recordings/<int:rid>/retry")
@login_required
def api_recording_retry(rid):
    """Try a failed recording again (after a failed model download, say)."""
    if not recordings.retry(rid):
        return jsonify(error="not a failed recording"), 404
    return jsonify(ok=True)


def _list_reply(item_id, on_list):
    """AJAX callers get JSON; form fallbacks get a redirect."""
    if request.headers.get("X-Requested-With") == "fetch":
        return jsonify(item_id=item_id, on_list=on_list)
    return redirect(request.form.get("next") or url_for("main.skim"))


# ---------------------------------------------------------------- checkout / history
@bp.post("/checkout")
@login_required
def checkout():
    """Save the current list as a trip snapshot, stamp last_purchased, clear it."""
    rows = (
        db.session.query(ListItem, Item)
        .join(Item, Item.id == ListItem.item_id).all()
    )
    if rows:
        payload = [
            {"item_id": it.id, "name": it.name, "qty": li.qty,
             "source": it.source, "category": it.category}
            for li, it in rows
        ]
        db.session.add(TripSnapshot(
            label=request.form.get("label") or datetime.utcnow().strftime("%Y-%m-%d"),
            payload=json.dumps(payload),
        ))
        for li, it in rows:
            it.last_purchased = datetime.utcnow()
        ListItem.query.delete()
        db.session.commit()
        flash("Trip saved to history and list cleared.")
    return redirect(url_for("main.view_list"))


@bp.get("/history")
@login_required
def history():
    trips = TripSnapshot.query.order_by(TripSnapshot.created_at.desc()).limit(50).all()
    parsed = [(t, json.loads(t.payload or "[]")) for t in trips]
    return render_template("history.html", trips=parsed)


@bp.post("/history/<int:trip_id>/reorder")
@login_required
def reorder(trip_id):
    trip = TripSnapshot.query.get_or_404(trip_id)
    for entry in json.loads(trip.payload or "[]"):
        it = Item.query.get(entry["item_id"])
        if it and it.active and not ListItem.query.filter_by(item_id=it.id).first():
            db.session.add(ListItem(item_id=it.id, qty=entry.get("qty", "1")))
    db.session.commit()
    flash("Previous trip reloaded onto your list.")
    return redirect(url_for("main.view_list"))


# ---------------------------------------------------------------- send
@bp.post("/send")
@login_required
def send_list():
    cfg = current_app.config
    to = request.form.get("to") or cfg.get("DEFAULT_RECIPIENTS", "")
    recipients = [r.strip() for r in to.split(",") if r.strip()]
    src = request.form.get("source") or None
    if not recipients:
        flash("No recipient set.")
        return redirect(url_for("main.view_list"))
    if not cfg.get("SMTP_USER"):
        flash("SMTP is not configured (set SMTP_USER / SMTP_PASS).")
        return redirect(url_for("main.view_list"))

    msg = EmailMessage()
    msg["Subject"] = "Grocery List"
    msg["From"] = cfg["SMTP_FROM"]
    msg["To"] = ", ".join(recipients)
    msg.set_content(format_list_text(src))
    try:
        with smtplib.SMTP(cfg["SMTP_HOST"], cfg["SMTP_PORT"]) as s:
            s.starttls()
            s.login(cfg["SMTP_USER"], cfg["SMTP_PASS"])
            s.send_message(msg)
        flash(f"Sent to {', '.join(recipients)}.")
    except Exception as e:  # noqa: BLE001
        flash(f"Send failed: {e}")
    return redirect(url_for("main.view_list"))
