"""Name normalisation and pitch-slot helpers shared by ingest and model code."""
import re
import unicodedata

NON_DECOMPOSABLE = str.maketrans(
    {"ø": "o", "æ": "ae", "å": "a", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ß": "ss", "ı": "i"}
)


def norm(name):
    """Accent/case/punctuation-insensitive key for matching player names across sources."""
    s = unicodedata.normalize("NFD", name.casefold()).translate(NON_DECOMPOSABLE)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z ]", "", s.replace("-", " ")).strip()


def band(slot):
    """Pitch band for a rotowire-style slot code (GK, DL/DC/DR, DMC, MC, AML/AMC/AMR, FW/FWL/FWR)."""
    if slot == "GK":
        return "GK"
    if slot.startswith("DM"):
        return "DM"
    if slot.startswith("D"):
        return "D"
    if slot.startswith("AM"):
        return "AM"
    if slot.startswith("M"):
        return "M"
    return "F"


def slot_side(slot):
    """0 = left, 1 = centre, 2 = right — for laying slots out on the pitch."""
    if slot.endswith("L"):
        return 0
    if slot.endswith("R"):
        return 2
    return 1


BANDS = ("GK", "D", "DM", "M", "AM", "F")
