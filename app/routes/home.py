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

def process_data(df, user_id, source, product_code_map):
    result = {"rows": 0, "products": 0, "sales": 0, "production": 0, "expenses": 0, "customers": 0}
    if df is None or df.empty:
        return result

    df = df.dropna(axis=0, how="all")
    df = df.dropna(axis=1, how="all")
    if df.empty:
        return result

    result["rows"] = len(df)
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

    product_col = find(["product_name", "productname", "product", "item", "item_name", "product_title"])
    product_id_col = find(["product_id", "productid", "product_code", "sku", "sku_id"])
    category_col = find(["category", "product_category", "subcategory", "product_type"])
    price_col = find(["price", "unit_price", "selling_price", "rate"])
    quantity_col = find(["quantity", "qty", "qty_sold", "quantity_sold", "units", "units_sold", "sold_quantity"])
    production_col = find(["production_quantity", "production_qty", "produced_quantity", "produced_qty", "quantity_produced"])
    sales_col = find(["amount_of_sales", "sales_amount", "revenue", "total_revenue", "total_sales", "sale_amount", "sales"])
    date_col = find(["date", "sales_date", "sale_date", "transaction_date", "time_period", "datetime", "timestamp", "production_date", "expense_date"])
    region_col = find(["region", "area", "location", "region_area", "zone", "city"])
    expense_category_col = find(["expense_category", "exp_category", "expense_type"])
    expense_col = find(["expense_amount", "total_expense", "cost_amount", "expense", "amount"])
    customer_col = find(["customer", "customer_name", "customer_id", "cust_id", "client", "client_name"])

    source_name = source.lower()

    products = Product.query.filter_by(user_id=user_id).all()
    sales = Sales.query.filter_by(user_id=user_id).all()
    production = Production.query.filter_by(user_id=user_id).all()
    expenses = Expenses.query.filter_by(user_id=user_id).all()
    customers = CustomerData.query.filter_by(user_id=user_id).all()

    product_map = {str(product.product_name).strip().lower(): product for product in products if product.product_name}
    sales_map = {(sale.product_id, sale.region_area or "", sale.time_period): sale for sale in sales}
    production_map = {(item.product_id, item.time_period): item for item in production}
    expense_map = {(expense.exp_category or "", expense.time_period): expense for expense in expenses}
    customer_map = {(customer.product_id, customer.sales_id, customer.time): customer for customer in customers}

    new_products = []
    new_sales = []
    new_production = []
    new_expenses = []
    new_customers = []

    for row in df.to_dict("records"):
        product_name = None
        product_code = None
        category = None
        price = None
        quantity = None
        production_quantity = None
        sales_amount = None
        expense_amount = None
        date = None
        region = None
        expense_category = "Other"

        if product_col:
            value = row.get(product_col)
            if pd.notna(value):
                product_name = str(value).strip()

        if product_id_col:
            value = row.get(product_id_col)
            if pd.notna(value):
                product_code = str(value).strip()

        if category_col:
            value = row.get(category_col)
            if pd.notna(value):
                category = str(value).strip()

        if price_col:
            value = row.get(price_col)
            if pd.notna(value):
                try:
                    price = float(str(value).replace(",", "").replace("₹", "").replace("$", ""))
                except:
                    price = None

        if quantity_col:
            value = row.get(quantity_col)
            if pd.notna(value):
                try:
                    quantity = int(float(value))
                except:
                    quantity = None

        if production_col:
            value = row.get(production_col)
            if pd.notna(value):
                try:
                    production_quantity = int(float(value))
                except:
                    production_quantity = None

        if date_col:
            value = row.get(date_col)
            if pd.notna(value):
                try:
                    date = pd.to_datetime(value, errors="coerce")
                    date = None if pd.isna(date) else date.to_pydatetime()
                except:
                    date = None

        if region_col:
            value = row.get(region_col)
            if pd.notna(value):
                region = str(value).strip()

        if sales_col:
            value = row.get(sales_col)
            if pd.notna(value):
                try:
                    sales_amount = float(str(value).replace(",", "").replace("₹", "").replace("$", ""))
                except:
                    sales_amount = None

        if expense_col:
            value = row.get(expense_col)
            if pd.notna(value):
                try:
                    expense_amount = float(str(value).replace(",", "").replace("₹", "").replace("$", ""))
                except:
                    expense_amount = None

        if expense_category_col:
            value = row.get(expense_category_col)
            if pd.notna(value):
                expense_category = str(value).strip()

        product = None

        if product_name:
            product = product_map.get(product_name.lower())

        if not product and product_code:
            product = product_code_map.get(product_code)

        if "products" in source_name and product_name:
            key = product_name.lower()
            product = product_map.get(key)

            if product:
                if category:
                    product.category = category
                if price is not None:
                    product.price = price
            else:
                product = Product(user_id=user_id, product_name=product_name, category=category, price=price)
                new_products.append(product)
                product_map[key] = product

            if product_code:
                product_code_map[product_code] = product

            result["products"] += 1

        if not product and product_name:
            product = product_map.get(product_name.lower())

        if product and ("sales" in source_name or sales_amount is not None):
            if sales_amount is not None or quantity is not None:
                key = (product.product_id, region or "", date)
                sale = sales_map.get(key)

                if sale:
                    if quantity is not None:
                        sale.quantity = quantity
                    if sales_amount is not None:
                        sale.amount_of_sales = sales_amount
                else:
                    sale = Sales(user_id=user_id, product_id=product.product_id, region_area=region, quantity=quantity, amount_of_sales=sales_amount, time_period=date)
                    new_sales.append(sale)
                    if product.product_id:
                        sales_map[key] = sale

                result["sales"] += 1

        if product and ("production" in source_name or production_quantity is not None):
            if production_quantity is not None:
                key = (product.product_id, date)
                production_record = production_map.get(key)

                if production_record:
                    production_record.quantity = production_quantity
                    if price is not None:
                        production_record.price = price
                else:
                    production_record = Production(user_id=user_id, product_id=product.product_id, quantity=production_quantity, price=price, time_period=date)
                    new_production.append(production_record)
                    production_map[key] = production_record

                result["production"] += 1

        if expense_amount is not None:
            key = (expense_category, date)
            expense = expense_map.get(key)

            if expense:
                expense.price = expense_amount
            else:
                expense = Expenses(user_id=user_id, exp_category=expense_category, price=expense_amount, time_period=date)
                new_expenses.append(expense)
                expense_map[key] = expense

            result["expenses"] += 1

        if "customers" in source_name and product:
            customer_key = (product.product_id, None, date)
            customer_record = customer_map.get(customer_key)

            if customer_record:
                customer_record.quantity = quantity
                customer_record.time = date
            else:
                customer_record = CustomerData(user_id=user_id, product_id=product.product_id, sales_id=None, quantity=quantity, time=date)
                new_customers.append(customer_record)
                customer_map[customer_key] = customer_record

            result["customers"] += 1

    if new_products:
        db.session.add_all(new_products)
        db.session.flush()
        for product in new_products:
            product_map[str(product.product_name).strip().lower()] = product

    if new_sales:
        db.session.add_all(new_sales)

    if new_production:
        db.session.add_all(new_production)

    if new_expenses:
        db.session.add_all(new_expenses)

    if new_customers:
        db.session.add_all(new_customers)

    db.session.flush()
    return result

