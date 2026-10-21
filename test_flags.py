from flags import audit_flags


def row(year, op, ni, cf):
    return {"year": year, "op_income": op, "net_income": ni, "op_cf": cf}


def test_three_year_operating_loss():
    rows = [row(2022, -1, -1, 1), row(2023, -1, -1, 1), row(2024, -1, -1, 1)]
    assert [f[0] for f in audit_flags(rows)] == ["high"]


def test_two_year_loss_not_flagged():
    rows = [row(2022, 1, 1, 1), row(2023, -1, 1, 1), row(2024, -1, 1, 1)]
    assert audit_flags(rows) == []


def test_profit_with_negative_cf():
    flags = audit_flags([row(2024, 5, 3, -2)])
    assert len(flags) == 1 and flags[0][0] == "mid" and "2024" in flags[0][1]


def test_missing_values_ignored():
    assert audit_flags([row(2024, None, None, None)] * 3) == []
