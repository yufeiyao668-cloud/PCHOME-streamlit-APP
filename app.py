# -*- coding: utf-8 -*-
import re
import time

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ------------------------------------------------------------------
# 基本設定
# ------------------------------------------------------------------
st.set_page_config(page_title="PChome 商品價格查詢", page_icon="🛒", layout="wide")

API_URL = "https://ecshweb.pchome.com.tw/search/v3.3/all/results"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}
SORT_OPTIONS = {
    "銷量高 → 低": "sale/dc",
    "價格低 → 高": "prc/ac",
    "價格高 → 低": "prc/dc",
    "相關度": "rnk/dc",
}


# ------------------------------------------------------------------
# CODE01：爬蟲（單頁，快取 10 分鐘）
# ------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def fetch_page(keyword: str, page: int, sort: str) -> dict:
    params = {"q": keyword, "page": page, "sort": sort}
    resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.json()


def crawl(keyword: str, pages: int, sort: str, delay: float) -> pd.DataFrame:
    """依序抓取 1~pages 頁，合併成一個 DataFrame。"""
    frames = []
    progress = st.progress(0.0, text="開始抓取...")
    for i in range(1, pages + 1):
        progress.progress((i - 1) / pages, text=f"抓取第 {i} / {pages} 頁...")
        try:
            data = fetch_page(keyword, i, sort)
        except Exception as e:
            st.warning(f"第 {i} 頁抓取失敗：{e}")
            break

        prods = data.get("prods") or []
        if not prods:
            st.info(f"第 {i} 頁沒有資料，停止抓取。")
            break
        frames.append(pd.DataFrame(prods))

        total_page = data.get("totalPage")
        if total_page and i >= int(total_page):
            st.info(f"此關鍵字共 {total_page} 頁，已全部抓完。")
            break
        if i < pages and delay > 0:
            time.sleep(delay)  # 避免請求過快
    progress.progress(1.0, text="抓取完成")
    progress.empty()

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ------------------------------------------------------------------
# CODE02：資料整理
# ------------------------------------------------------------------
def extract_brand(name: str) -> str:
    """商品名稱常以【品牌】開頭，抓出來當作品牌。"""
    m = re.match(r"\s*[【\[](.+?)[】\]]", str(name))
    if m:
        return m.group(1).strip()
    return "其他"


def clean(raw: pd.DataFrame) -> pd.DataFrame:
    cols = [c for c in ["Id", "name", "price", "originPrice"] if c in raw.columns]
    df = raw[cols].copy()
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    if "originPrice" in df.columns:
        df["originPrice"] = pd.to_numeric(df["originPrice"], errors="coerce")
    df = df.dropna(subset=["name", "price"]).drop_duplicates(subset=["name", "price"])
    df = df.reset_index(drop=True)
    df.insert(0, "序號", df.index + 1)
    df["品牌"] = df["name"].apply(extract_brand)

    # 價格區間（圓餅圖、旭日圖用）
    bins = [0, 500, 1000, 1500, 2000, 3000, 5000, 10000, float("inf")]
    labels = [
        "500 以下", "500~1,000", "1,000~1,500", "1,500~2,000",
        "2,000~3,000", "3,000~5,000", "5,000~10,000", "10,000 以上",
    ]
    df["價格區間"] = pd.cut(df["price"], bins=bins, labels=labels, right=False)
    df["價格區間"] = df["價格區間"].astype(str)

    if "Id" in df.columns:
        df["連結"] = "https://24h.pchome.com.tw/prod/" + df["Id"].astype(str)
    return df, labels


# ------------------------------------------------------------------
# 畫面
# ------------------------------------------------------------------
st.title("🛒 PChome 商品價格查詢與視覺化")
st.caption("輸入商品關鍵字與頁數，即時抓取 PChome 24h 購物搜尋結果並分析價格。")

with st.sidebar:
    st.header("查詢條件")
    with st.form("query_form"):
        keyword = st.text_input("商品關鍵字", value="電風扇")
        pages = st.number_input("抓取頁數（每頁約 20 筆）", min_value=1, max_value=10, value=2, step=1)
        sort_label = st.selectbox("排序方式", list(SORT_OPTIONS.keys()))
        delay = st.slider("每頁間隔秒數", 0.0, 10.0, 1.0, 0.5, help="間隔越久越不容易被網站阻擋")
        submitted = st.form_submit_button("🔍 查詢", use_container_width=True)

