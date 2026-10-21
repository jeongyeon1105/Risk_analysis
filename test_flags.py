from flags import audit_flags


def row(year, op, ni, cf, **extra):
    return {"year": year, "op_income": op, "net_income": ni, "op_cf": cf, **extra}


def audit(year, auditor="A회계법인", opinion="적정", emphasis="-", kam="-"):
    return {"year": year, "auditor": auditor, "opinion": opinion, "emphasis": emphasis, "kam": kam}


def levels(flags):
    return [f[0] for f in flags]


def test_three_year_operating_loss():
    rows = [row(2022, -1, -1, 1), row(2023, -1, -1, 1), row(2024, -1, -1, 1)]
    assert levels(audit_flags(rows)) == ["high"]


def test_latest_year_loss_is_yellow():
    rows = [row(2022, 1, 1, 1), row(2023, -1, 1, 1), row(2024, -1, 1, 1)]
    assert levels(audit_flags(rows)) == ["mid"]


def test_profit_with_negative_cf():
    flags = audit_flags([row(2024, 5, 3, -2)])
    assert len(flags) == 1 and flags[0][0] == "mid" and "2024" in flags[0][1]


def test_two_years_profit_with_negative_cf_is_red():
    flags = audit_flags([row(2023, 5, 3, -2), row(2024, 5, 3, -2)])
    assert levels(flags) == ["high"]


def test_three_year_negative_cf_is_red():
    rows = [row(y, 5, -1, -2) for y in (2022, 2023, 2024)]
    assert levels(audit_flags(rows)) == ["high"]


def test_missing_values_ignored():
    assert audit_flags([row(2024, None, None, None)] * 3) == []


def test_capital_impairment():
    assert levels(audit_flags([row(2024, 1, 1, 1, equity=-5, capital=10)])) == ["high"]
    assert levels(audit_flags([row(2024, 1, 1, 1, equity=5, capital=10)])) == ["mid"]


def test_debt_ratio():
    rows = [row(2023, 1, 1, 1, debt_ratio=100), row(2024, 1, 1, 1, debt_ratio=250)]
    assert levels(audit_flags(rows)) == ["mid", "mid"]  # 200% 초과 + 50%p 이상 급증


def test_audit_signals():
    rows = [row(2024, 1, 1, 1)]
    assert audit_flags(rows, [audit(2024)]) == []
    assert levels(audit_flags(rows, [audit(2024, opinion="한정")])) == ["high"]
    assert levels(audit_flags(rows, [audit(2024, emphasis="계속기업 관련 중요한 불확실성")])) == ["high"]
    assert levels(audit_flags(rows, [audit(2024, emphasis="소송 관련")])) == ["mid"]
    assert levels(audit_flags(rows, [audit(2023), audit(2024, auditor="B회계법인")])) == ["mid"]
