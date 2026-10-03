from app import db
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime


class User(db.Model):
    user_id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(90), nullable=False)
    business_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    business_type = db.Column(db.String(200), default="Business")
    password = db.Column(db.String(255), nullable=False)

    def set_password(self, password):
        self.password = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password, password)


class Product(db.Model):
    product_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    product_name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100))
    price = db.Column(db.Float)
    sales = db.relationship("Sales", backref="product", lazy=True)
    production = db.relationship("Production", backref="product", lazy=True)


class Sales(db.Model):
    sales_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"), nullable=False)
    region_area = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    amount_of_sales = db.Column(db.Float)
    time_period = db.Column(db.DateTime)


class Production(db.Model):
    pro_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"), nullable=False)
    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)
    time_period = db.Column(db.DateTime)


class Expenses(db.Model):
    exp_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    exp_category = db.Column(db.String(100))
    price = db.Column(db.Float)
    time_period = db.Column(db.DateTime)


class CustomerData(db.Model):
    cust_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"))
    sales_id = db.Column(db.Integer, db.ForeignKey("sales.sales_id"))
    quantity = db.Column(db.Integer)
    time = db.Column(db.DateTime)


class Prediction(db.Model):
    pre_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    pre_name = db.Column(db.String(150))
    pre_desc = db.Column(db.Text)
    predicted_value = db.Column(db.Float)
    time_period = db.Column(db.DateTime)


class Analysis(db.Model):
    ana_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer,db.ForeignKey("user.user_id"),nullable=False)
    ana_name = db.Column(db.String(150))
    description = db.Column(db.Text)
    analysis_type = db.Column(db.String(100))
