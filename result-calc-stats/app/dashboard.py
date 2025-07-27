from streamlit_autorefresh import st_autorefresh
import streamlit as st
import sqlite3
import struct
import pandas as pd

DB_PATH = "data/warmup_success_params.sqlite"
conn = sqlite3.connect(DB_PATH)

def decode_sqlite_int(val):
    if isinstance(val, bytes):
        return struct.unpack("<q", val)[0]  # little endian 8-byte int
    return val

@st.cache_data
def load_data():
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM warmup_params", conn)
    conn.close()
    df["success_rate"] = df["success_count"] / df["total_count"].clip(lower=1)
    df["blur"] = df["blur"].apply(decode_sqlite_int)
    df["gaussian_blur"] = df["gaussian_blur"].apply(decode_sqlite_int)
    return df

df = load_data()

st.subheader("全体統計")
st_autorefresh(interval=30 * 1000, key="refresh_dashboard")

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
st.scatter_chart(df[["total_count", "success_rate"]])

st.subheader("ヒストグラム")
param = st.selectbox("パラメータを選択", [col for col in df.columns[:-3] if col != "id"])
st.bar_chart(df[param].value_counts().sort_index().drop(labels=["id"], errors="ignore"))

st.subheader("成功率上位パラメータ")
st.dataframe(df.sort_values("success_rate", ascending=False).head(10), use_container_width=True)
