import json
import re
import pandas as pd
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from sqlalchemy import func
from app import db
from app.models import User, Product, Sales, Production, Expenses, CustomerData, Prediction, Analysis

home = Blueprint("home", __name__)

def read_file(file):
    filename = file.filename
    extension = filename.rsplit(".", 1)[-1].lower()
    if extension == "csv":
        file.stream.seek(0)
        try:
            df = pd.read_csv(file)
        except UnicodeDecodeError:
            file.stream.seek(0)
            df = pd.read_csv(file, encoding="latin-1")
        return [(filename, df)]
    if extension in ["xlsx", "xls"]:
        file.stream.seek(0)
        sheets = pd.read_excel(file, sheet_name=None)
        return [(f"{filename} - {sheet}", df) for sheet, df in sheets.items()]
    if extension == "json":
        file.stream.seek(0)
        data = json.load(file)
        if isinstance(data, list):
            df = pd.DataFrame(data)
        elif isinstance(data, dict):
            if isinstance(data.get("data"), list):
                df = pd.DataFrame(data["data"])
            else:
                df = pd.DataFrame([data])
        else:
            df = pd.DataFrame()
        return [(filename, df)]
    return []

def process_data(df, user_id):
    if df is None or df.empty:
        return {"rows": 0, "products": 0, "sales": 0, "production": 0, "expenses": 0, "customers": 0}
    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")
    if df.empty:
        return {"rows": 0, "products": 0, "sales": 0, "production": 0, "expenses": 0, "customers": 0}
    columns = {}
    for column in df.columns:
        name = str(column).strip().lower()
        name = re.sub(r"[^a-z0-9]+", "_", name)
        name = re.sub(r"_+", "_", name).strip("_")
        columns[name] = column
    def find(names):
        for name in names:
            name = re.sub(r"[^a-z0-9]+", "_", name.lower())
            name = re.sub(r"_+", "_", name).strip("_")
            if name in columns:
                return columns[name]
        return None
    product_col = find(["product_name", "product", "item", "item_name", "product_title"])
    category_col = find(["category", "product_category", "subcategory", "product_type"])
    price_col = find(["price", "unit_price", "selling_price", "rate"])
    quantity_col = find(["quantity", "qty", "qty_sold", "quantity_sold", "units", "units_sold", "sold_quantity"])
    production_col = find(["production_quantity", "production_qty", "produced_quantity", "produced_qty", "quantity_produced"])
    sales_col = find(["amount_of_sales", "sales_amount", "revenue", "total_revenue", "total_sales", "sale_amount", "sales"])
    date_col = find(["date", "sales_date", "sale_date", "transaction_date", "time_period", "datetime", "timestamp"])
    region_col = find(["region", "area", "location", "region_area", "zone", "city"])
    expense_category_col = find(["expense_category", "exp_category", "expense_type"])
    expense_col = find(["expense_amount", "total_expense", "cost_amount", "expense"])
    amount_col = find(["amount", "total_amount"])
    customer_col = find(["customer", "customer_name", "customer_id", "client", "client_name"])
    result = {"rows": len(df), "products": 0, "sales": 0, "production": 0, "expenses": 0, "customers": 0}
    product_cache = {}
    for _, row in df.iterrows():
        product_name = None
        if product_col and not pd.isna(row[product_col]):
            product_name = str(row[product_col]).strip()
        category = None
        if category_col and not pd.isna(row[category_col]):
            category = str(row[category_col]).strip()
        price = None
        if price_col:
            try:
                value = str(row[price_col]).replace(",", "").replace("₹", "").replace("$", "")
                price = float(value)
            except:
                price = None
        quantity = None
        if quantity_col:
            try:
                quantity = int(float(row[quantity_col]))
            except:
                quantity = None
        production_quantity = None
        if production_col:
            try:
                production_quantity = int(float(row[production_col]))
            except:
                production_quantity = None
        date = None
        if date_col:
            try:
                date = pd.to_datetime(row[date_col], errors="coerce")
                if pd.isna(date):
                    date = None
                else:
                    date = date.to_pydatetime()
            except:
                date = None
        region = None
        if region_col and not pd.isna(row[region_col]):
            region = str(row[region_col]).strip()
        sales_amount = None
        if sales_col:
            try:
                value = str(row[sales_col]).replace(",", "").replace("₹", "").replace("$", "")
                sales_amount = float(value)
            except:
                sales_amount = None
        elif amount_col and product_name:
            try:
                sales_amount = float(str(row[amount_col]).replace(",", "").replace("₹", "").replace("$", ""))
            except:
                sales_amount = None
        product = None
        if product_name:
            key = product_name.lower()
            if key in product_cache:
                product = product_cache[key]
            else:
                product = Product.query.filter(Product.user_id == user_id, func.lower(Product.product_name) == key).first()
                if product:
                    if category:
                        product.category = category
                    if price is not None:
                        product.price = price
                else:
                    product = Product(user_id=user_id, product_name=product_name, category=category, price=price)
                    db.session.add(product)
                    db.session.flush()
                    result["products"] += 1
                product_cache[key] = product
        sale = None
        if product and (sales_amount is not None or quantity is not None):
            sale = Sales.query.filter(Sales.user_id == user_id, Sales.product_id == product.product_id, Sales.region_area == region, Sales.time_period == date).first()
            if sale:
                sale.quantity = quantity
                sale.amount_of_sales = sales_amount
            else:
                sale = Sales(user_id=user_id, product_id=product.product_id, region_area=region, quantity=quantity, amount_of_sales=sales_amount, time_period=date)
                db.session.add(sale)
                db.session.flush()
                result["sales"] += 1
        if product and production_quantity is not None:
            production = Production.query.filter(Production.user_id == user_id, Production.product_id == product.product_id, Production.time_period == date).first()
            if production:
                production.quantity = production_quantity
                if price is not None:
                    production.price = price
            else:
                production = Production(user_id=user_id, product_id=product.product_id, quantity=production_quantity, price=price, time_period=date)
                db.session.add(production)
                result["production"] += 1
        expense_amount = None
        if expense_col:
            try:
                expense_amount = float(str(row[expense_col]).replace(",", "").replace("₹", "").replace("$", ""))
            except:
                expense_amount = None
        elif amount_col and expense_category_col:
            try:
                expense_amount = float(str(row[amount_col]).replace(",", "").replace("₹", "").replace("$", ""))
            except:
                expense_amount = None
        if expense_amount is not None:
            expense_category = "Other"
            if expense_category_col and not pd.isna(row[expense_category_col]):
                expense_category = str(row[expense_category_col]).strip()
            expense = Expenses.query.filter(Expenses.user_id == user_id, Expenses.exp_category == expense_category, Expenses.time_period == date).first()
            if expense:
                expense.price = expense_amount
            else:
                expense = Expenses(user_id=user_id, exp_category=expense_category, price=expense_amount, time_period=date)
                db.session.add(expense)
                result["expenses"] += 1
        if customer_col and product and sale:
            customer = row[customer_col]
            if not pd.isna(customer):
                customer = str(customer).strip()
                if customer:
                    customer_record = CustomerData.query.filter(CustomerData.user_id == user_id, CustomerData.product_id == product.product_id, CustomerData.sales_id == sale.sales_id).first()
                    if customer_record:
                        customer_record.quantity = quantity
                        customer_record.time = date
                    else:
                        customer_record = CustomerData(user_id=user_id, product_id=product.product_id, sales_id=sale.sales_id, quantity=quantity, time=date)
                        db.session.add(customer_record)
                        result["customers"] += 1
    return result