def create_analysis(user_id):
    Analysis.query.filter_by(user_id=user_id, analysis_type="Automated Summary").delete(synchronize_session=False)

    total_products = Product.query.filter_by(user_id=user_id).count()
    total_sales_records = Sales.query.filter_by(user_id=user_id).count()
    total_production = Production.query.filter_by(user_id=user_id).count()
    total_customers = CustomerData.query.filter_by(user_id=user_id).count()

    total_sales = db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar()
    total_expenses = db.session.query(func.coalesce(func.sum(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar()

    total_sales = float(total_sales or 0)
    total_expenses = float(total_expenses or 0)
    net_amount = total_sales - total_expenses

    analyses = [
        Analysis(user_id=user_id, ana_name="Business Overview", description=f"The business has {total_products} products, {total_sales_records} sales records, {total_production} production records and {total_customers} customer records.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Sales Summary", description=f"Total recorded sales are ₹{total_sales:,.2f}.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Expense Summary", description=f"Total recorded expenses are ₹{total_expenses:,.2f}.", analysis_type="Automated Summary"),
        Analysis(user_id=user_id, ana_name="Net Business Amount", description=f"Sales minus expenses equals ₹{net_amount:,.2f}.", analysis_type="Automated Summary")
    ]

    top_product = db.session.query(Product.product_name, func.sum(Sales.amount_of_sales).label("total")).join(Sales, Product.product_id == Sales.product_id).filter(Product.user_id == user_id).group_by(Product.product_id, Product.product_name).order_by(func.sum(Sales.amount_of_sales).desc()).first()

    if top_product:
        analyses.append(Analysis(user_id=user_id, ana_name="Top Selling Product", description=f"{top_product[0]} has the highest recorded sales value of ₹{float(top_product[1] or 0):,.2f}.", analysis_type="Automated Summary"))

    db.session.add_all(analyses)
    

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

    product_names = {product.product_id: product.product_name for product in products}
    product_sales = {}

    for sale in sales:
        name = product_names.get(sale.product_id, "Unknown Product")
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
        has_data=len(products) > 0 or len(sales) > 0 or len(expenses) > 0 or len(customers) > 0 or len(production) > 0,
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
    user_id = session["user_id"]
    product_code_map = {}

    try:
        datasets = []

        for file in files:
            if not file.filename:
                continue

            extension = file.filename.rsplit(".", 1)[-1].lower()

            if extension not in allowed:
                flash(f"{file.filename} is not supported.", "danger")
                return redirect(url_for("home.input_data"))

            datasets.extend(read_file(file))

        datasets.sort(key=lambda item: 0 if "products" in item[0].lower() else 1)

        for source, df in datasets:
            result = process_data(df, user_id, source, product_code_map)

            for key in total:
                total[key] += result[key]

        create_analysis(user_id)
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