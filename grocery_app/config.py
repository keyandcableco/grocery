import os


class Config:
    # Swap to a Postgres URL to merge into the workbench suite later.
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "GROCERY_DB_URI", "sqlite:///grocery.db"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("GROCERY_SECRET", "dev-change-me")

    # Optional single shared password (leave unset to disable auth).
    APP_PASSWORD = os.environ.get("GROCERY_PASSWORD")

    # SMTP for emailing / texting the list.
    SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
    SMTP_USER = os.environ.get("SMTP_USER")
    SMTP_PASS = os.environ.get("SMTP_PASS")
    SMTP_FROM = os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", ""))

    # Default recipients (comma-separated). Phone gateways work here too,
    # e.g. 3523251222@vtext.com
    DEFAULT_RECIPIENTS = os.environ.get("GROCERY_RECIPIENTS", "")