def create_analysis(user_id):
    Analysis.query.filter_by(user_id=user_id, analysis_type="Automated Summary").delete(synchronize_session=False)
    products = Product.query.filter_by(user_id=user_id).all()
    sales = Sales.query.filter_by(user_id=user_id).all()
    expenses = Expenses.query.filter_by(user_id=user_id).all()
    customers = CustomerData.query.filter_by(user_id=user_id).all()
    production = Production.query.filter_by(user_id=user_id).all()
    total_sales = sum(float(s.amount_of_sales or 0) for s in sales)
    total_expenses = sum(float(e.price or 0) for e in expenses)
    net_amount = total_sales - total_expenses
    analyses = [
        Analysis(user_id=user_id, ana_name="Business Overview", description=f"The business has {len(products)} products, {len(sales)} sales records, {len(production)} production records and {len(customers)} customer records.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Sales Summary", description=f"Total recorded sales are ₹{total_sales:,.2f}.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Expense Summary", description=f"Total recorded expenses are ₹{total_expenses:,.2f}.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Net Business Amount", description=f"Sales minus expenses equals ₹{net_amount:,.2f}.", analysis_type="Automated Summary")
    ]
    product_sales = {}
    product_names = {product.product_id: product.product_name for product in products}
    for sale in sales:
        name = product_names.get(sale.product_id, "Unknown Product")
        product_sales[name] = product_sales.get(name, 0) + float(sale.amount_of_sales or 0)
    if product_sales:
        top_product = max(product_sales, key=product_sales.get)
        analyses.append(Analysis(user_id=user_id, ana_name="Top Selling Product", description=f"{top_product} has the highest recorded sales value of ₹{product_sales[top_product]:,.2f}.", analysis_type="Automated Summary"))
    for analysis in analyses:
        db.session.add(analysis)

@home.route("/")
def homepg():
    if "user_id" in session:
        return redirect(url_for("home.dashboard"))
    return render_template("index.html")

