from datetime import datetime
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Category(db.Model):
    __tablename__ = "categories"
    name = db.Column(db.String, primary_key=True)
    sort_order = db.Column(db.Integer, default=100)  # aisle/walking order


class Item(db.Model):
    """Master catalog of things Greg buys."""
    __tablename__ = "items"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False, unique=True)
    category = db.Column(db.String, db.ForeignKey("categories.name"), nullable=False)
    source = db.Column(db.String, nullable=False, default="local")  # 'local' | 'bulk'
    default_qty = db.Column(db.String, default="1")
    note = db.Column(db.String)
    active = db.Column(db.Boolean, default=True)          # soft delete
    times_added = db.Column(db.Integer, default=0)        # frequency ranking
    last_purchased = db.Column(db.DateTime)               # staple restock tracking
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    list_entry = db.relationship(
        "ListItem", backref="item", uselist=False,
        cascade="all, delete-orphan"
    )


class ListItem(db.Model):
    """An item currently on the working grocery list."""
    __tablename__ = "list_items"
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, unique=True)
    qty = db.Column(db.String, default="1")
    checked = db.Column(db.Boolean, default=False)        # crossed off while shopping
    added_at = db.Column(db.DateTime, default=datetime.utcnow)


class Recording(db.Model):
    """A spoken ramble sent as audio: queued -> transcribing -> filed | failed."""
    __tablename__ = "recordings"
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String, nullable=False, default="queued")
    audio = db.Column(db.String, nullable=False)       # file name in RECORDINGS_DIR
    text = db.Column(db.String, default="")            # Whisper's transcript, kept once made
    reader = db.Column(db.String, default="")          # "haiku" or "rules"
    summary = db.Column(db.String, default="")         # what was added, as said back
    error = db.Column(db.String, default="")
    attempts = db.Column(db.Integer, default=0)


class TripSnapshot(db.Model):
    """A completed list saved for history / one-tap reorder."""
    __tablename__ = "trip_snapshots"
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    payload = db.Column(db.String)  # JSON: [{item_id, name, qty, source, category}, ...]
