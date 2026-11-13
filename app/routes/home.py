import json
import re
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.ensemble import IsolationForest
from xgboost import XGBRegressor
from sklearn.metrics import mean_absolute_error,r2_score,mean_squared_error
import numpy as np
import random
import plotly.graph_objects as go
from plotly.utils import PlotlyJSONEncoder
from flask import Blueprint, render_template, redirect, url_for, flash, session, request
from sqlalchemy import func,cast,String,or_,text
from app import db#,cache
from app.models import User, Product, Sales, Production, Expenses, CustomerData, Prediction, Analysis
from datetime import datetime
from zoneinfo import ZoneInfo
import inspect

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
    df = df.dropna(axis=0, how="all").dropna(axis=1, how="all")
    if df.empty:
        return result
    result["rows"] = len(df)
    columns = {}
    for column in df.columns:
        name = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", str(column).strip().lower())).strip("_")
        columns[name] = column
    def find(names):
        for name in names:
            name = re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.lower())).strip("_")
            if name in columns:
                return columns[name]
        return None
    def number(value):
        if pd.isna(value):
            return None
        try:
            return float(str(value).replace(",", "").replace("₹", "").replace("$", "").strip())
        except (ValueError, TypeError):
            return None
    def date_value(value):
        if pd.isna(value):
            return None
        try:
            value = pd.to_datetime(value, errors="coerce")
            return None if pd.isna(value) else value.to_pydatetime()
        except (ValueError, TypeError):
            return None
    def normalized_number(value):
        return None if value is None else round(float(value), 6)
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
    product_map = {str(p.product_name).strip().lower(): p for p in products if p.product_name}
    sales_keys = {
        (s.product_id, s.region_area or "", s.time_period, s.quantity, normalized_number(s.amount_of_sales))
        for s in sales
    }

    production_keys = {
        (p.product_id, p.time_period, p.quantity, normalized_number(p.price))
        for p in production
    }

    expense_keys = {
        (e.exp_category or "", e.time_period, normalized_number(e.price))
        for e in expenses
    }

    customer_keys = {
        (c.product_id, c.sales_id, c.time, c.quantity)
        for c in customers
    }

    new_sales = []
    new_production = []
    new_expenses = []
    new_customers = []

    for row in df.to_dict("records"):
        product_name = str(row.get(product_col)).strip() if product_col and pd.notna(row.get(product_col)) else None
        product_code = str(row.get(product_id_col)).strip() if product_id_col and pd.notna(row.get(product_id_col)) else None
        category = str(row.get(category_col)).strip() if category_col and pd.notna(row.get(category_col)) else None
        price = number(row.get(price_col)) if price_col else None
        quantity_value = number(row.get(quantity_col)) if quantity_col else None
        quantity = int(quantity_value) if quantity_value is not None and quantity_value.is_integer() else quantity_value
        production_value = number(row.get(production_col)) if production_col else None
        production_quantity = int(production_value) if production_value is not None and production_value.is_integer() else production_value
        sales_amount = number(row.get(sales_col)) if sales_col else None
        expense_amount = number(row.get(expense_col)) if expense_col else None
        date = date_value(row.get(date_col)) if date_col else None
        region = str(row.get(region_col)).strip() if region_col and pd.notna(row.get(region_col)) else None
        expense_category = str(row.get(expense_category_col)).strip() if expense_category_col and pd.notna(row.get(expense_category_col)) else "Other"

        product = product_map.get(product_name.lower()) if product_name else None

        if not product and product_code:
            product = product_code_map.get(product_code)

        if "products" in source_name and product_name:
            key = product_name.lower()
            product = product_map.get(key)

            if product:
                if category is not None:
                    product.category = category
                if price is not None:
                    product.price = price
            else:
                product = Product(user_id=user_id, product_name=product_name, category=category, price=price)
                db.session.add(product)
                db.session.flush()
                product_map[key] = product
                result["products"] += 1

            if product_code:
                product_code_map[product_code] = product

        if not product and product_name:
            product = product_map.get(product_name.lower())

        if product and ("sales" in source_name or sales_amount is not None):
            if sales_amount is not None or quantity is not None:
                key = (product.product_id, region or "", date, quantity, normalized_number(sales_amount))

                if key not in sales_keys:
                    new_sales.append(Sales(user_id=user_id, product_id=product.product_id, region_area=region, quantity=quantity, amount_of_sales=sales_amount, time_period=date))
                    sales_keys.add(key)
                    result["sales"] += 1

        if product and ("production" in source_name or production_quantity is not None):
            if production_quantity is not None:
                key = (product.product_id, date, production_quantity, normalized_number(price))

                if key not in production_keys:
                    new_production.append(Production(user_id=user_id, product_id=product.product_id, quantity=production_quantity, price=price, time_period=date))
                    production_keys.add(key)
                    result["production"] += 1

        if expense_amount is not None:
            key = (expense_category, date, normalized_number(expense_amount))

            if key not in expense_keys:
                new_expenses.append(Expenses(user_id=user_id, exp_category=expense_category, price=expense_amount, time_period=date))
                expense_keys.add(key)
                result["expenses"] += 1

        if "customers" in source_name and product:
            key = (product.product_id, None, date, quantity)

            if key not in customer_keys:
                new_customers.append(CustomerData(user_id=user_id, product_id=product.product_id, sales_id=None, quantity=quantity, time=date))
                customer_keys.add(key)
                result["customers"] += 1
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
    total_products = Product.query.filter_by(user_id=user_id).count()
    total_sales_records = Sales.query.filter_by(user_id=user_id).count()
    total_production = Production.query.filter_by(user_id=user_id).count()
    total_customers = CustomerData.query.filter_by(user_id=user_id).count()
    total_sales = float(db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    total_expenses = float(db.session.query(func.coalesce(func.sum(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar() or 0)
    net_amount = total_sales - total_expenses
    add_analysis("Business Data Insights", f"Your business contains {total_products} products, {total_sales_records} sales records, {total_production} production records and {total_customers} customer records. Total recorded sales are ₹{total_sales:,.2f}, expenses are ₹{total_expenses:,.2f}, and sales minus recorded expenses are ₹{net_amount:,.2f}.")

    average_sale = db.session.query(func.avg(Sales.amount_of_sales)).filter(Sales.user_id == user_id).scalar()
    if average_sale is not None:
        add_analysis("Average Sales Value", f"The average recorded transaction value is ₹{float(average_sale):,.2f} across {total_sales_records} sales records.")

    daily_rows = db.session.query(func.date(Sales.time_period).label("day"),func.sum(Sales.amount_of_sales).label("sales"),func.sum(Sales.quantity).label("quantity")).filter(Sales.user_id == user_id,Sales.time_period.isnot(None)).group_by(func.date(Sales.time_period)).order_by(func.date(Sales.time_period)).all()
    daily_sales = pd.DataFrame(daily_rows, columns=["date", "sales", "quantity"])

    if not daily_sales.empty:
        daily_sales["date"] = pd.to_datetime(daily_sales["date"], errors="coerce")
        daily_sales["sales"] = pd.to_numeric(daily_sales["sales"], errors="coerce").fillna(0)
        daily_sales["quantity"] = pd.to_numeric(daily_sales["quantity"], errors="coerce").fillna(0)
        daily_sales = daily_sales.dropna(subset=["date"]).set_index("date").sort_index()

        daily_sales = daily_sales.resample("D").sum()

        if len(daily_sales) >= 2:
            first_value = float(daily_sales["sales"].iloc[0])
            last_value = float(daily_sales["sales"].iloc[-1])
            change = last_value - first_value
            trend = "increased" if change > 0 else "decreased" if change < 0 else "remained unchanged"
            add_analysis("Historical Sales Change", f"Recorded daily sales changed from ₹{first_value:,.2f} to ₹{last_value:,.2f} between {daily_sales.index[0].date()} and {daily_sales.index[-1].date()}. Sales {trend} by ₹{abs(change):,.2f}.")

        if len(daily_sales) >= 5:
            mean_sales = float(daily_sales["sales"].mean())
            variation = float(daily_sales["sales"].std(ddof=0))
            cv = variation / mean_sales * 100 if mean_sales > 0 else 0
            level = "high" if cv > 50 else "moderate" if cv > 20 else "low"
            add_analysis("Sales Volatility", f"Daily sales have a coefficient of variation of {cv:.2f}%, indicating {level} variation relative to their average.")

        if len(daily_sales) >= 10:
            values = daily_sales["sales"].to_numpy().reshape(-1, 1)
            detector = IsolationForest(contamination="auto", random_state=42)
            detector.fit(values)
            unusual = daily_sales.loc[detector.predict(values) == -1, "sales"]

            if not unusual.empty:
                unusual_text = ", ".join(f"{date.date()}: ₹{amount:,.2f}" for date, amount in unusual.sort_values().tail(5).items())
                add_analysis("Unusual Sales Detection", f"Isolation Forest identified unusual daily sales values: {unusual_text}. Review these records for exceptional orders, promotions, or possible data errors.")

        def make_features(series):
            frame = pd.DataFrame({"sales": series})
            frame["lag_1"] = frame["sales"].shift(1)
            frame["lag_2"] = frame["sales"].shift(2)
            frame["lag_3"] = frame["sales"].shift(3)
            frame["lag_7"] = frame["sales"].shift(7)
            frame["rolling_7"] = frame["sales"].shift(1).rolling(7).mean()
            frame["day_of_week"] = frame.index.dayofweek
            frame["month"] = frame.index.month
            frame["trend"] = np.arange(len(frame))
            return frame.dropna()

        if len(daily_sales) >= 30:
            series = daily_sales["sales"].astype(float)
            features = make_features(series)

            X = features.drop(columns=["sales"])
            y = features["sales"]

            split = int(len(features) * 0.8)
            X_train, X_test = X.iloc[:split], X.iloc[split:]
            y_train, y_test = y.iloc[:split], y.iloc[split:]

            models = {
                "Linear Regression": LinearRegression(),
                "XGBoost": XGBRegressor(n_estimators=150,max_depth=3,learning_rate=0.05,subsample=0.8,colsample_bytree=0.8,objective="reg:squarederror",random_state=42,n_jobs=-1)
            }
            model_results = {}
            fitted_models = {}
            print("\n========== BIZBOY SALES MODEL EVALUATION ==========")
            for model_name, model in models.items():
                try:
                    model.fit(X_train, y_train)
                    predictions = np.maximum(0, model.predict(X_test))
                    mae = mean_absolute_error(y_test, predictions)
                    rmse = np.sqrt(mean_squared_error(y_test, predictions))
                    r2 = r2_score(y_test, predictions) if len(y_test) >= 2 else float("nan")
                    model_results[model_name] = {"MAE": mae, "RMSE": rmse, "R2": r2}
                    fitted_models[model_name] = model
                    print(f"\n{model_name}")
                    print(f"MAE: ₹{mae:,.2f}")
                    print(f"RMSE: ₹{rmse:,.2f}")
                    print(f"R² Score: {r2:.4f}")
                    add_analysis(f"{model_name} Evaluation", f"Chronological test evaluation: MAE ₹{mae:,.2f}, RMSE ₹{rmse:,.2f}, R² {r2:.4f}. These are test-set metrics, not training accuracy.")
                except Exception as model_error:
                    print(f"{model_name} failed: {model_error}")
            print("\n===================================================\n")

            if fitted_models:
                best_name = min(model_results, key=lambda name: model_results[name]["MAE"])
                best_model = fitted_models[best_name]
                add_analysis("Best Forecasting Model", f"{best_name} achieved the lowest test MAE of ₹{model_results[best_name]['MAE']:,.2f} among the successfully evaluated models. Model selection is based on historical test performance.")
                future_series = series.copy()
                future_predictions = []
                for step in range(7):
                    next_date = future_series.index[-1] + pd.Timedelta(days=1)
                    next_features = pd.DataFrame([{
                        "lag_1": future_series.iloc[-1],
                        "lag_2": future_series.iloc[-2],
                        "lag_3": future_series.iloc[-3],
                        "lag_7": future_series.iloc[-7],
                        "rolling_7": future_series.iloc[-7:].mean(),
                        "day_of_week": next_date.dayofweek,
                        "month": next_date.month,
                        "trend": len(future_series)
                    }], index=[next_date])
                    prediction = max(0.0, float(best_model.predict(next_features)[0]))
                    future_predictions.append((next_date, prediction))
                    future_series.loc[next_date] = prediction
                forecast_total = sum(value for date, value in future_predictions)
                forecast_average = forecast_total / 7
                forecast_text = ", ".join(f"{date.strftime('%d %b')}: ₹{value:,.2f}" for date, value in future_predictions)
                add_analysis("Next 7 Days Sales Forecast", f"{best_name} forecasts total sales of approximately ₹{forecast_total:,.2f} over the next 7 calendar days, averaging ₹{forecast_average:,.2f} per day. Daily estimates: {forecast_text}. These are model estimates, not guaranteed revenue.")
                previous_week = float(series.tail(7).sum())
                if previous_week > 0:
                    forecast_change = (forecast_total - previous_week) / previous_week * 100
                    direction = "increase" if forecast_change > 0 else "decrease" if forecast_change < 0 else "no change"
                    add_analysis("Forecasted Sales Trend", f"The next 7-day forecast indicates a possible {abs(forecast_change):.2f}% {direction} compared with the previous 7 recorded calendar days.")

        else:
            add_analysis("Sales Forecast Data Requirement", f"There are {len(daily_sales)} daily observations. At least 30 calendar days are required by this forecasting setup before comparing Linear Regression and XGBoost reliably. More history may improve evaluation.")
    product_rows = db.session.query(Sales.product_id,Product.product_name,func.date(Sales.time_period).label("day"),func.sum(Sales.quantity).label("quantity"),func.sum(Sales.amount_of_sales).label("revenue")).join(Product,(Sales.product_id == Product.product_id) &
    (Product.user_id == user_id)).filter(Sales.user_id == user_id,Sales.time_period.isnot(None)).group_by(Sales.product_id,Product.product_name,func.date(Sales.time_period)).order_by(Sales.product_id,func.date(Sales.time_period)).all()
    product_df = pd.DataFrame(product_rows, columns=["product_id", "product_name", "date", "quantity", "revenue"])

    if not product_df.empty:
        product_df["date"] = pd.to_datetime(product_df["date"], errors="coerce")
        product_df["quantity"] = pd.to_numeric(product_df["quantity"], errors="coerce").fillna(0)
        product_df["revenue"] = pd.to_numeric(product_df["revenue"], errors="coerce").fillna(0)
        product_df = product_df.dropna(subset=["date"])
        latest_date = product_df["date"].max().normalize()
        recent_start = latest_date - pd.Timedelta(days=6)
        previous_start = latest_date - pd.Timedelta(days=13)
        product_insights = []
        for product_id, group in product_df.groupby("product_id"):
            recent = float(group.loc[group["date"] >= recent_start, "quantity"].sum())
            previous = float(group.loc[(group["date"] >= previous_start) & (group["date"] < recent_start), "quantity"].sum())
            if recent == 0 and previous == 0:
                continue
            if previous > 0:
                growth = (recent - previous) / previous * 100
                direction = "growing" if growth > 0 else "declining" if growth < 0 else "stable"
            elif recent > 0:
                growth = None
                direction = "new or recently active"
            else:
                growth = -100
                direction = "no recent demand"
            product_name = str(group["product_name"].iloc[0] or f"Product {product_id}")
            product_insights.append({
                "name": product_name,
                "recent": recent,
                "previous": previous,
                "growth": growth,
                "direction": direction,
                "revenue": float(group["revenue"].sum())
            })
        growing = sorted([p for p in product_insights if p["growth"] is not None and p["growth"] > 0], key=lambda p: p["growth"], reverse=True)
        declining = sorted([p for p in product_insights if p["growth"] is not None and p["growth"] < 0], key=lambda p: p["growth"])
        for item in growing[:5]:
            add_analysis("Growing Product Demand", f"{item['name']} sold {item['recent']:,.0f} units in the latest 7 calendar days compared with {item['previous']:,.0f} in the previous 7 days. Recorded quantity demand increased by {item['growth']:.2f}%. Consider checking stock availability.")
        for item in declining[:5]:
            add_analysis("Declining Product Demand", f"{item['name']} sold {item['recent']:,.0f} units in the latest 7 calendar days compared with {item['previous']:,.0f} in the previous 7 days. Recorded quantity demand declined by {abs(item['growth']):.2f}%. Review pricing, availability, and customer interest.")
        if not growing and not declining:
            add_analysis("Product Demand Trends", "No clear growing or declining product demand was identified from the available 7-day comparisons.")
        top_product = max(product_insights, key=lambda p: p["revenue"], default=None)

        if top_product:
            add_analysis("Leading Product", f"{top_product['name']} has the highest recorded product revenue among the analyzed products, approximately ₹{top_product['revenue']:,.2f}.")
    if total_sales > 0:
        if net_amount >= 0:
            add_analysis("Sales and Expense Outlook", f"Recorded sales exceed recorded expenses by ₹{net_amount:,.2f}. This is a basic difference, not necessarily accounting profit.")
        else:
            add_analysis("Sales and Expense Outlook", f"Recorded expenses exceed recorded sales by ₹{abs(net_amount):,.2f}. Review business costs and revenue.")
    if total_production:
        add_analysis("Production Data Coverage", f"The database contains {total_production} production records. Compare production quantities with sales demand to identify potential inventory gaps.")

    if total_customers:
        add_analysis("Customer Data Coverage", f"The database contains {total_customers} customer records. Linking customer IDs with sales can enable customer segmentation and purchasing-pattern analysis.")

    db.session.add_all(analyses[:25])
    db.session.commit()
    
    print(f"BIZBOY: Generated {min(len(analyses), 25)} automated business insights.")

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

    create_analysis(user_id)
    analysis = Analysis.query.filter_by(user_id=user_id).order_by(Analysis.ana_id.desc()).all()
    products = Product.query.filter_by(user_id=user_id).order_by(Product.product_name.asc()).limit(10).all()

    monthly_sales_rows = db.session.execute(text("""
        SELECT
            DATE_TRUNC('month', time_period::timestamp) AS month,
            SUM(amount_of_sales) AS total
        FROM sales
        WHERE user_id = :user_id
          AND time_period IS NOT NULL
        GROUP BY 1
        ORDER BY 1
    """),{"user_id": user_id}).fetchall()
    
    monthly_expense_rows = db.session.execute(
        text("""
            SELECT
                DATE_TRUNC('month', time_period::timestamp) AS month,
                SUM(price) AS total
            FROM expenses
            WHERE user_id = :user_id
              AND time_period IS NOT NULL
            GROUP BY 1
            ORDER BY 1
        """),{"user_id": user_id}).fetchall()
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
#@cache.cached(timeout=300, key_prefix=lambda: f"sales_{session.get('user_id', 'anonymous')}_{request.args.get('page', '1')}")
def sales_page():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))

    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))

    page = max(request.args.get("page", 1, type=int), 1)
    per_page = 50

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
#@cache.cached(timeout=300, key_prefix=lambda: f"products_{session.get('user_id', 'anonymous')}_{request.args.get('page', '1')}_{request.args.get('search', '').strip()}")
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



