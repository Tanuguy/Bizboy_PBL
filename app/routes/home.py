from flask import (
    Flask,
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash,
    session,
    request,
)
from app import db
from app.models import User

home = Blueprint("home", __name__)


@home.route("/")
def homepg():
    if "user_id" in session:
        return redirect(url_for("home.dashboard"))
    return render_template("index.html")


@home.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))
    return render_template("dashboard.html")
