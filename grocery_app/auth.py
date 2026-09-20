from functools import wraps
from flask import (
    Blueprint, current_app, request, session, redirect, url_for, render_template
)

bp = Blueprint("auth", __name__)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        pw = current_app.config.get("APP_PASSWORD")
        if pw and not session.get("authed"):
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@bp.route("/login", methods=["GET", "POST"])
def login():
    pw = current_app.config.get("APP_PASSWORD")
    if not pw:
        return redirect(url_for("main.view_list"))
    error = None
    if request.method == "POST":
        if request.form.get("password") == pw:
            session["authed"] = True
            return redirect(request.args.get("next") or url_for("main.view_list"))
        error = "Wrong password."
    return render_template("login.html", error=error)


@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
