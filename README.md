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
curl -X POST http://pugetbl:8006/api/capture \
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
plus a one-line `summary` for a Tasker flash or Say.

## Merging into workbench later

Models use SQLAlchemy, so point `GROCERY_DB_URI` at workbench's Postgres and the
same schema ports over. To run inside one Flask instance instead of standalone,
register `grocery_app.views.bp` and `grocery_app.auth.bp` on the parent app under
a `/groceries` url_prefix and drop the `create_app` call. Migrations here are
additive-only, matching the workbench convention.

## License

Copyright © 2026 Greg Miller / The Key & Cable Company.

Licensed under the [GNU General Public License v3.0](LICENSE). You can use, study, share and modify it. If you distribute it or a modified version, you have to make the source available under the same licence.
