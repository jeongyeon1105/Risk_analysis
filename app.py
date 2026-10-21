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

from flags import CRITERIA, audit_flags
from industry import industry_label
from kam import split_kam

load_dotenv()  # 로컬 개발용 기본 키. 배포 시에는 사용자가 직접 입력
BASE = "https://opendart.fss.or.kr/api"
YEARS = 5
# 계정 매칭은 account_id 기준 (계정명은 회사마다 다름). 금융업 등 없는 경우 None.
IS = ("IS", "CIS")  # 자본변동표 등 같은 account_id가 다른 표에도 나오므로 표 구분 필수
ACCOUNTS = {
    "revenue": (("ifrs-full_Revenue", "ifrs_Revenue"), IS),
    "op_income": (("dart_OperatingIncomeLoss",), IS),
    "net_income": (("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"), IS),
    "op_cf": (("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"), ("CF",)),
    "liabilities": (("ifrs-full_Liabilities", "ifrs_Liabilities"), ("BS",)),
    "equity": (("ifrs-full_Equity", "ifrs_Equity"), ("BS",)),
    "capital": (("ifrs-full_IssuedCapital", "ifrs_IssuedCapital"), ("BS",)),
}
LABELS = {"revenue": "매출액", "op_income": "영업이익", "net_income": "당기순이익",
          "op_cf": "영업현금흐름", "debt_ratio": "부채비율(%)"}
UNIT = 1e8  # 화면 표시는 억원


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
    for k, (ids, tables) in ACCOUNTS.items():
        for a in r["list"]:
            if a["account_id"] in ids and a["sj_div"] in tables and a.get("thstrm_amount", "").strip("-").replace(",", "").isdigit():
                out[k] = int(a["thstrm_amount"].replace(",", ""))
                break
    return out


@st.cache_data(show_spinner=False, ttl=86400)
def load_audit(_key, corp_code, year):
    """해당 연도 사업보고서의 감사정보 3개년(당기/전기/전전기). 보고서가 없으면 None."""
    r = requests.get(f"{BASE}/accnutAdtorNmNdAdtOpinion.json", timeout=30, params={
        "crtfc_key": _key, "corp_code": corp_code, "bsns_year": year, "reprt_code": "11011"}).json()
    if r["status"] == "013":
        return None
    if r["status"] != "000":
        raise ValueError(f"DART 오류 {r['status']}: {r['message']}")
    out = []
    for a in r["list"]:
        label = a["bsns_year"]
        back = 2 if "전전기" in label else 1 if "전기" in label else 0
        out.append({"year": year - back, "auditor": a["adtor"].strip(), "opinion": a["adt_opinion"].strip(),
                    "emphasis": a["emphs_matter"].strip(), "kam": a["core_adt_matter"].strip()})
    return sorted(out, key=lambda x: x["year"])


@st.cache_data(show_spinner=False, ttl=7 * 86400)
def load_industry(_key, corp_code):
    r = requests.get(f"{BASE}/company.json", params={"crtfc_key": _key, "corp_code": corp_code}, timeout=30).json()
    if r["status"] != "000":  # 예외는 캐시되지 않으므로 일시 오류가 오래 남지 않음
        raise ValueError(r["message"])
    return r.get("induty_code", "")


@st.cache_data(show_spinner=False, ttl=86400)
def load_audit_reports(_key, corp_code):
    """감사보고서(공시유형 F) 최근 목록. 사업보고서가 없는 비상장 외부감사 대상 기업용."""
    r = requests.get(f"{BASE}/list.json", timeout=30, params={
        "crtfc_key": _key, "corp_code": corp_code, "pblntf_ty": "F", "page_count": 10,
        "bgn_de": f"{date.today().year - 5}0101", "end_de": date.today().strftime("%Y%m%d")}).json()
    if r["status"] == "013":
        return []
    if r["status"] != "000":
        raise ValueError(f"DART 오류 {r['status']}: {r['message']}")
    return r["list"]


def industry_text(key, corp_code):
    try:
        return industry_label(load_industry(key, corp_code))
    except (ValueError, requests.RequestException):
        return "업종 미확인"


def corp_label(key, r):
    return f"{r['name']} ({r['stock_code'] or '비상장'}) · {industry_text(key, r['corp_code'])}"


def latest_audit(key, corp_code):
    """가장 최근 사업보고서 연도와 그 감사정보. 올해 보고서가 아직 없으면 전년도로."""
    for y in (date.today().year - 1, date.today().year - 2):
        a = load_audit(key, corp_code, y)
        if a:
            return y, a
    return date.today().year - 1, []


def trend(key, corp_code, fs_div, last):
    rows = []
    for y in range(last - YEARS + 1, last + 1):
        d = load_fs(key, corp_code, y, fs_div)
        if d is None:
            continue
        r = {"year": y, **{k: d.get(k) for k in ACCOUNTS}}
        # 자본총계가 0 이하이면 비율이 무의미 (자본잠식 플래그가 따로 잡음)
        r["debt_ratio"] = round(r["liabilities"] / r["equity"] * 100, 1) if r["liabilities"] and r["equity"] and r["equity"] > 0 else None
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
            st.session_state["q"] = ""  # 이전 검색어가 기록에서 고른 기업을 덮어쓰지 않도록
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

