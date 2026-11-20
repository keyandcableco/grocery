# Key & Cable Groceries

A standalone Flask grocery-list service for the flask-stack suite. Populates from
your item catalog, sorts into store categories, splits local vs. bulk/warehouse,
and emails or texts a categorized list. Reachable across your tailnet.

## Layout

```
grocery/
├── run.py                 # entry point (0.0.0.0:5055)
├── import_sheet.py        # one-time Google Sheet CSV import
├── requirements.txt
└── grocery_app/
    ├── __init__.py        # app factory + category seed
    ├── config.py          # env-driven config
    ├── models.py          # Item, ListItem, Category, TripSnapshot
    ├── views.py           # all routes
    ├── auth.py            # optional shared-password gate
    ├── templates/
    └── static/            # style.css, app.js, manifest.json
```

## Run

```bash
pip install -r requirements.txt
python run.py            # http://<tailscale-ip>:5055
```

## Import your existing list

Export the Google Sheet as CSV (headers: name, category, source, qty, note),
then:

```bash
python import_sheet.py grocery_export.csv
```

`source` accepts `local`/`bulk` or words like costco/warehouse/online (→ bulk).
Unknown categories are created automatically and parked at the end of aisle order;
reorder them in the `categories` table to match your store walk.

## Config (environment variables)

| Var | Purpose |
|-----|---------|
| `GROCERY_DB_URI` | DB URL. Default `sqlite:///grocery.db`. Swap to Postgres to fold into workbench. |
| `GROCERY_SECRET` | Flask session secret. |
| `GROCERY_PASSWORD` | Optional shared password. Unset = no auth (fine behind Tailscale). |
| `SMTP_HOST/PORT/USER/PASS/FROM` | Outbound mail. For Gmail use an App Password. |
| `GROCERY_RECIPIENTS` | Default send targets, comma-separated. Phone gateways OK. |

### Texting without an SMS API

Use your carrier's email-to-SMS gateway as a recipient, e.g.
`3523251222@vtext.com` (Verizon), `@txt.att.net` (AT&T), `@tmomail.net` (T-Mobile).
Swap in Twilio later if you want something sturdier.

## Features

- **List** — categorized, aisle-ordered, local/bulk split; check items off while
  shopping, edit quantities inline, send or checkout.
- **Skim** — browse the whole catalog to jog memory; live text filter; a "Usual
  items" chip row of your most-added staples for one-tap adding.
- **Catalog** — add/update/soft-delete items (soft delete keeps history intact).
- **Checkout** — saves the current list as a trip snapshot, stamps
  `last_purchased`, and clears the list.
- **History** — past trips with one-tap **Reorder onto list** for a typical run.
- **PWA** — `manifest.json` lets it install to your phone home screen.

## Voice capture (Tasker or any HTTP client)

`POST /api/capture` takes a spoken sentence and puts the items on the list:

```bash
curl -X POST http://<pi>:8006/api/capture \
  -H 'Content-Type: text/plain' \
  -d 'we need two milks, ground chicken and a bag of tortilla chips'
```

Send a raw `text/plain` body (easiest, no JSON escaping) or `{"text": "..."}`.
Items are split on commas and "and", and matched against the catalog
regardless of plurals or word order ("ground chicken" → CHICKEN GROUND,
"half and half" → HALF N HALF). A run of catalog names said without "and"
between them ("eggs milk bread") still splits. A leading number or unit becomes
the quantity ("two milks" → 2, "a bag of chips" → 1 bag). Lead-ins like "add",
"we need" and "to the list" are ignored.

Anything not in the catalog is added to it under **Other** and put on the
list, so nothing said is lost — set its category on the Catalog page once and
it's matched from then on. One catch: a new two-word item made of two catalog
names (say "almond milk", with ALMONDS and MILK in the catalog) splits into
those two until ALMOND MILK itself is in the catalog.

The response lists `added`, `updated` (qty changed), `already` and `new` names,
plus a one-line `summary` for a Tasker flash or Say, and `reader` (`haiku` or `rules`).

### Rambles: Claude Haiku sorts them

