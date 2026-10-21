from kam import split_kam


def test_consolidated_and_separate():
    text = "(연결재무제표)\n 1. 재고자산 평가\n(별도재무제표)\n 1. 매출차감"
    assert split_kam(text) == [("연결재무제표 KAM", "1. 재고자산 평가"), ("별도재무제표 KAM", "1. 매출차감")]


def test_only_separate():
    assert split_kam("(별도재무제표)\n1. 수익인식") == [("별도재무제표 KAM", "1. 수익인식")]


def test_no_marker_or_none():
    assert split_kam("-") == [("", "-")]
    assert split_kam("1. 수익인식") == [("", "1. 수익인식")]
