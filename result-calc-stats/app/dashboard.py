from streamlit_autorefresh import st_autorefresh
import streamlit as st
import sqlite3
import struct
import pandas as pd
import altair as alt

def stored_int_to_float(stored: int) -> float:
    """保存された整数を小数に戻す（例: 21 → 1.2）"""
    whole = stored % 10
    decimal = stored // 10
    return whole + decimal / 10

DB_PATH = "data/warmup_success_params.sqlite"
# Removed unused global database connection to prevent resource leaks

def decode_sqlite_int(val):
    if isinstance(val, bytes):
        return struct.unpack("<q", val)[0]  # little endian 8-byte int
    return val

# @st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM warmup_params", conn)
    conn.close()

    # BLOB 形式の整数を数値に変換
    df["blur"] = df["blur"].apply(decode_sqlite_int)
    df["gaussian_blur"] = df["gaussian_blur"].apply(decode_sqlite_int)
    df["total_count"] = df["total_count"].apply(decode_sqlite_int)
    df["success_count"] = df["success_count"].apply(decode_sqlite_int)
    df["contrast_scaled"] = df["contrast_scaled"].apply(decode_sqlite_int).apply(stored_int_to_float)
    df["resize_ratio_scaled"] = df["resize_ratio_scaled"].apply(decode_sqlite_int).apply(stored_int_to_float)
    MAX_SUCCESS_COUNT = 30
    effective_success = df["success_count"].clip(upper=MAX_SUCCESS_COUNT)
    df["success_rate"] = (df["success_count"] / df["total_count"].clip(lower=1)) * effective_success
    return df

df = load_data()

st.subheader("全体統計")
st_autorefresh(interval=60 * 1000, key="refresh_dashboard")

# パラメータ空間サイズの定義
total_param_space = (
    120 *  # threshold (100–219)
    5 *    # blur
    141 *  # contrast_scaled (0.60–2.00 at 0.01 step → 141 values)
    101 *  # resize_ratio_scaled (0.60–1.60 at 0.01 step → 101 values)
    6 *    # gaussian_blur
    2      # use_clahe
)

unique_params = df[
    ["threshold", "blur", "contrast_scaled", "resize_ratio_scaled", "gaussian_blur", "use_clahe"]
].drop_duplicates().shape[0]

coverage_rate = unique_params / total_param_space * 100


col1, col2 ,col3 = st.columns(3)
col1.metric("総試行数", int(df["total_count"].sum()))
col2.metric("パラメータ空間カバー率", f"{coverage_rate:.3f}%")
col3.metric("成功率", f'{(df["success_count"].sum() / df["total_count"].sum()) * 100:.2f}%')

st.subheader("成功率 vs 試行数（散布図）")
st.altair_chart(
    alt.Chart(df).mark_circle().encode(
        x=alt.X("id:Q", scale=alt.Scale(domainMin=0), title="総試行数"),
        y=alt.Y("success_rate:Q", scale=alt.Scale(domainMin=0), title="成功率")
    ).properties(height=400),
    use_container_width=True
)

st.subheader("ヒストグラム")
param_options = [col for col in df.columns[:-3] if col != "id"]
param = st.selectbox("パラメータを選択", param_options)
chart_data = df[param].value_counts().sort_index()

bar_chart_df = chart_data.reset_index()
bar_chart_df.columns = [param, "count"]

chart = alt.Chart(bar_chart_df).mark_bar().encode(
    x=alt.X(f"{param}:O", title=param),
    y=alt.Y("count:Q", title="Count", scale=alt.Scale(domain=[0, chart_data.max() * 1.1]))
)

st.altair_chart(chart, use_container_width=True)

st.subheader("成功率上位パラメータ")
st.dataframe(df.sort_values("success_rate", ascending=False).head(10), use_container_width=True)
