# app.py — Astra (AI Ecommerce Analyst)
# Run: streamlit run app.py

import os
import pandas as pd
import matplotlib.pyplot as plt
import streamlit as st
import requests

# ----------------------------
# Page config / Branding
# ----------------------------
st.set_page_config(page_title="Astra — AI Ecommerce Analyst", layout="wide")

st.title("✨ Astra — AI Ecommerce Analyst")
st.caption("Where data becomes direction.")
st.write("See your store clearly — upload your ecommerce CSV to get instant insights.")

# ----------------------------
# Sidebar: API Key + Settings
# ----------------------------
st.sidebar.header("🔑 API Settings")

# --- Groq API Key (auto from Streamlit secrets; fallback to env var; optional manual input for local) ---
groq_api_key = None

# 1) Streamlit Cloud secrets (preferred)
if "GROQ_API_KEY" in st.secrets:
    groq_api_key = st.secrets["GROQ_API_KEY"]

# 2) Local environment variable fallback
elif os.getenv("GROQ_API_KEY"):
    groq_api_key = os.getenv("GROQ_API_KEY")

# 3) Optional manual input fallback (local dev only)
else:
    with st.sidebar:
        st.header("🔑 API Settings")
        groq_api_key = st.text_input("Groq API Key", type="password")
        st.caption("For Streamlit Cloud, store this in Secrets instead.")

st.sidebar.markdown("---")
show_debug = st.sidebar.checkbox("Show debug info (columns + dtypes)", value=False)

# ----------------------------
# Robust CSV Loader
# ----------------------------
def load_csv_any_encoding(file) -> pd.DataFrame:
    """
    Tries multiple encodings and safely rewinds the uploaded file each attempt.
    """
    encodings_to_try = ["utf-8", "latin1", "ISO-8859-1", "cp1252"]

    last_err = None
    for enc in encodings_to_try:
        try:
            file.seek(0)
            return pd.read_csv(file, encoding=enc)
        except Exception as e:
            last_err = e
            continue

    # Final fallback: ignore bad characters
    file.seek(0)
    try:
        return pd.read_csv(
            file,
            encoding="ISO-8859-1",
            engine="python",
            encoding_errors="ignore"
        )
    except Exception as e:
        raise RuntimeError(f"Could not read CSV. Last error: {last_err}") from e

# ----------------------------
# Helpers: smart default column choices
# ----------------------------
def guess_date_column(cols):
    candidates = [c for c in cols if "date" in c.lower() or "time" in c.lower()]
    return candidates[0] if candidates else cols[0]

def guess_product_column(cols):
    for key in ["description", "product", "item", "title", "name", "sku"]:
        candidates = [c for c in cols if key in c.lower()]
        if candidates:
            return candidates[0]
    return cols[0]

def guess_numeric_column(cols):
    if "Revenue" in cols:
        return "Revenue"
    for key in ["sales", "revenue", "amount", "total", "price"]:
        candidates = [c for c in cols if key in c.lower()]
        if candidates:
            return candidates[0]
    return cols[0]

# ----------------------------
# File upload
# ----------------------------
uploaded_file = st.file_uploader("📂 Upload a CSV file", type=["csv"])

if uploaded_file is None:
    st.info("☝️ Upload a CSV file to get started.")
    st.stop()

# Load CSV
try:
    df = load_csv_any_encoding(uploaded_file)
except Exception as e:
    st.error(f"Could not read your CSV: {e}")
    st.stop()

# Remove obvious junk columns
df = df.loc[:, ~df.columns.astype(str).str.contains("^Unnamed", case=False, regex=True)]

# Add ecommerce-friendly Revenue column if possible
if "Quantity" in df.columns and "UnitPrice" in df.columns:
    df["Revenue"] = pd.to_numeric(df["Quantity"], errors="coerce") * pd.to_numeric(df["UnitPrice"], errors="coerce")

# Preview
st.subheader("👀 Preview of Data")
st.dataframe(df.head(20), use_container_width=True)

