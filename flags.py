def audit_flags(rows):
    """rows: 연도 오름차순 dict 리스트 (op_income, net_income, op_cf; 없으면 None). 반환: (수준, 메시지) 리스트."""
    out = []
    ops = [r["op_income"] for r in rows]
    if len(ops) >= 3 and all(v is not None and v < 0 for v in ops[-3:]):
        out.append(("high", f"{rows[-3]['year']}~{rows[-1]['year']} 3년 연속 영업손실"))
    for r in rows:
        if r["net_income"] is not None and r["op_cf"] is not None and r["net_income"] > 0 > r["op_cf"]:
            out.append(("mid", f"{r['year']} 순이익은 흑자인데 영업현금흐름 마이너스"))
    return out