@home.route("/analysis")
def analysis():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))

    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))

    try:
        create_analysis(user_id)
    except Exception as error:
        db.session.rollback()
        print("ANALYSIS UPDATE ERROR:", error)

    analysis = Analysis.query.filter_by(user_id=user_id, analysis_type="Automated Summary").order_by(Analysis.ana_id.desc()).all()

    total_sales = float(db.session.query(func.coalesce(func.sum(Sales.amount_of_sales), 0)).filter(Sales.user_id == user_id).scalar() or 0)
    total_quantity = int(db.session.query(func.coalesce(func.sum(Sales.quantity), 0)).filter(Sales.user_id == user_id).scalar() or 0)

    daily_rows = db.session.query(func.date(Sales.time_period).label("day"), func.sum(Sales.amount_of_sales).label("sales")).filter(Sales.user_id == user_id, Sales.time_period.isnot(None)).group_by(func.date(Sales.time_period)).order_by(func.date(Sales.time_period)).all()

    forecast_chart = go.Figure()
    forecast_available = False
    forecast_total = 0
    forecast_average = 0

    if daily_rows:
        daily_df = pd.DataFrame(daily_rows, columns=["date", "sales"])
        daily_df["date"] = pd.to_datetime(daily_df["date"], errors="coerce")
        daily_df["sales"] = pd.to_numeric(daily_df["sales"], errors="coerce").fillna(0)
        daily_df = daily_df.dropna(subset=["date"]).set_index("date").sort_index().resample("D").sum()

        if len(daily_df) >= 2:
            recent_sales = daily_df.tail(30)

            X = np.arange(len(recent_sales)).reshape(-1, 1)
            y = recent_sales["sales"].to_numpy(dtype=float)

            model = LinearRegression().fit(X, y)

            future_dates = pd.date_range(start=recent_sales.index[-1] + pd.Timedelta(days=1), end=recent_sales.index[-1] + pd.DateOffset(months=1), freq="D")
            future_X = np.arange(len(recent_sales), len(recent_sales) + len(future_dates)).reshape(-1, 1)
            predictions = np.maximum(0, model.predict(future_X))

            forecast_total = float(predictions.sum())
            forecast_average = float(predictions.mean())
            forecast_available = True

            forecast_chart.add_trace(go.Bar(
                x=recent_sales.index,
                y=recent_sales["sales"],
                name="Historical Sales",
                marker_color="#7181ef",
                hovertemplate="%{x|%d %b %Y}<br>Actual Sales: ₹%{y:,.2f}<extra></extra>"
            ))

            forecast_chart.add_trace(go.Bar(
                x=future_dates,
                y=predictions,
                name="Predicted Sales",
                marker_color="#10b981",
                hovertemplate="%{x|%d %b %Y}<br>Predicted Sales: ₹%{y:,.2f}<extra></extra>"
            ))

    if not forecast_available:
        forecast_chart.add_annotation(text="At least 2 dated sales observations are required for a forecast", x=0.5, y=0.5, xref="paper", yref="paper", showarrow=False, font=dict(color="#94a3b8", size=13))

    forecast_chart.update_layout(
        barmode="group",
        xaxis=dict(title="Date", type="date", tickformat="%d %b"),
        yaxis=dict(title="Sales Amount (₹)", rangemode="tozero"),
        hovermode="x unified",
        showlegend=True,
        legend=dict(orientation="h", y=1.12, x=0),
        margin=dict(l=15, r=15, t=45, b=15)
    )

    forecast_chart = apply_dark(forecast_chart)

    return render_template(
        "analysis.html",
        user=user,
        analysis=analysis,
        total_analysis=len(analysis),
        total_sales=total_sales,
        total_quantity=total_quantity,
        forecast_total=forecast_total,
        forecast_average=forecast_average,
        forecast_available=forecast_available,
        forecast_chart=json.dumps(forecast_chart, cls=PlotlyJSONEncoder)
    )