if show_debug:
    st.markdown("**Detected columns:**")
    st.write(list(df.columns))
    st.markdown("**Detected dtypes:**")
    st.write(df.dtypes)

# ----------------------------
# Column selection UI
# ----------------------------
st.subheader("⚙️ Choose Columns")

cols = list(df.columns)

default_date = guess_date_column(cols)
default_product = guess_product_column(cols)
default_numeric = guess_numeric_column(cols)

c1, c2, c3 = st.columns(3)

with c1:
    date_col = st.selectbox(
        "📅 Date column",
        options=cols,
        index=cols.index(default_date) if default_date in cols else 0
    )

with c2:
    num_col = st.selectbox(
        "💰 Numeric column (Revenue is best)",
        options=cols,
        index=cols.index(default_numeric) if default_numeric in cols else 0
    )

with c3:
    product_col = st.selectbox(
        "🧾 Product column",
        options=cols,
        index=cols.index(default_product) if default_product in cols else 0
    )

st.caption("Tip: For ecommerce, use **Revenue** (Quantity × UnitPrice) and **Description** as product.")

# ----------------------------
# Run Analysis
# ----------------------------
if st.button("🔍 Run Analysis"):
    df_clean = df.copy()

    # Convert types
    df_clean[date_col] = pd.to_datetime(df_clean[date_col], errors="coerce")
    df_clean[num_col] = pd.to_numeric(df_clean[num_col], errors="coerce")

    # Drop unusable rows
    df_clean = df_clean.dropna(subset=[date_col, num_col])

    if df_clean.empty:
        st.error("No valid data after cleaning. Try different columns.")
        st.stop()

    # ----------------------------
    # Basic summary
    # ----------------------------
    st.subheader("📌 Basic Summary")
    a, b, c = st.columns(3)
    a.metric("Rows (clean)", f"{len(df_clean):,}")
    b.metric("Date range", f"{df_clean[date_col].min().date()} → {df_clean[date_col].max().date()}")
    c.metric(f"Total {num_col}", f"{df_clean[num_col].sum():,.2f}")

    # ----------------------------
    # CLEAN Revenue Trend (monthly + remove returns)
    # ----------------------------
    st.subheader("📈 Revenue Trend Over Time")

    df_ts = df_clean.copy()

    # Remove returns/refunds for trend (negative Quantity)
    if "Quantity" in df_ts.columns:
        df_ts["Quantity"] = pd.to_numeric(df_ts["Quantity"], errors="coerce")
        df_ts = df_ts[df_ts["Quantity"] > 0]

    df_ts = df_ts.dropna(subset=[date_col, num_col])

    df_ts["Month"] = df_ts[date_col].dt.to_period("M").dt.to_timestamp()
    monthly = df_ts.groupby("Month")[num_col].sum().reset_index()

    fig = plt.figure(figsize=(10, 4))
    plt.plot(monthly["Month"], monthly[num_col], marker="o")
    plt.title("Revenue Trend (Monthly)")
    plt.xlabel("Month")
    plt.ylabel(num_col)
    plt.grid(True)
    plt.xticks(rotation=45)
    st.pyplot(fig)
    plt.close(fig)

    # ----------------------------
    # Top products by Revenue (TABLE + bar chart)
    # ----------------------------
    st.subheader("🏆 Top 10 Best-Selling Products")

    df_prod = df_clean.copy()

    # Remove returns for top-products calculation too
    if "Quantity" in df_prod.columns:
        df_prod["Quantity"] = pd.to_numeric(df_prod["Quantity"], errors="coerce")
        df_prod = df_prod[df_prod["Quantity"] > 0]

    # Clean product names
    df_prod[product_col] = df_prod[product_col].astype(str).str.strip()
    df_prod = df_prod[df_prod[product_col].notna()]
    df_prod = df_prod[df_prod[product_col] != ""]
    df_prod = df_prod[df_prod[product_col].str.lower() != "nan"]

    # Compute top products FIRST (so variable exists for table + chart)
    top_products = (
        df_prod.groupby(product_col)[num_col]
        .sum()
        .sort_values(ascending=False)
        .head(10)
    )

    # Table
    top_products_df = (
        top_products
        .reset_index()
        .rename(columns={product_col: "Product", num_col: "Total Revenue"})
    )
    st.dataframe(top_products_df, use_container_width=True)

    # Horizontal bar chart (readable)
    fig = plt.figure(figsize=(10, 5))
    top_products.sort_values().plot(kind="barh")
    plt.title("Top 10 Products by Revenue")
    plt.xlabel("Revenue")
    plt.ylabel("Product")
    plt.tight_layout()
    st.pyplot(fig)
    plt.close(fig)

    # ----------------------------
    # Declining products (Last 30 days vs Previous 30 days)
    # ----------------------------
    st.subheader("📉 Declining Products (Last 30 days vs Previous 30 days)")

    df_decl = df_clean.copy()

    if "Quantity" in df_decl.columns:
        df_decl["Quantity"] = pd.to_numeric(df_decl["Quantity"], errors="coerce")
        df_decl = df_decl[df_decl["Quantity"] > 0]

    df_decl[product_col] = df_decl[product_col].astype(str).str.strip()
    df_decl = df_decl[df_decl[product_col].notna()]
    df_decl = df_decl[df_decl[product_col] != ""]
    df_decl = df_decl[df_decl[product_col].str.lower() != "nan"]

    max_date = df_decl[date_col].max()
    last_30_start = max_date - pd.Timedelta(days=30)
    prev_30_start = max_date - pd.Timedelta(days=60)

    last_30 = df_decl[(df_decl[date_col] > last_30_start) & (df_decl[date_col] <= max_date)]
    prev_30 = df_decl[(df_decl[date_col] > prev_30_start) & (df_decl[date_col] <= last_30_start)]

    last_sum = last_30.groupby(product_col)[num_col].sum()
    prev_sum = prev_30.groupby(product_col)[num_col].sum()

    compare = pd.DataFrame({
        "Previous 30 days": prev_sum,
        "Last 30 days": last_sum
    }).fillna(0.0)

    compare["Change"] = compare["Last 30 days"] - compare["Previous 30 days"]
    compare["% Change"] = compare.apply(
        lambda r: (r["Change"] / r["Previous 30 days"] * 100) if r["Previous 30 days"] > 0 else None,
        axis=1
    )

    declining = compare.sort_values("Change").head(10).reset_index().rename(columns={product_col: "Product"})
    st.dataframe(declining, use_container_width=True)

    # ----------------------------
    # AI Insights (Groq)
    # ----------------------------
    st.subheader("🤖 AI Insights")
    st.caption("Tip: You can store your key once on your Mac and never paste again (we’ll do that next).")

    st.info(
        "🤖 AI Insights will be available in the public version of Astra. "
        "This demo focuses on core ecommerce analytics."
    )

    # Compact summary for LLM (reduce tokens)
    summary = {
        "rows_clean": int(len(df_clean)),
        "date_range": [str(df_clean[date_col].min()), str(df_clean[date_col].max())],
        "total_metric": float(df_clean[num_col].sum()),
        "top_products": top_products.head(5).to_dict(),
        "declining_products": declining.head(5).to_dict(orient="records"),
        "columns": list(df.columns),
    }

    prompt = f"""
You are a senior ecommerce analyst.

Given this dataset summary, provide:
1) 5 key revenue insights (seasonality, spikes, growth/decline)
2) 3 likely reasons behind these patterns
3) 5 actionable recommendations for the store owner (specific, practical, prioritized)

DATA SUMMARY:
{summary}
"""

    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3
    }

    with st.spinner("Generating AI insights..."):
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=60)
            data = resp.json()

            if "choices" not in data:
                st.error(f"AI error: {data}")
            else:
                insights = data["choices"][0]["message"]["content"]
                st.markdown(insights)

        except Exception as e:
            st.error(f"Request failed: {e}")
