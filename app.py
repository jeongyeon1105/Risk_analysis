import io
import json
import os
import zipfile
import xml.etree.ElementTree as ET
from datetime import date

import pandas as pd
import requests
import streamlit as st
from dotenv import load_dotenv
from streamlit_local_storage import LocalStorage

from flags import audit_flags

load_dotenv()  # 로컬 개발용 기본 키. 배포 시에는 사용자가 직접 입력
BASE = "https://opendart.fss.or.kr/api"
YEARS = 5
# 계정 매칭은 account_id 기준 (계정명은 회사마다 다름). 금융업 등 없는 경우 None.
ACCOUNTS = {
    "revenue": ("ifrs-full_Revenue", "ifrs_Revenue"),
    "op_income": ("dart_OperatingIncomeLoss",),
    "net_income": ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"),
    "op_cf": ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"),
    "liabilities": ("ifrs-full_Liabilities", "ifrs_Liabilities"),
    "equity": ("ifrs-full_Equity", "ifrs_Equity"),
}
LABELS = {"revenue": "매출액", "op_income": "영업이익", "net_income": "당기순이익",
          "op_cf": "영업현금흐름", "debt_ratio": "부채비율(%)"}


@st.cache_data(show_spinner="기업 목록 내려받는 중...", ttl=7 * 86400)
def load_corps(_key):  # _key: 캐시 키에서 제외 (공개 데이터라 사용자 간 공유)
    r = requests.get(f"{BASE}/corpCode.xml", params={"crtfc_key": _key}, timeout=60)
    try:
        xml = zipfile.ZipFile(io.BytesIO(r.content)).read("CORPCODE.xml")
    except zipfile.BadZipFile:
        raise ValueError("API 키 오류: " + (ET.fromstring(r.content).findtext("message") or r.text[:100]))
    rows = [{"corp_code": e.findtext("corp_code"), "name": e.findtext("corp_name"),
             "stock_code": (e.findtext("stock_code") or "").strip()} for e in ET.fromstring(xml)]
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False, ttl=86400)
def load_fs(_key, corp_code, year, fs_div):
    r = requests.get(f"{BASE}/fnlttSinglAcntAll.json", timeout=30, params={
        "crtfc_key": _key, "corp_code": corp_code, "bsns_year": year,
        "reprt_code": "11011", "fs_div": fs_div}).json()
    if r["status"] == "013":  # 데이터 없음은 정상 케이스 (예: 연결재무제표 없는 기업)
        return None
    if r["status"] != "000":
        raise ValueError(f"DART 오류 {r['status']}: {r['message']}")
    out = {}
    for k, ids in ACCOUNTS.items():
        for a in r["list"]:
            if a["account_id"] in ids and a.get("thstrm_amount", "").strip("-").replace(",", "").isdigit():
                out[k] = int(a["thstrm_amount"].replace(",", ""))
                break
    return out


def trend(key, corp_code, fs_div):
    rows = []
    for y in range(date.today().year - YEARS, date.today().year):
        d = load_fs(key, corp_code, y, fs_div)
        if d is None:
            continue
        r = {"year": y, **{k: d.get(k) for k in ACCOUNTS}}
        r["debt_ratio"] = round(r["liabilities"] / r["equity"] * 100, 1) if r["liabilities"] and r["equity"] else None
        rows.append(r)
    return rows


st.set_page_config(page_title="감사 대상 기업 분석", layout="wide")
store = LocalStorage()

with st.sidebar:
    st.header("DART API 키")
    key = st.text_input("본인 키 입력", type="password", value=os.getenv("DART_API_KEY", ""),
                        help="키는 이 세션에서만 사용되며 서버에 저장되지 않습니다.")
    raw = store.getItem("history")
    history = json.loads(raw) if raw else []
    st.header("최근 검색")
    for h in history:
        if st.button(f"{h['name']} ({h['stock_code'] or '비상장'})", key=f"h{h['corp_code']}"):
            st.session_state["pick"] = h
    if history and st.button("기록 지우기"):
        store.setItem("history", "[]", key="clear")
        st.rerun()

st.title("감사 대상 기업 분석")
if not key:
    st.info("왼쪽에 본인의 DART API 키를 입력하세요. (opendart.fss.or.kr 에서 무료 발급)")
    st.stop()
try:
    corps = load_corps(key)
except ValueError as e:
    st.error(str(e))
    st.stop()

q = st.text_input("기업명 또는 종목코드").strip()
pick = st.session_state.get("pick")
if q:
    m = corps[corps["name"].str.contains(q, case=False, regex=False) | (corps["stock_code"] == q)]
    m = m.assign(listed=m["stock_code"] != "").sort_values("listed", ascending=False).head(20)
    if m.empty:
        st.warning("검색 결과가 없습니다.")
    else:
        label = m.apply(lambda r: f"{r['name']} ({r['stock_code'] or '비상장'})", axis=1)
        i = st.selectbox("검색 결과", range(len(m)), format_func=lambda n: label.iloc[n])
        c = m.iloc[i]
        pick = {"corp_code": c["corp_code"], "name": c["name"], "stock_code": c["stock_code"]}
        st.session_state["pick"] = pick
if not pick:
    st.stop()

if not history or history[0]["corp_code"] != pick["corp_code"]:
    new = [pick] + [h for h in history if h["corp_code"] != pick["corp_code"]]
    store.setItem("history", json.dumps(new[:10], ensure_ascii=False), key="save")

st.subheader(pick["name"])
fs_div = st.radio("재무제표", ["CFS", "OFS"], format_func=lambda v: "연결" if v == "CFS" else "별도", horizontal=True)
try:
    rows = trend(key, pick["corp_code"], fs_div)
except (ValueError, requests.RequestException) as e:
    st.error(str(e))
    st.stop()
if not rows:
    st.warning("해당 재무제표 데이터가 없습니다. (연결재무제표가 없는 기업일 수 있음)")
    st.stop()

for level, msg in audit_flags(rows):
    (st.error if level == "high" else st.warning)(msg)
df = pd.DataFrame(rows).set_index("year")[list(LABELS)].rename(columns=LABELS)
st.dataframe(df.T.style.format("{:,.0f}", na_rep="N/A"), use_container_width=True)
st.line_chart(df.drop(columns="부채비율(%)"))
st.line_chart(df[["부채비율(%)"]])
st.caption("단위: 원. 사업보고서 기준. N/A = 해당 계정을 찾지 못함 (금융업 등).")