#Production
@home.route("/production")
def production():
    if "user_id" not in session:
        return redirect(url_for("home.homepg"))

    user_id = session["user_id"]
    user = db.session.get(User, user_id)

    if not user:
        session.pop("user_id", None)
        return redirect(url_for("home.homepg"))

    search = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 15

    base_query = db.session.query(Production, Product).outerjoin(Product, Production.product_id == Product.product_id).filter(Production.user_id == user_id)

    total_records = Production.query.filter_by(user_id=user_id).count()
    total_quantity = db.session.query(func.coalesce(func.sum(Production.quantity), 0)).filter(Production.user_id == user_id).scalar() or 0
    total_production_value = db.session.query(func.coalesce(func.sum(Production.quantity * Production.price), 0)).filter(Production.user_id == user_id).scalar() or 0
    unique_products = db.session.query(func.count(func.distinct(Production.product_id))).filter(Production.user_id == user_id).scalar() or 0

    monthly_rows = db.session.query(func.date_trunc("month", Production.time_period).label("month"), func.coalesce(func.sum(Production.quantity), 0).label("quantity")).filter(Production.user_id == user_id, Production.time_period.isnot(None)).group_by(func.date_trunc("month", Production.time_period)).order_by(func.date_trunc("month", Production.time_period)).all()

    monthly_labels = [row.month.strftime("%b %Y") for row in monthly_rows]
    monthly_quantities = [float(row.quantity or 0) for row in monthly_rows]

    monthly_production_fig = go.Figure()
    monthly_production_fig.add_trace(go.Bar(x=monthly_labels, y=monthly_quantities, name="Units Produced", marker_color="#38BDF8", marker_line_width=0, hovertemplate="%{x}<br>Units: %{y:,.0f}<extra></extra>"))
    monthly_production_fig.update_layout(title=None, xaxis_title=None, yaxis_title="Units Produced", showlegend=False, margin=dict(l=45, r=20, t=20, b=55))
    apply_dark(monthly_production_fig)

    product_rows = db.session.query(Product.product_name, func.coalesce(func.sum(Production.quantity), 0).label("quantity")).join(Production, Production.product_id == Product.product_id).filter(Production.user_id == user_id).group_by(Product.product_name).order_by(func.sum(Production.quantity).desc()).limit(10).all()

    product_labels = [row.product_name or "Unknown Product" for row in product_rows]
    product_quantities = [float(row.quantity or 0) for row in product_rows]

    product_production_fig = go.Figure()
    product_production_fig.add_trace(go.Bar(x=product_quantities, y=product_labels, orientation="h", marker_color="#2563EB", marker_line_width=0, hovertemplate="%{y}<br>Units: %{x:,.0f}<extra></extra>"))
    product_production_fig.update_layout(title=None, xaxis_title="Units Produced", yaxis_title=None, showlegend=False, yaxis=dict(autorange="reversed"), margin=dict(l=110, r=25, t=20, b=45))
    apply_dark(product_production_fig)

    value_rows = db.session.query(func.date_trunc("month", Production.time_period).label("month"), func.coalesce(func.sum(Production.quantity * Production.price), 0).label("value")).filter(Production.user_id == user_id, Production.time_period.isnot(None)).group_by(func.date_trunc("month", Production.time_period)).order_by(func.date_trunc("month", Production.time_period)).all()

    value_labels = [row.month.strftime("%b %Y") for row in value_rows]
    production_values = [float(row.value or 0) for row in value_rows]

    production_value_fig = go.Figure()
    production_value_fig.add_trace(go.Scatter(x=value_labels, y=production_values, mode="lines+markers", name="Production Value", line=dict(color="#0EA5E9", width=3), marker=dict(size=7, color="#38BDF8"), fill="tozeroy", fillcolor="rgba(14, 165, 233, 0.10)", hovertemplate="%{x}<br>Value: ₹%{y:,.2f}<extra></extra>"))
    production_value_fig.update_layout(title=None, xaxis_title=None, yaxis_title="Production Value (₹)", showlegend=False, margin=dict(l=65, r=20, t=20, b=55))
    apply_dark(production_value_fig)

    distribution_rows = db.session.query(Product.product_name, func.coalesce(func.sum(Production.quantity), 0).label("quantity")).join(Production, Production.product_id == Product.product_id).filter(Production.user_id == user_id).group_by(Product.product_name).order_by(func.sum(Production.quantity).desc()).limit(8).all()

    distribution_labels = [row.product_name or "Unknown Product" for row in distribution_rows]
    distribution_quantities = [float(row.quantity or 0) for row in distribution_rows]

    production_distribution_fig = go.Figure()
    production_distribution_fig.add_trace(go.Pie(labels=distribution_labels, values=distribution_quantities, hole=0.62, textinfo="percent", marker=dict(colors=["#38BDF8", "#0EA5E9", "#2563EB", "#6366F1", "#1D4ED8", "#0284C7", "#60A5FA", "#1E40AF"]), hovertemplate="%{label}<br>Units: %{value:,.0f}<br>Share: %{percent}<extra></extra>"))
    production_distribution_fig.update_layout(title=None, showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5), margin=dict(l=20, r=20, t=15, b=65))
    apply_dark(production_distribution_fig)

    if search:
        search_pattern = f"%{search}%"
        base_query = base_query.filter(or_(Product.product_name.ilike(search_pattern), cast(Production.quantity, String).ilike(search_pattern), cast(Production.price, String).ilike(search_pattern), cast(Production.time_period, String).ilike(search_pattern)))

    filtered_records = base_query.count()
    total_pages = max(1, (filtered_records + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))

    production_records = base_query.order_by(Production.time_period.desc().nullslast()).offset((page - 1) * per_page).limit(per_page).all()

    start_record = (page - 1) * per_page + 1 if filtered_records > 0 else 0
    end_record = min(page * per_page, filtered_records)

    monthly_production_chart = json.dumps(monthly_production_fig, cls=PlotlyJSONEncoder)
    product_production_chart = json.dumps(product_production_fig, cls=PlotlyJSONEncoder)
    production_value_chart = json.dumps(production_value_fig, cls=PlotlyJSONEncoder)
    production_distribution_chart = json.dumps(production_distribution_fig, cls=PlotlyJSONEncoder)

    return render_template("production.html", total_production_value=float(total_production_value), total_records=total_records, total_quantity=total_quantity, unique_products=unique_products, monthly_production_chart=monthly_production_chart, product_production_chart=product_production_chart, production_value_chart=production_value_chart, production_distribution_chart=production_distribution_chart, production_records=production_records, search=search, page=page, total_pages=total_pages, start_record=start_record, end_record=end_record, filtered_records=filtered_records)


