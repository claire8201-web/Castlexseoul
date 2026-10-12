"""Reservation link parsing and server-result classification without browser I/O."""
import ast
import datetime
import re


def parse_booking_link(href, date):
    match = re.fullmatch(r"\s*(?:javascript:\s*)?Book_Confirm\s*\((.*)\)\s*;?\s*", href, re.I | re.S)
    if not match:
        raise ValueError("Unsupported reservation link")
    try:
        args = ast.literal_eval("(" + match.group(1) + ",)")
    except (SyntaxError, ValueError) as exc:
        raise ValueError("Non-literal reservation arguments") from exc
    if len(args) not in (6, 7) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("Unexpected reservation arguments")
    if args[0] != date:
        raise ValueError("Reservation date does not match selected date")
    datetime.datetime.strptime(args[0], "%Y%m%d")
    if not re.fullmatch(r"(?:[01]\d|2[0-3])[0-5]\d", args[4]) or not args[3]:
        raise ValueError("Invalid tee time or course")
    return args


def classify_booking_message(text):
    compact = re.sub(r"\s+", "", text or "")
    if any(word in compact for word in ("로그인", "세션만료")):
        return "SESSION_EXPIRED"
    if "당일중복예약제한" in compact or ("이미예약을하셨" in compact and "추가예약" in compact):
        return "ALREADY_RESERVED"
    if "점검" in compact or "정비" in compact:
        return "MAINTENANCE"
    if any(word in compact for word in ("이미다른분", "다른회원", "예약불가", "예약할수없", "불가능")):
        return "SLOT_TAKEN"
    if "예약" in compact and any(word in compact for word in ("완료", "성공", "정상적으로처리")):
        return "SUCCESS_TEXT"
    if "예약을하시겠습니까" in compact or "예약하시겠습니까" in compact:
        return "CONFIRM"
    return "UNKNOWN_RESULT"
