from flask import Flask
from .config import Config
from .models import db


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    db.init_app(app)

    from .views import bp as main_bp
    from .auth import bp as auth_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    with app.app_context():
        db.create_all()
        _seed_categories()

    return app


def _seed_categories():
    """Idempotent category seed with a sensible default aisle order."""
    from .models import Category
    defaults = [
        ("Produce", 10), ("Bakery", 20), ("Deli", 30), ("Meat", 40),
        ("Seafood", 50), ("Dairy", 60), ("Eggs", 65), ("Frozen", 70),
        ("Canned & Jarred", 80), ("Dry Goods & Pasta", 90),
        ("Baking", 100), ("Condiments & Sauces", 110), ("Snacks", 120),
        ("Beverages", 130), ("Coffee & Tea", 140), ("Breakfast", 150),
        ("Household", 160), ("Cleaning", 170), ("Paper Goods", 180),
        ("Personal Care", 190), ("Health", 200), ("Pet", 210), ("Other", 999),
    ]
    for name, order in defaults:
        if not Category.query.get(name):
            db.session.add(Category(name=name, sort_order=order))
    db.session.commit()