@home.route("/expenses")
def expenses():
    if "user_id" not in session:
        return redirect(url_for("auth.login"))

    user_id = session["user_id"]
    search = request.args.get("q", "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 15

    total_expenses = db.session.query(func.coalesce(func.sum(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar() or 0
    total_records = Expenses.query.filter_by(user_id=user_id).count()
    average_expense = db.session.query(func.coalesce(func.avg(Expenses.price), 0)).filter(Expenses.user_id == user_id).scalar() or 0
    unique_categories = db.session.query(func.count(func.distinct(Expenses.exp_category))).filter(Expenses.user_id == user_id).scalar() or 0

    monthly_data = db.session.query(func.date_trunc("month", Expenses.time_period).label("month"), func.sum(Expenses.price).label("amount")).filter(Expenses.user_id == user_id, Expenses.time_period.isnot(None)).group_by(func.date_trunc("month", Expenses.time_period)).order_by(func.date_trunc("month", Expenses.time_period)).all()

    category_data = db.session.query(func.coalesce(Expenses.exp_category, "Uncategorized").label("category"), func.sum(Expenses.price).label("amount")).filter(Expenses.user_id == user_id).group_by(func.coalesce(Expenses.exp_category, "Uncategorized")).order_by(func.sum(Expenses.price).desc()).all()

    month_labels = [row.month.strftime("%b %Y") for row in monthly_data]
    month_amounts = [float(row.amount or 0) for row in monthly_data]
    category_labels = [row.category for row in category_data]
    category_amounts = [float(row.amount or 0) for row in category_data]

    monthly_fig = go.Figure(go.Bar(x=month_labels, y=month_amounts, marker_color="#38bdf8", name="Expenses"))
    monthly_fig.update_layout(title="Monthly Expenses", xaxis_title="Month", yaxis_title="Amount (₹)")
    apply_dark(monthly_fig)

    category_fig = go.Figure(go.Pie(labels=category_labels, values=category_amounts, hole=0.55))
    category_fig.update_layout(title="Expenses by Category")
    apply_dark(category_fig)

    trend_fig = go.Figure(go.Scatter(x=month_labels, y=month_amounts, mode="lines+markers", line=dict(color="#a78bfa", width=3), marker=dict(size=8), name="Expense Trend"))
    trend_fig.update_layout(title="Expense Trend", xaxis_title="Month", yaxis_title="Amount (₹)")
    apply_dark(trend_fig)

    top_data = category_data[:10]
    top_fig = go.Figure(go.Bar(x=[float(row.amount or 0) for row in top_data], y=[row.category for row in top_data], orientation="h", marker_color="#0ea5e9"))
    top_fig.update_layout(title="Top Expense Categories", xaxis_title="Amount (₹)", yaxis_title="Category", yaxis=dict(autorange="reversed"))
    apply_dark(top_fig)

    query = Expenses.query.filter_by(user_id=user_id)

    if search:
        query = query.filter(or_(Expenses.exp_category.ilike(f"%{search}%"), cast(Expenses.price, String).ilike(f"%{search}%"), cast(Expenses.time_period, String).ilike(f"%{search}%")))

    filtered_records = query.count()
    total_pages = max(1, (filtered_records + per_page - 1) // per_page)
    page = max(1, min(page, total_pages))
    expenses = query.order_by(Expenses.time_period.desc()).paginate(page=page, per_page=per_page, error_out=False).items

    return render_template("expenses.html", total_expenses=total_expenses, total_records=total_records, average_expense=average_expense, unique_categories=unique_categories, monthly_expenses_chart=json.dumps(monthly_fig, cls=PlotlyJSONEncoder), category_expenses_chart=json.dumps(category_fig, cls=PlotlyJSONEncoder), expense_trend_chart=json.dumps(trend_fig, cls=PlotlyJSONEncoder), top_categories_chart=json.dumps(top_fig, cls=PlotlyJSONEncoder), expenses=expenses, search=search, page=page, per_page=per_page, total_pages=total_pages, filtered_records=filtered_records)