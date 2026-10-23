import json
import re
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest
from sklearn.metrics import mean_absolute_error
import numpy as np
import random
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from sqlalchemy import func,cast,String
from app import db,cache
from app.models import User, Product, Sales, Production, Expenses, CustomerData, Prediction, Analysis
from datetime import datetime
from zoneinfo import ZoneInfo

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

    analyses = []
    add_analysis = lambda name, description: analyses.append(Analysis(user_id=user_id, ana_name=name, description=description, analysis_type="Automated Summary"))

    products = Product.query.filter_by(user_id=user_id).all()
    sales_records = Sales.query.filter_by(user_id=user_id).all()
    production_records = Production.query.filter_by(user_id=user_id).all()
    customer_records = CustomerData.query.filter_by(user_id=user_id).count()
    total_sales = float(db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    total_expenses = float(db.session.query(func.coalesce(func.sum(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar() or 0)
    net_amount = total_sales - total_expenses

    add_analysis("Business Data Insights", f"Analysis of {len(products)} products, {len(sales_records)} sales records, {len(production_records)} production records and {customer_records} customer records found total sales of ₹{total_sales:,.2f} and recorded expenses of ₹{total_expenses:,.2f}.")

    if sales_records:
        sales_df = pd.DataFrame([{"date": row.date_of_sales, "amount": float(row.amount_of_sales or 0), "product_id": row.product_id} for row in sales_records])
        sales_df["date"] = pd.to_datetime(sales_df["date"], errors="coerce")
        sales_df["amount"] = pd.to_numeric(sales_df["amount"], errors="coerce")
        sales_df = sales_df.dropna(subset=["amount"])

        if not sales_df.empty:
            average_sale = float(sales_df["amount"].mean())
            add_analysis("Average Sales Value", f"The average recorded sales value is ₹{average_sale:,.2f} across {len(sales_df)} valid sales records.")

            if total_sales > 0 and total_expenses > 0:
                expense_ratio = total_expenses / total_sales * 100
                add_analysis("Expense Ratio Insight", f"Recorded expenses represent {expense_ratio:.2f}% of recorded sales. Sales minus recorded expenses equals ₹{net_amount:,.2f}; this is not necessarily accounting profit.")

            valid_dates = sales_df.dropna(subset=["date"])
            if not valid_dates.empty:
                daily_sales = valid_dates.groupby(valid_dates["date"].dt.normalize())["amount"].sum().sort_index()

                if len(daily_sales) >= 2:
                    first_value = float(daily_sales.iloc[0])
                    last_value = float(daily_sales.iloc[-1])
                    change = last_value - first_value
                    trend = "increased" if change > 0 else "decreased" if change < 0 else "remained unchanged"
                    add_analysis("Historical Sales Change", f"Sales changed from ₹{first_value:,.2f} on {daily_sales.index[0].date()} to ₹{last_value:,.2f} on {daily_sales.index[-1].date()}; the recorded value {trend} by ₹{abs(change):,.2f}. This compares the first and last recorded sales days, not equivalent periods.")

                if len(daily_sales) >= 5:
                    x = np.arange(len(daily_sales)).reshape(-1, 1)
                    y = daily_sales.to_numpy(dtype=float)
                    model = LinearRegression().fit(x, y)
                    next_index = np.array([[len(daily_sales)]])
                    prediction = max(0.0, float(model.predict(next_index)[0]))
                    trend = "upward" if model.coef_[0] > 0 else "downward" if model.coef_[0] < 0 else "flat"
                    add_analysis("ML Sales Forecast", f"Linear regression estimates sales for the next observed sales interval at approximately ₹{prediction:,.2f}. The fitted historical trend is {trend}. This is a baseline estimate, not a guarantee.")

                    variation = float(daily_sales.std(ddof=0))
                    mean_sales = float(daily_sales.mean())
                    if mean_sales > 0:
                        cv = variation / mean_sales * 100
                        level = "high" if cv > 50 else "moderate" if cv > 20 else "low"
                        add_analysis("Sales Volatility", f"Daily sales have a coefficient of variation of {cv:.2f}%, indicating {level} variation relative to their mean.")

                if len(daily_sales) >= 10:
                    detector = IsolationForest(contamination="auto", random_state=42).fit(daily_sales.to_numpy().reshape(-1, 1))
                    unusual = daily_sales[detector.predict(daily_sales.to_numpy().reshape(-1, 1)) == -1]
                    if not unusual.empty:
                        unusual_text = ", ".join(f"{date.date()}: ₹{amount:,.2f}" for date, amount in unusual.sort_values().tail(3).items())
                        add_analysis("Unusual Sales Detection", f"Isolation Forest flagged these daily sales values as unusual: {unusual_text}. Review them for promotions, exceptional orders, or data errors.")

            product_sales = sales_df.dropna(subset=["product_id"]).groupby("product_id")["amount"].sum().sort_values(ascending=False)
            product_lookup = {product.product_id: product.product_name for product in products}

            if not product_sales.empty:
                best_id = product_sales.index[0]
                best_value = float(product_sales.iloc[0])
                best_name = product_lookup.get(best_id, f"Product {best_id}")
                add_analysis("Leading Product", f"{best_name} has the highest recorded sales value at ₹{best_value:,.2f}.")

                if total_sales > 0:
                    share = best_value / total_sales * 100
                    add_analysis("Product Revenue Concentration", f"The leading product represents approximately {share:.2f}% of total recorded sales. A high share may indicate reliance on one product.")

                if len(product_sales) >= 2:
                    second_id = product_sales.index[1]
                    second_name = product_lookup.get(second_id, f"Product {second_id}")
                    second_value = float(product_sales.iloc[1])
                    add_analysis("Product Sales Comparison", f"{best_name} recorded ₹{best_value:,.2f} in sales compared with ₹{second_value:,.2f} for {second_name}, a difference of ₹{best_value - second_value:,.2f}.")

    if len(analyses) < 10 and total_sales > 0:
        add_analysis("Sales and Expense Outlook", f"Recorded sales exceed expenses by ₹{net_amount:,.2f}." if net_amount >= 0 else f"Recorded expenses exceed sales by ₹{abs(net_amount):,.2f}. Review costs and revenue before drawing conclusions about profitability.")

    if len(analyses) < 10 and products:
        add_analysis("Product Portfolio Insight", f"There are {len(products)} products in the current portfolio. Compare product-level sales and costs to identify which products deserve more attention.")

    if len(analyses) < 10 and production_records:
        add_analysis("Production Data Coverage", f"The database contains {len(production_records)} production records. Production efficiency requires compatible production quantities, sales quantities, and time periods.")

    if len(analyses) < 10 and customer_records:
        add_analysis("Customer Data Coverage", f"The database contains {customer_records} customer records. Customer purchasing patterns require sales records linked to customer identifiers.")

    db.session.add_all(analyses[:10])
    db.session.commit()

def apply_dark(fig):
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter, Arial, sans-serif",color="#cbd5e1",size=12),
        margin=dict(l=20, r=20, t=25, b=25),
        legend=dict(bgcolor="rgba(0,0,0,0)",font=dict(color="#cbd5e1", size=11)),
        hoverlabel=dict(bgcolor="#111b29",bordercolor="#29374a",font=dict(color="#f1f5f9"))
    )
    fig.update_xaxes(showgrid=False,zeroline=False,showline=True,linecolor="#29374a",tickfont=dict(color="#94a3b8"),title_font=dict(color="#cbd5e1"))
    fig.update_yaxes(showgrid=True,gridcolor="rgba(148,163,184,0.12)",zeroline=False,showline=False,tickfont=dict(color="#94a3b8"),title_font=dict(color="#cbd5e1"))
    fig.update_annotations(font=dict(color="#94a3b8", size=13))
    return fig    

@home.route("/")
def homepg():
    if "user_id" in session:
        return redirect(url_for("home.dashboard"))
    return render_template("index.html")
@home.route("/dashboard")
@cache.cached(timeout=300, key_prefix=lambda: f"dashboard_{session.get('user_id', 'anonymous')}")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))

    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))

    total_products = Product.query.filter_by(user_id=user_id).count()
    total_customers = CustomerData.query.filter_by(user_id=user_id).count()
    total_production = Production.query.filter_by(user_id=user_id).count()
    total_predictions = Prediction.query.filter_by(user_id=user_id).count()
    total_sales_records = Sales.query.filter_by(user_id=user_id).count()

    total_sales = float(db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    total_expenses = float(db.session.query(func.coalesce(func.sum(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar() or 0)
    total_quantity = int(db.session.query(func.coalesce(func.sum(Sales.quantity), 0)).filter(Sales.user_id == user_id).scalar() or 0)

    analysis = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.ana_id.desc()).limit(10).all()
    products = Product.query.filter_by(user_id=user_id).order_by(Product.product_name.asc()).limit(10).all()

    monthly_sales_rows = db.session.query(func.date_trunc("month", Sales.time_period).label("month"), func.sum(Sales.amount_of_sales).label("total")).filter(Sales.user_id == user_id, Sales.time_period.isnot(None)).group_by(func.date_trunc("month", Sales.time_period)).order_by(func.date_trunc("month", Sales.time_period)).all()
    monthly_expense_rows = db.session.query(func.date_trunc("month", Expenses.time_period).label("month"), func.sum(Expenses.price).label("total")).filter(Expenses.user_id == user_id, Expenses.time_period.isnot(None)).group_by(func.date_trunc("month", Expenses.time_period)).order_by(func.date_trunc("month", Expenses.time_period)).all()

    monthly_sales = {month.strftime("%Y-%m"): float(total or 0) for month, total in monthly_sales_rows}
    monthly_expenses = {month.strftime("%Y-%m"): float(total or 0) for month, total in monthly_expense_rows}
    months = sorted(set(monthly_sales) | set(monthly_expenses))

    if months:
        sales_chart = go.Figure()
        sales_chart.add_trace(go.Bar(x=months, y=[monthly_sales.get(month, 0) for month in months], name="Sales", marker_color="#7181ef", marker_line_width=0, hovertemplate="%{x}<br>Sales: %{y:,.2f}<extra></extra>"))

        revenue_chart = go.Figure()
        revenue_chart.add_trace(go.Scatter(x=months, y=[monthly_sales.get(month, 0) for month in months], mode="lines+markers", name="Revenue", line=dict(color="#7181ef", width=3), marker=dict(size=6, color="#7181ef"), hovertemplate="%{x}<br>Revenue: %{y:,.2f}<extra></extra>"))
        revenue_chart.add_trace(go.Scatter(x=months, y=[monthly_expenses.get(month, 0) for month in months], mode="lines+markers", name="Expenses", line=dict(color="#fb7185", width=2.5), marker=dict(size=5, color="#fb7185"), hovertemplate="%{x}<br>Expenses: %{y:,.2f}<extra></extra>"))
    else:
        sales_chart = go.Figure()
        sales_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="#94a3b8", size=13))

        revenue_chart = go.Figure()
        revenue_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="#94a3b8", size=13))

    product_rows = db.session.query(Product.product_name, func.sum(Sales.amount_of_sales).label("total")).join(Product, Sales.product_id == Product.product_id).filter(Sales.user_id == user_id, Product.user_id == user_id).group_by(Product.product_id, Product.product_name).order_by(func.sum(Sales.amount_of_sales).desc()).limit(10).all()
    top_products = [(name, float(total or 0)) for name, total in product_rows]

    if top_products:
        product_chart = go.Figure()
        product_chart.add_trace(go.Bar(x=[item[1] for item in top_products], y=[item[0] for item in top_products], orientation="h", name="Sales", marker_color="#818cf8", marker_line_width=0, hovertemplate="%{y}<br>Sales: %{x:,.2f}<extra></extra>"))
        product_chart.update_layout(yaxis=dict(autorange="reversed"))
    else:
        product_chart = go.Figure()
        product_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="#94a3b8", size=13))

    region_rows = db.session.query(Sales.region_area, func.sum(Sales.amount_of_sales).label("total")).filter(Sales.user_id == user_id).group_by(Sales.region_area).order_by(func.sum(Sales.amount_of_sales).desc()).all()
    regions = {(region or "Unknown"): float(total or 0) for region, total in region_rows}

    if regions:
        region_chart = go.Figure()
        region_chart.add_trace(go.Pie(labels=list(regions.keys()), values=list(regions.values()), hole=0.55, marker=dict(colors=["#7181ef", "#fb7185", "#10b981", "#a78bfa", "#38bdf8"], line=dict(color="#111b29", width=3)), textfont=dict(color="#e2e8f0"), hovertemplate="%{label}<br>Sales: %{value:,.2f}<br>Share: %{percent}<extra></extra>"))
    else:
        region_chart = go.Figure()
        region_chart.add_annotation(text="No data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="#94a3b8", size=13))

    sales_chart = apply_dark(sales_chart)
    revenue_chart = apply_dark(revenue_chart)
    product_chart = apply_dark(product_chart)
    region_chart = apply_dark(region_chart)

    recent_sales = Sales.query.filter_by(user_id=user_id).order_by(Sales.time_period.desc().nullslast(), Sales.sales_id.desc()).limit(10).all()

    current_hour = datetime.now(ZoneInfo("Asia/Kolkata")).hour
    greeting = "Good morning" if current_hour < 12 else "Good afternoon" if current_hour < 17 else "Good evening"

    has_data = total_products > 0 or total_sales_records > 0 or total_expenses != 0 or total_customers > 0 or total_production > 0

    return render_template(
        "dashboard.html",
        user=user,
        has_data=has_data,
        total_sales=total_sales,
        total_expenses=total_expenses,
        net_amount=total_sales - total_expenses,
        total_products=total_products,
        total_customers=total_customers,
        total_sales_records=total_sales_records,
        total_production=total_production,
        total_predictions=total_predictions,
        total_analysis=len(analysis),
        total_quantity=total_quantity,
        recent_sales=recent_sales,
        products=products,
        analysis=analysis,
        top_products=top_products,
        monthly_sales_chart=json.dumps(sales_chart, cls=PlotlyJSONEncoder),
        revenue_expenses_chart=json.dumps(revenue_chart, cls=PlotlyJSONEncoder),
        product_sales_chart=json.dumps(product_chart, cls=PlotlyJSONEncoder),
        region_sales_chart=json.dumps(region_chart, cls=PlotlyJSONEncoder),
        greeting=greeting
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
        cache.delete(f"dashboard_{user_id}")
        for page_number in range(1, 1001):
            cache.delete(f"sales_{user_id}_{page_number}")
        flash(f"Import completed successfully! {total['rows']:,} rows processed. "f"{total['products']:,} products, {total['sales']:,} sales, "f"{total['production']:,} production records, "f"{total['expenses']:,} expenses and "f"{total['customers']:,} customer records were stored.","success")
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

@home.route("/sales")
@cache.cached(timeout=3000, key_prefix=lambda: f"sales_{session.get('user_id', 'anonymous')}_{request.args.get('page', '1')}")
def sales_page():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))

    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))

    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 15

    sales_query = db.session.query(Sales, Product).outerjoin(Product, (Sales.product_id == Product.product_id) & (Product.user_id == user_id)).filter(Sales.user_id == user_id)
    total_transactions = sales_query.count()
    total_pages = max(1, (total_transactions + per_page - 1) // per_page)
    page = min(page, total_pages)

    sales_records = sales_query.order_by(Sales.sales_id.desc()).offset((page - 1) * per_page).limit(per_page).all()

    total_sales = float(db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    total_quantity = int(db.session.query(func.coalesce(func.sum(Sales.quantity), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    unique_products = db.session.query(func.count(func.distinct(Sales.product_id))).filter(Sales.user_id == user_id, Sales.product_id.isnot(None)).scalar() or 0

    monthly_rows = db.session.query(func.date_trunc("month", Sales.time_period).label("month"), func.sum(Sales.amount_of_sales).label("total_sales"), func.sum(Sales.quantity).label("total_quantity")).filter(Sales.user_id == user_id, Sales.time_period.isnot(None)).group_by(func.date_trunc("month", Sales.time_period)).order_by(func.date_trunc("month", Sales.time_period)).all()

    monthly_sales = {month.strftime("%Y-%m"): float(amount or 0) for month, amount, quantity in monthly_rows}
    monthly_quantity = {month.strftime("%Y-%m"): int(quantity or 0) for month, amount, quantity in monthly_rows}
    months = sorted(monthly_sales.keys())

    product_rows = db.session.query(Product.product_name, func.sum(Sales.amount_of_sales).label("total")).join(Product, Sales.product_id == Product.product_id).filter(Sales.user_id == user_id, Product.user_id == user_id).group_by(Product.product_id, Product.product_name).order_by(func.sum(Sales.amount_of_sales).desc()).limit(10).all()
    top_products = [(name, float(amount or 0)) for name, amount in product_rows]

    region_rows = db.session.query(Sales.region_area, func.sum(Sales.amount_of_sales).label("total")).filter(Sales.user_id == user_id).group_by(Sales.region_area).order_by(func.sum(Sales.amount_of_sales).desc()).all()
    region_sales = {(region or "Unknown"): float(amount or 0) for region, amount in region_rows}

    monthly_chart = go.Figure()
    if months:
        monthly_chart.add_trace(go.Bar(x=months, y=[monthly_sales[month] for month in months], name="Sales", marker_color="#7181ef", marker_line_width=0, hovertemplate="%{x}<br>Sales: %{y:,.2f}<extra></extra>"))
    else:
        monthly_chart.add_annotation(text="No sales data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)

    product_chart = go.Figure()
    if top_products:
        product_chart.add_trace(go.Bar(x=[item[1] for item in top_products], y=[item[0] for item in top_products], orientation="h", name="Sales", marker_color="#818cf8", marker_line_width=0, hovertemplate="%{y}<br>Sales: %{x:,.2f}<extra></extra>"))
        product_chart.update_layout(yaxis=dict(autorange="reversed"))
    else:
        product_chart.add_annotation(text="No product data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)

    region_chart = go.Figure()
    if region_sales:
        region_chart.add_trace(go.Pie(labels=list(region_sales.keys()), values=list(region_sales.values()), hole=0.55, marker=dict(colors=["#7181ef", "#fb7185", "#10b981", "#a78bfa", "#38bdf8"], line=dict(color="#111b29", width=3)), textfont=dict(color="#e2e8f0"), hovertemplate="%{label}<br>Sales: %{value:,.2f}<br>Share: %{percent}<extra></extra>"))
    else:
        region_chart.add_annotation(text="No regional sales data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)

    quantity_chart = go.Figure()
    if months:
        quantity_chart.add_trace(go.Scatter(x=months, y=[monthly_quantity[month] for month in months], mode="lines+markers", name="Quantity Sold", line=dict(color="#10b981", width=3), marker=dict(size=6), hovertemplate="%{x}<br>Quantity: %{y:,}<extra></extra>"))
    else:
        quantity_chart.add_annotation(text="No quantity data available", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False)

    monthly_chart = apply_dark(monthly_chart)
    product_chart = apply_dark(product_chart)
    region_chart = apply_dark(region_chart)
    quantity_chart = apply_dark(quantity_chart)

    return render_template("sales.html", user=user, sales_records=sales_records, total_sales=total_sales, total_transactions=total_transactions, total_quantity=total_quantity, unique_products=unique_products, page=page, total_pages=total_pages, per_page=per_page, monthly_sales_chart=json.dumps(monthly_chart, cls=PlotlyJSONEncoder), product_sales_chart=json.dumps(product_chart, cls=PlotlyJSONEncoder), region_sales_chart=json.dumps(region_chart, cls=PlotlyJSONEncoder), quantity_sales_chart=json.dumps(quantity_chart, cls=PlotlyJSONEncoder))

@home.route("/products")
@cache.cached(timeout=300, key_prefix=lambda: f"products_{session.get('user_id', 'anonymous')}_{request.args.get('page', '1')}_{request.args.get('search', '').strip()}")
def products():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    search = request.args.get("search", "").strip()
    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 30

    query = Product.query.filter(Product.user_id == user_id)

    if search:
        search_term = f"%{search}%"
        query = query.filter(db.or_(Product.product_name.ilike(search_term), cast(Product.product_id, String).ilike(search_term)))

    total_products = query.count()
    total_pages = max(1, (total_products + per_page - 1) // per_page)
    page = min(page, total_pages)

    products_list = query.order_by(Product.product_name.asc(), Product.product_id.asc()).offset((page - 1) * per_page).limit(per_page).all()

    start_record = (page - 1) * per_page + 1 if total_products else 0
    end_record = min(page * per_page, total_products)

    return render_template("product.html", products=products_list, total_products=total_products, search=search, page=page, total_pages=total_pages, start_record=start_record, end_record=end_record)