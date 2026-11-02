"""Language helpers shared by the router and the domain modules: language
detection, normalisation, dates, counts and references to earlier results."""
import os
import re
from datetime import date, timedelta

# Reference date of the mock dataset; "tonight", "Friday" etc. resolve against it.
TODAY = date.fromisoformat(os.environ.get("SUPERCHAT_TODAY", "2026-11-02"))

_FOLD = str.maketrans("əğıöüşçё", "egiousce")


def fold(text):
    """Lower-case and drop Azerbaijani diacritics so 'Bakı' and 'baki' match."""
    return text.lower().replace("i̇", "i").translate(_FOLD)


def tr(lang, en, az, ru):
    return {"en": en, "az": az, "ru": ru}[lang]


_patterns = {}


def find(t, keys):
    """True if any key starts a word in t; a trailing '$' requires the whole word."""
    for key in keys:
        if key not in _patterns:
            body = r"(?<!\w)" + re.escape(key.rstrip("$"))
            _patterns[key] = re.compile(body + (r"(?!\w)" if key.endswith("$") else ""))
        if _patterns[key].search(t):
            return True
    return False


# ---------- language ----------

_AZ_WORDS = {"salam", "var", "ne", "bu", "ve", "ucuz", "goster", "hansi", "bes", "mene", "ucun",
             "isteyirem", "axsam", "sabah", "bugun", "nece", "sebet", "varmi", "yox", "beli",
             "haqqinda", "qeder", "ile", "daha", "olar", "bron", "bilet", "mi", "mu", "en"}


def detect_lang(text, current):
    low = text.lower()
    if re.search(r"[а-яё]", low):
        return "ru"
    if re.search(r"[əğışçöü]", low):
        return "az"
    words = re.findall(r"[a-z]+", low)
    if any(w in _AZ_WORDS for w in words):
        return "az"
    if len(words) >= 2:
        return "en"
    return current


# ---------- dates and times ----------

_WEEKDAYS = [  # Monday first; longer Azerbaijani names are checked before their prefixes
    ["monday", "bazar ertesi", "понедельник"],
    ["tuesday", "cersenbe axsami", "вторник"],
    ["wednesday", "cersenbe", "сред"],
    ["thursday", "cume axsami", "четверг"],
    ["friday", "cume", "пятниц"],
    ["saturday", "senbe", "суббот"],
    ["sunday", "bazar$", "воскресен"],
]
_MONTHS = ["jan|yanvar|январ", "feb|fevral|феврал", "mar|март", "apr|aprel|апрел", "may|мая|май",
           "jun|iyun|июн", "jul|iyul|июл", "aug|avqust|август", "sep|sentyabr|сентябр",
           "oct|oktyabr|октябр", "nov|noyabr|ноябр", "dec|dekabr|декабр"]


def _date(year, month, day):
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


def parse_date(t):
    """ISO date for '6 November', '06.11', 'Friday', 'today', 'tomorrow', or None.
    Explicit dates win over relative ones."""
    m = re.search(r"\d{4}-\d{2}-\d{2}", t)
    if m:
        return m.group(0)
    for month, stems in enumerate(_MONTHS, 1):
        m = (re.search(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s*(?:of\s+)?(?:%s)" % stems, t)
             or re.search(r"(?<!\w)(?:%s)\w*\s+(\d{1,2})(?!\d)" % stems, t))
        if m and _date(TODAY.year, month, int(m.group(1))):
            return _date(TODAY.year, month, int(m.group(1)))
    m = re.search(r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?![\d.])", t)
    if m and _date(TODAY.year, int(m.group(2)), int(m.group(1))):
        return _date(TODAY.year, int(m.group(2)), int(m.group(1)))
    for i, keys in enumerate(_WEEKDAYS):
        if find(t, keys):
            return (TODAY + timedelta(days=(i - TODAY.weekday()) % 7)).isoformat()
    if find(t, ["today", "tonight", "this evening", "bu gun", "bugun", "bu axsam", "сегодня"]):
        return TODAY.isoformat()
    if find(t, ["tomorrow", "sabah$", "sabaha", "завтра"]):
        return (TODAY + timedelta(days=1)).isoformat()
    return None


def clock_time(t):
    """'14:20' or '7:30' -> '14:20' / '07:30', or None."""
    m = re.search(r"(?<!\d)(\d{1,2}):(\d{2})(?!\d)", t)
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None


def party_size(t):
    """Group size stated anywhere in the chat: 'for 2 people', 'iki nəfərik', 'нас трое'."""
    m = (re.search(r"(?<![\d.:/-])([1-9])\s*(?:people|persons|adults|passengers|nefer|человек|пассажир)", t)
         or re.search(r"(?:we are|there are|biz|нас)\s+([1-9])(?!\d)", t))
    if m:
        return int(m.group(1))
    for word, n in _COUNTS.items():
        if find(t, [f"{word} people", f"{word} adults", f"{word} nefer", f"{word} человек"]):
            return n
    if find(t, ["нас двое"]):
        return 2
    if find(t, ["нас трое"]):
        return 3
    return None


def time_window(t):
    """(from_hour, to_hour) for 'morning', 'afternoon', 'evening'/'tonight', or None."""
    if find(t, ["morning", "seher", "утр"]):
        return (0, 12)
    if find(t, ["afternoon", "gunorta", "днем", "днём"]):
        return (12, 17)
    if find(t, ["evening", "tonight", "night", "axsam$", "вечер", "ночь"]):
        return (17, 24)
    return None


_WD = {"en": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"],
       "az": ["B.e.", "Ç.a.", "Çər.", "C.a.", "Cümə", "Şənbə", "Bazar"],
       "ru": ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]}