# 按下查詢才重新抓；結果存在 session_state，切換圖表時不會重抓
if submitted:
    if not keyword.strip():
        st.warning("請輸入商品關鍵字")
    else:
        raw = crawl(keyword.strip(), int(pages), SORT_OPTIONS[sort_label], delay)
        if raw.empty:
            st.session_state.pop("result", None)
            st.error("查無資料，請換個關鍵字，或稍後再試。")
        else:
            df, labels = clean(raw)
            st.session_state["result"] = {
                "df": df,
                "labels": labels,
                "keyword": keyword.strip(),
            }

result = st.session_state.get("result")
if not result:
    st.info("👈 請在左側輸入條件後按「查詢」")
    st.stop()

df: pd.DataFrame = result["df"]
labels: list = result["labels"]
kw: str = result["keyword"]

if df.empty:
    st.warning("沒有有效的價格資料")
    st.stop()

# ---- 統計指標 ----
st.subheader(f"「{kw}」查詢結果")
mean_price = df["price"].mean()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("商品數", f"{len(df):,}")
c2.metric("平均價", f"{mean_price:,.0f}")
c3.metric("中位數", f"{df['price'].median():,.0f}")
c4.metric("最高價", f"{df['price'].max():,.0f}")
c5.metric("最低價", f"{df['price'].min():,.0f}")

# ---- 圖表 ----
tab_line, tab_pie, tab_sun = st.tabs(["📈 折線圖", "🥧 圓餅圖", "☀️ 旭日圖"])

with tab_line:
    fig = px.line(
        df,
        x="序號",
        y="price",
        markers=True,
        hover_data={"name": True, "序號": True, "price": ":,.0f"},
        labels={"price": "價格 (NT$)", "序號": "商品序號"},
        title=f"PChome「{kw}」售價走勢",
    )
    fig.add_hline(
        y=mean_price,
        line_dash="dash",
        line_color="red",
        annotation_text=f"平均 {mean_price:,.0f}",
        annotation_position="top left",
    )
    st.plotly_chart(fig, use_container_width=True)

with tab_pie:
    pie_df = (
        df.groupby("價格區間").size().reindex(labels).dropna().reset_index(name="商品數")
    )
    fig = px.pie(
        pie_df,
        names="價格區間",
        values="商品數",
        hole=0.35,
        title=f"PChome「{kw}」價格區間分布",
        category_orders={"價格區間": labels},
    )
    fig.update_traces(textinfo="percent+label")
    st.plotly_chart(fig, use_container_width=True)

with tab_sun:
    top_n = st.slider("顯示前 N 大品牌（其餘歸為「其他」）", 3, 20, 8)
    sun_df = df.copy()
    top_brands = sun_df["品牌"].value_counts().head(top_n).index
    sun_df["品牌"] = sun_df["品牌"].where(sun_df["品牌"].isin(top_brands), "其他")
    sun_df["商品數"] = 1
    fig = px.sunburst(
        sun_df,
        path=["價格區間", "品牌"],
        values="商品數",
        title=f"PChome「{kw}」價格區間 → 品牌",
    )
    fig.update_traces(textinfo="label+value")
    st.plotly_chart(fig, use_container_width=True)

# ---- 明細表 + 下載 ----
st.subheader("商品明細")
show_cols = [c for c in ["序號", "name", "品牌", "price", "originPrice", "價格區間", "連結"] if c in df.columns]
st.dataframe(
    df[show_cols],
    use_container_width=True,
    height=420,
    column_config={
        "name": "商品名稱",
        "price": st.column_config.NumberColumn("售價", format="%d"),
        "originPrice": st.column_config.NumberColumn("原價", format="%d"),
        "連結": st.column_config.LinkColumn("商品連結", display_text="開啟"),
    },
    hide_index=True,
)

st.download_button(
    "⬇️ 下載 CSV",
    data=df.to_csv(index=False).encode("utf-8-sig"),
    file_name=f"PCHOME_{kw}.csv",
    mime="text/csv",
)
