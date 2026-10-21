# 레드("high")/옐로("mid") 기준은 DART·감사기준서에 공식 정의가 없는 제안값이다.
# 계속기업 징후(감사기준서 570)와 일반 실무를 참고했으며, 아래 상수를 법인 기준에 맞게 조정한다.
DEBT_RATIO_LIMIT = 200  # % 초과 시 옐로. shortcut: 업종 구분 없이 일괄 적용, 업종별 기준이 필요하면 확장
DEBT_RATIO_SURGE = 50  # %p 이상 전년 대비 증가 시 옐로
NO_EMPHASIS = ("", "-", "해당사항 없음", "해당 사항 없음", "해당없음")

# 화면의 ? 툴팁에 표시. 규칙을 바꾸면 이 문구도 함께 고친다.
CRITERIA = f"""공식 기준이 아닌 제안값입니다 (계속기업 징후·감사기준서 570 및 실무 참고).

**레드**
- 3년 연속 영업손실
- 3년 연속 영업현금흐름 마이너스
- 2년 연속 순이익 흑자인데 영업현금흐름 마이너스
- 완전자본잠식 (자본총계 < 0)
- 비적정 감사의견 (한정·부적정·의견거절)
- 감사보고서 강조사항에 계속기업 언급

**옐로**
- 당기 영업손실
- 순이익 흑자인데 영업현금흐름 마이너스 (1년)
- 부분자본잠식 의심 (자본총계 < 자본금)
- 부채비율 {DEBT_RATIO_LIMIT}% 초과, 또는 전년 대비 {DEBT_RATIO_SURGE}%p 이상 증가
- 기타 강조사항
- 핵심감사사항(KAM)에 계속기업 언급
- 감사인 변경"""


def audit_flags(rows, audits=()):
    """rows: 연도 오름차순 dict (op_income, net_income, op_cf, equity, capital, debt_ratio; 없으면 None).
    audits: 연도 오름차순 dict (year, auditor, opinion, emphasis, kam). 반환: (수준, 메시지) 리스트."""
    out = []
    last3 = rows[-3:]
    last = rows[-1]

    # 영업손실
    if len(last3) == 3 and all(r["op_income"] is not None and r["op_income"] < 0 for r in last3):
        out.append(("high", f"{last3[0]['year']}~{last3[-1]['year']} 3년 연속 영업손실"))
    elif last["op_income"] is not None and last["op_income"] < 0:
        out.append(("mid", f"{last['year']} 영업손실"))

    # 영업현금흐름
    if len(last3) == 3 and all(r["op_cf"] is not None and r["op_cf"] < 0 for r in last3):
        out.append(("high", f"{last3[0]['year']}~{last3[-1]['year']} 3년 연속 영업현금흐름 마이너스"))
    diverged = [r["year"] for r in rows
                if r["net_income"] is not None and r["op_cf"] is not None and r["net_income"] > 0 > r["op_cf"]]
    if len(rows) >= 2 and {rows[-2]["year"], last["year"]} <= set(diverged):
        out.append(("high", f"{rows[-2]['year']}~{last['year']} 2년 연속 순이익 흑자인데 영업현금흐름 마이너스"))
        diverged = [y for y in diverged if y < rows[-2]["year"]]
    out += [("mid", f"{y} 순이익은 흑자인데 영업현금흐름 마이너스") for y in diverged]

    # 자본잠식·부채
    if last.get("equity") is not None:
        if last["equity"] < 0:
            out.append(("high", f"{last['year']} 완전자본잠식 (자본총계 < 0)"))
        elif last.get("capital") and last["equity"] < last["capital"]:
            out.append(("mid", f"{last['year']} 부분자본잠식 의심 (자본총계 < 자본금)"))
    dr = last.get("debt_ratio")
    if dr is not None and dr > DEBT_RATIO_LIMIT:
        out.append(("mid", f"{last['year']} 부채비율 {dr:,.0f}% ({DEBT_RATIO_LIMIT}% 초과)"))
    prev_dr = rows[-2].get("debt_ratio") if len(rows) >= 2 else None
    if dr is not None and prev_dr is not None and dr - prev_dr >= DEBT_RATIO_SURGE:
        out.append(("mid", f"{last['year']} 부채비율 전년 대비 {dr - prev_dr:,.0f}%p 증가"))

    # 감사정보
    prev = None
    for a in audits:
        op = a["opinion"].replace("의견", "").strip()
        if op not in ("", "-", "적정"):
            out.append(("high", f"{a['year']} 감사의견 {a['opinion']}"))
        if "계속기업" in a["emphasis"]:
            out.append(("high", f"{a['year']} 감사보고서 강조사항에 계속기업 관련 언급"))
        elif a["emphasis"] not in NO_EMPHASIS:
            out.append(("mid", f"{a['year']} 감사보고서 강조사항 있음"))
        if "계속기업" in a["kam"]:
            out.append(("mid", f"{a['year']} 핵심감사사항에 계속기업 관련 언급"))
        if prev and a["auditor"] != prev["auditor"]:
            out.append(("mid", f"{a['year']} 감사인 변경 ({prev['auditor']} → {a['auditor']})"))
        prev = a
    return out