_MON = {"en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "az": ["yan", "fev", "mar", "apr", "may", "iyn", "iyl", "avq", "sen", "okt", "noy", "dek"],
        "ru": ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]}


def fmt_day(iso, lang):
    d = date.fromisoformat(iso[:10])
    return f"{_WD[lang][d.weekday()]} {d.day} {_MON[lang][d.month - 1]}"


def fmt_minutes(minutes, lang):
    h, m = divmod(minutes, 60)
    return tr(lang, f"{h}h {m:02d}m", f"{h} saat {m:02d} dəq", f"{h} ч {m:02d} мин")


# ---------- counts and references ----------

_COUNTS = {"two": 2, "three": 3, "four": 4, "five": 5, "iki": 2, "uc": 3, "dord": 4,
           "один": 1, "одно": 1, "одну": 1, "два": 2, "две": 2, "три": 3, "четыре": 4, "пять": 5}


def parse_count(t):
    """How many seats / tickets / items the user asks for, or None."""
    m = re.search(r"(?<![\d.:/-])([1-9])\s*(?:x\b|seat|ticket|people|person|passenger|adult|pc|piece"
                  r"|bilet|yer|nefer|eded|ed\b|мест|билет|человек|пассажир|шт)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\bfor\s+([1-9])\b", t)
    if m:
        return int(m.group(1))
    for w in re.findall(r"\w+", t):
        if w in _COUNTS:
            return _COUNTS[w]
    return None


ORDINALS = [
    ["first", "1st", "birinci", "ilk$", "перв"],
    ["second", "2nd", "ikinci", "второй", "вторую", "второе", "второго"],
    ["third", "3rd", "ucuncu", "трет"],
    ["fourth", "4th", "dorduncu", "четверт"],
    ["fifth", "5th", "besinci", "пятый", "пятую", "пятое", "пятого"],
]
LAST = ["last$", "latter", "sonuncu", "последн"]
CHEAP = ["cheap", "less expensive", "lower price", "ucuz", "дешев"]
PRICEY = ["expensive", "pricier", "bahali", "дорож"]
POINTERS = ["it$", "that$", "this$", "one$", "them$", "those$", "these$", "o$", "onu", "onun", "bunu",
            "hemin", "его", "ее$", "этот", "эту", "этого", "тот$", "ту$", "их$"]
REFERENCE = sum(ORDINALS, []) + LAST + CHEAP + PRICEY + POINTERS


def pick(t, items, name=None, clock=None):
    """Resolve 'the second one', 'the cheaper one', 'the last one', 'the 14:20 one' or a
    distinctive name ('the Pro', 'CA101') against a list shown earlier."""
    if not items:
        return None
    if clock and clock_time(t):
        hits = [x for x in items if clock(x) == clock_time(t)]
        if len(hits) == 1:
            return hits[0]
    if name:
        words = [set(re.findall(r"\w+", fold(name(x)))) for x in items]
        for i, own in enumerate(words):
            others = set().union(*(w for j, w in enumerate(words) if j != i))
            if any(find(t, [w + "$"]) for w in own - others if len(w) > 1 and not w.isdigit()):
                return items[i]
    for i, keys in enumerate(ORDINALS):
        if find(t, keys):
            return items[i] if i < len(items) else None
    if find(t, LAST):
        return items[-1]
    if find(t, CHEAP):
        return min(items, key=lambda x: x["price_azn"])
    if find(t, PRICEY):
        return max(items, key=lambda x: x["price_azn"])
    return None


def pick_many(t, items):
    """All items named by ordinal: 'compare the first and the third' -> [items[0], items[2]]."""
    return [items[i] for i, keys in enumerate(ORDINALS) if i < len(items) and find(t, keys)]


def money(x):
    return f"{x:.2f} AZN"