With `ANTHROPIC_API_KEY` set, Haiku reads the text first (`grocery_app/sorter.py`), so
a loose ramble works: "uh we need milk, a couple onions, the good bread, oh and eggs,
no wait, we have eggs". It matches each thing to a catalog name (almond milk is not
MILK), reads amounts, leaves out what's taken back, and gives a new item a store
category instead of Other. Capture only: nothing comes off the list by voice. With no
key, no internet or an error, the word rules above take over, so nothing said is lost.
Only the words, the catalog names and the category names go to Anthropic; a ramble
costs a fraction of a cent.

### Recordings: talk as long as you like

`POST /api/record` takes an audio file (raw body, e.g. `Content-Type: audio/mp4`, or a
multipart upload). Whisper writes it out on the server (`grocery_app/transcribe.py`,
the same faster-whisper setup as the GTD tracker and the shop app), then it's sorted
like a capture. `?wait=N` (up to 75 s) holds the reply until it's on the list, so the
phone can say what was added; past that, the reply says it's queued and it lands a
little later. `GET /api/recordings` shows the last ten (what Whisper heard, what was
added, any error); `POST /api/recordings/<id>/retry` tries a failed one again.

The server needs `faster-whisper` (requirements.txt), the recordings folder (default
`instance/recordings`, inside the data volume) and a Whisper model folder,
`WHISPER_DIR` (the stack shares the shop's `whisper_models`). `WHISPER_MODEL` defaults
to `medium.en` (about 2 GB while loaded, dropped when idle); `small.en` is about three
times faster, `off` turns recordings off. On the Pi 4, medium.en takes roughly 2.7
minutes per minute of talk, so a 20-second ramble is about a minute.

**Tasker**: import `tasker/Grocery_Ramble.tsk.xml` (Tasks tab, long-press the tab,
Import Task; Tasker needs its media permission for that), then set the HTTP Request's
URL to your server. One task: run it to start recording, run it again to send.

1. `If %GROCERYREC eq on`
2. ` Record Audio Stop`
3. ` Variable Set %GROCERYREC to off`
4. ` Say Sending`
5. ` HTTP Request`: POST `https://<pi>.ts.net:8448/api/record?wait=50`, Headers
   `Content-Type:audio/mp4`, File To Send `Tasker/grocery.mp4`, Timeout 60
6. ` Say %http_data.summary`
7. `Else`
8. ` Say Listening. Double tap again to send.`
9. ` Variable Set %GROCERYREC to on`
10. ` Record Audio`: File `Tasker/grocery.mp4`, Format MP4, MaxSize 0
11. `End If`

Gotchas found setting it up (Tasker 6.7.9): the HTTP timeout tops out at 60 s, so
`wait` stays under it; set Record Audio's Format to MP4 by hand after importing (the
file's format number didn't carry over); leave "Continue Task After Error" off on the
HTTP Request so a failed send stops instead of reading out `%http_data.summary`. Use
the server's HTTPS (Tailscale serve) address: Tasker doesn't allow plain http.
Give each Say an engine (`com.google.android.tts:eng-usa`): the default one fails with
"TTS: unsupported locale" and stops the task. Record Audio adds the format's extension
unless the name already has it (`grocery.m4a` became `grocery.m4a.mp4`), so name it
`.mp4`. The stack's nginx gives up after 60 s, another reason `wait` stays at 50; a
long ramble (Whisper takes about 2.3 s per second of talk on the Pi) answers "Got it"
and lands on the list a few minutes later.

To start it from another task (a back-tap menu, say), add `Perform Task Grocery
Ramble` with **Stop** ticked, `If %ld_selected ~ Grocery ramble` after the List
Dialog, and the same action with `If %GROCERYREC ~ on` before the dialog, so the
second tap sends without asking again.

## Merging into workbench later

Models use SQLAlchemy, so point `GROCERY_DB_URI` at workbench's Postgres and the
same schema ports over. To run inside one Flask instance instead of standalone,
register `grocery_app.views.bp` and `grocery_app.auth.bp` on the parent app under
a `/groceries` url_prefix and drop the `create_app` call. Migrations here are
additive-only, matching the workbench convention.

## License

Copyright © 2026 Greg Miller / The Key & Cable Company.

Licensed under the [GNU General Public License v3.0](LICENSE). You can use, study, share and modify it. If you distribute it or a modified version, you have to make the source available under the same licence.