@home.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))
    user_id = session["user_id"]
    user = db.session.get(User, user_id)
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))
    products = Product.query.filter_by(user_id=user_id).all()
    sales = Sales.query.filter_by(user_id=user_id).all()
    expenses = Expenses.query.filter_by(user_id=user_id).all()
    customers = CustomerData.query.filter_by(user_id=user_id).all()
    production = Production.query.filter_by(user_id=user_id).all()
    predictions = Prediction.query.filter_by(user_id=user_id).all()
    analysis = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.ana_id.desc()).all()
    total_sales = sum(float(s.amount_of_sales or 0) for s in sales)
    total_expenses = sum(float(e.price or 0) for e in expenses)
    total_quantity = sum(int(s.quantity or 0) for s in sales)
    product_sales = {}
    for sale in sales:
        product = next((p for p in products if p.product_id == sale.product_id), None)
        name = product.product_name if product else "Unknown Product"
        product_sales[name] = product_sales.get(name, 0) + float(sale.amount_of_sales or 0)
    monthly_sales = {}
    monthly_expenses = {}
    for sale in sales:
        if sale.time_period:
            month = sale.time_period.strftime("%Y-%m")
            monthly_sales[month] = monthly_sales.get(month, 0) + float(sale.amount_of_sales or 0)
    for expense in expenses:
        if expense.time_period:
            month = expense.time_period.strftime("%Y-%m")
            monthly_expenses[month] = monthly_expenses.get(month, 0) + float(expense.price or 0)
    months = sorted(set(monthly_sales) | set(monthly_expenses))
    if months:
        sales_chart = go.Figure()
        sales_chart.add_trace(go.Bar(x=months, y=[monthly_sales.get(month, 0) for month in months], name="Sales"))
        revenue_chart = go.Figure()
        revenue_chart.add_trace(go.Scatter(x=months, y=[monthly_sales.get(month, 0) for month in months], mode="lines+markers", name="Revenue"))
        revenue_chart.add_trace(go.Scatter(x=months, y=[monthly_expenses.get(month, 0) for month in months], mode="lines+markers", name="Expenses"))
    else:
        sales_chart = go.Figure()
        sales_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
        revenue_chart = go.Figure()
        revenue_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    if product_sales:
        top_products = sorted(product_sales.items(), key=lambda x: x[1], reverse=True)[:10]
        product_chart = go.Figure()
        product_chart.add_trace(go.Bar(x=[item[1] for item in top_products], y=[item[0] for item in top_products], orientation="h", name="Sales"))
    else:
        top_products = []
        product_chart = go.Figure()
        product_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    regions = {}
    for sale in sales:
        region = sale.region_area or "Unknown"
        regions[region] = regions.get(region, 0) + float(sale.amount_of_sales or 0)
    if regions:
        region_chart = go.Figure()
        region_chart.add_trace(go.Pie(labels=list(regions.keys()), values=list(regions.values()), hole=0.55))
    else:
        region_chart = go.Figure()
        region_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)
    recent_sales = sorted(sales, key=lambda x: x.time_period if x.time_period else pd.Timestamp.min, reverse=True)[:10]
    return render_template(
        "dashboard.html",
        user=user,
        has_data=(len(products) > 0 or len(sales) > 0 or len(expenses) > 0 or len(customers) > 0 or len(production) > 0),
        total_sales=total_sales,
        total_expenses=total_expenses,
        net_amount=total_sales - total_expenses,
        total_products=len(products),
        total_customers=len(customers),
        total_sales_records=len(sales),
        total_production=len(production),
        total_predictions=len(predictions),
        total_analysis=len(analysis),
        total_quantity=total_quantity,
        recent_sales=recent_sales,
        products=products,
        analysis=analysis,
        top_products=top_products,
        monthly_sales_chart=json.dumps(sales_chart, cls=PlotlyJSONEncoder),
        revenue_expenses_chart=json.dumps(revenue_chart, cls=PlotlyJSONEncoder),
        product_sales_chart=json.dumps(product_chart, cls=PlotlyJSONEncoder),
        region_sales_chart=json.dumps(region_chart, cls=PlotlyJSONEncoder)
    )

@home.route("/input-data", methods=["GET", "POST"])
def input_data():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))
    if request.method == "GET":
        return render_template("input.html")
    files = request.files.getlist("business_files")
    if not files:
        flash("Please select at least one file.", "warning")
        return redirect(url_for("home.input_data"))
    allowed = {"csv", "xlsx", "xls", "json"}
    total = {"rows": 0, "products": 0, "sales": 0, "production": 0, "expenses": 0, "customers": 0}
    try:
        for file in files:
            if not file.filename:
                continue
            extension = file.filename.rsplit(".", 1)[-1].lower()
            if extension not in allowed:
                flash(f"{file.filename} is not supported.", "danger")
                return redirect(url_for("home.input_data"))
            for source, df in read_file(file):
                result = process_data(df, session["user_id"])
                for key in total:
                    total[key] += result[key]
        create_analysis(session["user_id"])
        db.session.commit()
        flash(f"Import completed successfully! {total['rows']:,} rows processed. {total['products']:,} products, {total['sales']:,} sales, {total['production']:,} production records, {total['expenses']:,} expenses and {total['customers']:,} customer records were stored.", "success")
        return redirect(url_for("home.dashboard"))
    except Exception as error:
        db.session.rollback()
        print("IMPORT ERROR:", error)
        flash(f"The file could not be processed. Error: {error}", "danger")
        return redirect(url_for("home.input_data"))

@home.route("/profile")
def profile():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))
    user = db.session.get(User, session["user_id"])
    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))
    return render_template("profile.html", user=user)