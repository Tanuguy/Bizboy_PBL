from flask import Flask,Blueprint,render_template,redirect,url_for,flash,session,request
from app import db
from app.models import User

auth=Blueprint("auth",__name__)

@auth.route('/register',methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form.get("name")
        business_name=request.form.get("business_name")
        email=request.form.get("email")
        business_type=request.form.get("business_type")
        password=request.form.get("password")

        if not name or not business_name or not email or not password:
            flash("Please fill in all required fields.","error")
            return redirect(url_for("auth.register"))

        user = User.query.filter_by(email=email).first()
        if user:
            flash("Email already registered.","error")
            return redirect(url_for("auth.register"))

        new_user = User(
            name=name,
            business_name=business_name,
            email=email,
            business_type=business_type
        )
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful.","success")
        return redirect(url_for("auth.login"))

    return render_template("register.html")

@auth.route('/login',methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form.get("email")
        password=request.form.get("password")

        user = User.query.filter_by(email=email).first()
        if user and user.check_password(password):
            session["user_id"] = user.user_id
            flash("Login successful.","success")
            return redirect(url_for("home.dashboard"))
        else:
            flash("Invalid email or password.","error")
            return redirect(url_for("auth.login"))

    return render_template("login.html")

@auth.route('/logout')
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.","success")
    return redirect(url_for("home.homepg"))