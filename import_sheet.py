"""One-time import from the PANTRY Google Sheet export.

Expected columns (case-insensitive, order-independent):
  ITEM    (required)  - item name
  QTY     (optional)  - default quantity; 0 just means "not currently needed",
                        still imported as a catalog item
  TYPE    (optional)  - category: OTHER, PRODUCE, CONDIMENTS, DAIRY, DELI, FROZEN
  COSTCO  (TRUE/FALSE) - warehouse/bulk flag
  PATEL   (TRUE/FALSE) - local store flag
  HARRIS  (TRUE/FALSE) - local store flag

Source rule (per current preference): COSTCO=TRUE -> 'bulk', otherwise 'local'.
(Items sold at Costco AND a local store are labeled bulk under this rule.)

Usage:
  python import_sheet.py PANTRY_-_PANTRY.csv
  # inside the container:
  docker compose exec groceries python import_sheet.py /app/PANTRY_-_PANTRY.csv
"""
import csv
import sys

from grocery_app import create_app
from grocery_app.models import db, Item, Category

# TYPE (sheet) -> seeded category name. Anything unlisted falls back to 'Other'.
TYPE_MAP = {
    "OTHER": "Other",
    "PRODUCE": "Produce",
    "CONDIMENTS": "Condiments & Sauces",
    "DAIRY": "Dairy",
    "DELI": "Deli",
    "FROZEN": "Frozen",
}


def truthy(val):
    return (val or "").strip().upper() in {"TRUE", "1", "YES", "Y", "X"}


def main(path):
    app = create_app()
    with app.app_context():
        known = {c.name.lower(): c.name for c in Category.query.all()}
        added = updated = 0

        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [h.strip().upper() for h in reader.fieldnames]

            for raw in reader:
                row = {(k or "").strip().upper(): (v or "").strip()
                       for k, v in raw.items()}
                name = row.get("ITEM")
                if not name:
                    continue

                # category
                type_in = row.get("TYPE", "")
                category = TYPE_MAP.get(type_in.upper())
                if not category:
                    category = known.get(type_in.lower(), "Other") if type_in else "Other"

                # source: Costco -> bulk, else local
                source = "bulk" if truthy(row.get("COSTCO")) else "local"

                # qty: keep 0 as the default so out-of-stock items import but
                # don't get auto-added anywhere; blank -> "1"
                qty = row.get("QTY", "")
                qty = qty if qty != "" else "1"

                existing = Item.query.filter(
                    db.func.lower(Item.name) == name.lower()
                ).first()
                if existing:
                    existing.category = category
                    existing.source = source
                    existing.default_qty = qty
                    existing.active = True
                    updated += 1
                else:
                    db.session.add(Item(
                        name=name,
                        category=category,
                        source=source,
                        default_qty=qty,
                    ))
                    added += 1

        db.session.commit()
        total = Item.query.count()
        bulk = Item.query.filter_by(source="bulk").count()
        print(f"Imported: {added} new, {updated} updated. "
              f"Catalog now {total} items ({bulk} bulk, {total - bulk} local).")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python import_sheet.py <PANTRY_export.csv>")
        sys.exit(1)
    main(sys.argv[1])
