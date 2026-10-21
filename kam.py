import re


def split_kam(text):
    """'(연결재무제표) ... (별도재무제표) ...' 형태의 KAM 문자열을 [(구분, 내용)]으로 나눈다. 표식이 없으면 통째로 한 덩어리."""
    parts = re.split(r"\(\s*(연결|별도)\s*재무제표\s*\)", text)
    out = [("", parts[0].strip())] if parts[0].strip() else []
    out += [(f"{parts[i]}재무제표 KAM", parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]
    return out or [("", text)]