with st.form("search"):
    typed = st.text_input("기업명 또는 종목코드")
    if st.form_submit_button("검색"):
        st.session_state["q"] = typed.strip()
q = st.session_state.get("q", "")
pick = st.session_state.get("pick")
if q:
    m = corps[corps["name"].str.contains(q, case=False, regex=False) | (corps["stock_code"] == q)]
    m = m.assign(listed=m["stock_code"] != "").sort_values("listed", ascending=False).head(20)
    if m.empty:
        st.warning("검색 결과가 없습니다.")
    else:
        with st.spinner("업종 조회 중..."):
            label = m.apply(lambda r: corp_label(key, r), axis=1)
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
st.caption("업종: " + industry_text(key, pick["corp_code"]))
fs_div = st.radio("재무제표", ["CFS", "OFS"], format_func=lambda v: "연결" if v == "CFS" else "별도", horizontal=True)
try:
    last, audits = latest_audit(key, pick["corp_code"])
    rows = trend(key, pick["corp_code"], fs_div, last)
except (ValueError, requests.RequestException) as e:
    st.error(str(e))
    st.stop()
if not rows and not audits:
    st.info("이 기업은 사업보고서가 없어 재무 추이와 감사정보를 자동으로 보여줄 수 없습니다. "
            "비상장 외부감사 대상 기업은 사업보고서 없이 감사보고서만 제출하는 경우가 많습니다. "
            "아래 감사보고서 원문을 DART에서 직접 확인하세요.")
    try:
        reports = load_audit_reports(key, pick["corp_code"])
    except (ValueError, requests.RequestException) as e:
        st.error(str(e))
        st.stop()
    if not reports:
        st.warning("최근 5년 내 감사보고서도 찾지 못했습니다.")
    for rep in reports:
        st.markdown(f"- [{rep['report_nm']}](https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rep['rcept_no']})"
                    f" · 제출 {rep['flr_nm']} · 접수 {rep['rcept_dt']}")
    st.stop()
if not rows:
    st.warning("해당 재무제표 데이터가 없습니다. (연결재무제표가 없는 기업일 수 있음)")
    st.stop()

st.markdown("#### 경고 플래그", help=CRITERIA)  # help = 제목 옆 ? 아이콘, 올리거나 누르면 기준 표시
flags = audit_flags(rows, audits)
if not flags:
    st.success("해당되는 경고 플래그가 없습니다.")
for level, msg in sorted(flags, key=lambda f: f[0] != "high"):  # 레드 먼저
    (st.error if level == "high" else st.warning)(f"**{'레드' if level == 'high' else '옐로'}** · {msg}")

tab_fin, tab_audit = st.tabs(["재무 추이", "감사정보 (최근 3개년)"])

with tab_fin:
    df = pd.DataFrame(rows).set_index("year")[list(LABELS)].rename(columns=LABELS)
    df.index = df.index.astype(str)
    money = [v for k, v in LABELS.items() if k != "debt_ratio"]
    df[money] = df[money] / UNIT
    st.dataframe(df.T.style.format("{:,.0f}", na_rep="N/A")
                 .format("{:,.1f}", subset=pd.IndexSlice[["부채비율(%)"], :], na_rep="N/A"), use_container_width=True)
    for cols, names in ((st.columns(3), money[:3]), (st.columns(2), [money[3], "부채비율(%)"])):
        for col, name in zip(cols, names):
            col.markdown(f"**{name}**" + ("" if "%" in name else " (억원)"))
            col.bar_chart(df[[name]])
    st.caption("단위: 억원. 사업보고서 기준. N/A = 해당 계정을 찾지 못함 (금융업 등).")

with tab_audit:
    if not audits:
        st.info("감사정보를 찾지 못했습니다. (사업보고서가 없는 기업일 수 있음)")
    else:
        table = []
        for i, a in enumerate(audits):
            changed = i > 0 and a["auditor"] != audits[i - 1]["auditor"]
            table.append({"사업연도": a["year"], "감사인": a["auditor"], "감사인 변경": "변경" if changed else "-",
                          "감사의견": a["opinion"], "강조사항": a["emphasis"]})
        st.dataframe(pd.DataFrame(table).set_index("사업연도"), use_container_width=True)
        for a in reversed(audits):
            with st.expander(f"{a['year']} 핵심감사사항 (KAM)", expanded=a is audits[-1]):
                for part, body in split_kam(a["kam"]):
                    if part:
                        st.markdown(f"**{part}**")
                    st.text(body)
        st.caption(f"{audits[0]['year']}년 감사인은 변경 여부를 비교할 이전 연도가 없어 '-'로 표시됩니다. 출처: DART 사업보고서.")
