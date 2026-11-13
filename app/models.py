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
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True
    )
    product_name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(100), index=True)
    price = db.Column(db.Float)
    __table_args__ = (db.Index("idx_product_user_category", "user_id", "category"),)
    sales = db.relationship("Sales", backref="product", lazy=True)
    production = db.relationship("Production", backref="product", lazy=True)


class Sales(db.Model):
    sales_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"), nullable=False, index=True)
    region_area = db.Column(db.String(200))
    quantity = db.Column(db.Integer)
    amount_of_sales = db.Column(db.Float)
    time_period = db.Column(db.DateTime)
    __table_args__ = (db.Index("idx_sales_user_product", "user_id", "product_id"),
        db.Index("idx_sales_user_time", "user_id", time_period.desc()),
        db.Index("idx_sales_user_region", "user_id", "region_area"),)


class Production(db.Model):
    pro_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"), nullable=False, index=True)
    quantity = db.Column(db.Integer)
    price = db.Column(db.Float)
    time_period = db.Column(db.DateTime)
    __table_args__ = (db.Index("idx_production_user_product", "user_id", "product_id"),
        db.Index("idx_production_user_time", "user_id", time_period.desc()),)


class Expenses(db.Model):
    exp_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    exp_category = db.Column(db.String(100))
    price = db.Column(db.Float)
    time_period = db.Column(db.DateTime)
    __table_args__ = (
        db.Index("idx_expenses_user_time", "user_id", time_period.desc()),
        db.Index("idx_expenses_user_category", "user_id", "exp_category"),
    )


class CustomerData(db.Model):
    cust_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    product_id = db.Column(db.Integer, db.ForeignKey("product.product_id"), index=True)
    sales_id = db.Column(db.Integer, db.ForeignKey("sales.sales_id"), index=True)
    quantity = db.Column(db.Integer)
    time = db.Column(db.DateTime)
    __table_args__ = (db.Index("idx_customer_user_time", "user_id", time.desc()),)


class Prediction(db.Model):
    pre_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    pre_name = db.Column(db.String(150))
    pre_desc = db.Column(db.Text)
    predicted_value = db.Column(db.Float)
    time_period = db.Column(db.DateTime)
    __table_args__ = (db.Index("idx_prediction_user_time", "user_id", time_period.desc()),)


class Analysis(db.Model):
    ana_id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.user_id"), nullable=False, index=True)
    ana_name = db.Column(db.String(150))
    description = db.Column(db.Text)
    analysis_type = db.Column(db.String(100))
