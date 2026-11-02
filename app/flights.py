"""Flights module: search, filter, details, compare and mock reservations."""
import re

from . import nlp
from .nlp import find, fmt_day, money, tr

CITY_ALIASES = {
    "GYD": ["baku", "baki", "баку"],
    "IST": ["istanbul", "стамбул"],
    "DXB": ["dubai", "dubay", "дубай"],
    "SVO": ["moscow", "moskva", "москв"],
    "TBS": ["tbilisi", "tiflis", "тбилиси"],
    "TAS": ["tashkent", "daskend", "ташкент"],
}
DIRECT = ["direct", "non-stop", "nonstop", "birbasa", "aktarmasiz", "прямой", "прямые", "прямых",
          "без пересад"]
BOOK = ["book", "reserve", "bron", "брон", "заброн"]
COMPARE = ["compare", "comparison", "difference", "vs$", "versus", "muqayise", "ferq", "сравн", "разниц"]
FAST = ["fastest", "quickest", "shortest", "en qisa", "en tez", "быстр", "самый короткий"]
SORT = ["sort", "order by", "sirala", "сортир", "упорядоч"]
RETURN = ["return", "coming back", "back on", "geri qayit", "qayidis", "обратно", "обратный"]  # date after it is the return
LIMIT = 10  # longer lists (all destinations, a whole month of live fares) are cut with a hint
_ABLATIVE = ("dan", "den", "ndan", "nden", "tan", "ten")
_DATIVE = ("a", "e", "ya", "ye", "na", "ne")


BASE_KEYWORDS = [n for code, names in CITY_ALIASES.items() if code != "GYD" for n in names] + DIRECT + RETURN + [
    "round trip", "round-trip", "gedis-donus", "туда и обратно",
    "flight", "fly", "flies", "plane", "airline", "airport", "baggage", "luggage", "layover",
    "ucus", "ucaq", "reys", "aviabilet", "aeroport", "baqaj", "aktarma",
    "рейс", "перел", "самолет", "авиа", "багаж", "вылет", "аэропорт", "пересад"]


def keywords(repo):
    """Words that make the router send a message to this module."""
    airlines = sorted({nlp.fold(f["airline"].split()[0]) for f in repo.all()})
    numbers = [nlp.fold(f["flight_number"]) + "$" for f in repo.all()]
    return airlines + numbers + BASE_KEYWORDS


def find_route(t):
    """Origin and destination codes from 'from Baku to Istanbul', 'Bakıdan İstanbula', 'в Стамбул'."""
    found = []
    for code, names in CITY_ALIASES.items():
        for name in names:
            for m in re.finditer(r"(?<!\w)" + name + r"(\w*)", t):
                found.append((m.start(), code, m.group(1)))
    origin = dest = None
    loose = []
    for pos, code, suffix in sorted(found):
        before = t[max(0, pos - 6):pos]
        if suffix in _ABLATIVE or re.search(r"(from|из|от)\s*$", before):
            origin = origin or code
        elif suffix in _DATIVE or re.search(r"(to|в|во|до|на)\s*$", before):
            dest = dest or code
        else:
            loose.append(code)
    if len(loose) >= 2 and not origin and not dest:
        return loose[0], loose[1]
    for code in loose:
        if code == "GYD" and origin is None:
            origin = code
        elif dest is None and code != origin:
            dest = code
        elif origin is None and code != dest:
            origin = code
    return origin, dest


_NOT_PLACES = {"the", "a", "an", "my", "book", "fly", "go", "buy", "see", "get", "travel", "find", "me",
               "and", "be", "have", "make", "it", "them", "cheaper", "economy", "business", "flight",
               "flights", "cinema", "movies", "films", "shopping", "cart", "них", "этих", "течение"}


def live_route(t, repo, origin, dest):
    """Cities outside the alias table, resolved by the live source: 'to Paris', 'Parisə', 'в Берлин'.
    Without a preposition only Azerbaijani case endings count, so ordinary words are not taken for cities."""
    resolve = getattr(repo, "resolve_city", None)
    known = sum(CITY_ALIASES.values(), [])
    for m in re.finditer(r"(?:(?<!\w)(to|from|в|во|из|до)\s+)?(?<!\w)([^\W\d_]{3,})", t):
        if resolve is None or (origin and dest):
            break
        prep, word = m.group(1), m.group(2)
        if word in _NOT_PLACES or find(word, known) or (not prep and not word.endswith(_ABLATIVE + _DATIVE)):
            continue
        code = resolve(word)
        if not code:
            continue
        if prep in ("from", "из") or (not prep and word.endswith(_ABLATIVE)):
            origin = origin or code
        elif code != origin:
            dest = dest or code
    return origin, dest


_AZ_COMMON = {"sonra", "hansina", "haraya", "buraya", "oraya", "evvel", "qeder", "gore", "mene", "sene", "bize"}


_AZ_ENDINGS = ("ndan", "nden", "dan", "den", "tan", "ten", "ya", "ye", "a", "e")  # longest first


def unknown_place(t, repo=None, lang="en"):
    """A place outside our route network: after 'to'/'from'/'в'/'из' ('to Paris'), or, in an
    Azerbaijani message, a word with a from/to ending ('Londona'). The live source checks its
    city list first."""
    resolve = getattr(repo, "resolve_city", None)
    known = sum(CITY_ALIASES.values(), [])
    words = [(m.group(1), m.group(1)) for m in re.finditer(r"(?<!\w)(?:to|from|в|во|из)\s+(\w+)", t)]
    for w in re.findall(r"[a-z]{5,}", t) if lang == "az" else []:
        ending = next((e for e in _AZ_ENDINGS if w.endswith(e)), None)
        if ending and w not in _AZ_COMMON and not find(w, BASE_KEYWORDS + nlp.CHEAP):
            words.append((w, w[:-len(ending)]))  # "londona" is reported as "london"
    for word, shown in words:
        if word in _NOT_PLACES or word.isdigit() or nlp.parse_date(word) or find(word, known):
            continue
        if not (resolve and resolve(word)):
            return shown
    return None


def _city(repo, code):
    if hasattr(repo, "city_name"):
        return repo.city_name(code)
    for f in repo.all():
        for end in (f["origin"], f["destination"]):
            if end["code"] == code:
                return end["city"]
    return code


def _stops(f, lang, repo):
    if f["stops"] == 0:
        return tr(lang, "direct", "birbaşa", "прямой")
    if not f["via"]:
        return tr(lang, f"{f['stops']} stop(s)", f"{f['stops']} aktarma", f"пересадок: {f['stops']}")
    via = _city(repo, f["via"])
    return tr(lang, f"{f['stops']} stop via {via}", f"{f['stops']} aktarma ({via})",
              f"{f['stops']} пересадка ({via})")


def _line(i, f, lang, repo):
    """One flight. Baggage and seats left are only shown when the source reports them (the
    Aviasales Data API does not), instead of guessing."""
    extra = ""
    if f["baggage_kg"] is not None:
        extra += f" · {f['baggage_kg']} kg"
    if f["seats_available"] is not None:
        extra += f" · {f['seats_available']} {tr(lang, 'seats', 'yer', 'мест')}"
    return (f"{i}. {f['airline']} {f['flight_number']} · {fmt_day(f['departure_local'], lang)} "
            f"{f['departure_local'][11:]}→{f['arrival_local'][11:]} · "
            f"{nlp.fmt_minutes(f['duration_min'], lang)} · {_stops(f, lang, repo)} · "
            f"{money(f['price_azn'])}{extra}")


def _filter(t, items, repo):
    if find(t, DIRECT):
        items = [f for f in items if f["stops"] == 0]
    for f in repo.all():
        if find(t, [nlp.fold(f["airline"].split()[0])]):
            items = [x for x in items if x["airline"] == f["airline"]]
            break
    window = nlp.time_window(t)
    if window:
        items = [f for f in items if window[0] <= int(f["departure_local"][11:13]) < window[1]]
    if find(t, nlp.CHEAP + ["price", "qiymet", "цен"]):
        return sorted(items, key=lambda f: f["price_azn"])
    if find(t, FAST):
        return sorted(items, key=lambda f: f["duration_min"])
    if find(t, ["stop", "aktarma", "пересад"]):
        return sorted(items, key=lambda f: (f["stops"], f["departure_local"]))
    if find(t, ["by airline", "airline", "aviasirket", "авиакомпан"]):
        return sorted(items, key=lambda f: (f["airline"], f["departure_local"]))
    return sorted(items, key=lambda f: f["departure_local"])


def _has_filters(t, repo):
    airlines = [nlp.fold(f["airline"].split()[0]) for f in repo.all()]
    return find(t, DIRECT + FAST + nlp.CHEAP + airlines + SORT) or nlp.time_window(t) is not None


def _show(items, lang, repo, header):
    lines = [_line(i, f, lang, repo) for i, f in enumerate(items[:LIMIT], 1)]
    if len(items) > LIMIT:
        more = len(items) - LIMIT
        lines.append(tr(lang, f"…and {more} more. Add a date or 'direct' to narrow it down.",
                        f"…və daha {more} reys. Daraltmaq üçün tarix və ya 'birbaşa' yazın.",
                        f"…и ещё {more}. Укажите дату или «прямой», чтобы сузить."))
    return header + "\n" + "\n".join(lines)


def _search(t, s, repo, origin, dest, day, return_day=None):
    lang, st = s["lang"], s["flights"]
    if origin or dest:
        params = {"origin": origin or ("GYD" if dest != "GYD" else None), "dest": dest, "date": day}
    else:
        params = {"origin": st["search"].get("origin", "GYD"), "dest": st["search"].get("dest"), "date": day}
    st["search"] = params
    items = _filter(t, repo.search(params["origin"], params.get("dest"), params["date"]), repo)
    anywhere = tr(lang, "all destinations", "bütün istiqamətlər", "все направления")
    route = f"{_city(repo, params['origin']) if params['origin'] else anywhere} → " \
            f"{_city(repo, params['dest']) if params.get('dest') else anywhere}"
    when = f", {fmt_day(params['date'], lang)}" if params["date"] else ""
    back = []
    if return_day and params.get("dest"):
        back = _filter(t, repo.search(params["dest"], params["origin"], return_day), repo)
    st["results"] = [f["id"] for f in items[:LIMIT] + back]  # what "the first one" can refer to
    st["selected"] = items[0]["id"] if len(items) == 1 and not back else None
    if return_day and params.get("dest"):
        back_route = f"{_city(repo, params['dest'])} → {_city(repo, params['origin'])}, {fmt_day(return_day, lang)}"
        out = _show(items, lang, repo, tr(lang, f"Outbound {route}{when}:", f"Gediş {route}{when}:",
                                          f"Туда {route}{when}:")) if items else \
            tr(lang, f"No outbound flights {route}{when}.", f"Gediş uçuşu yoxdur: {route}{when}.",
               f"Рейсов туда нет: {route}{when}.")
        if back:
            lines = [_line(i, f, lang, repo) for i, f in enumerate(back, len(items[:LIMIT]) + 1)]
            ret = tr(lang, f"Return {back_route}:", f"Qayıdış {back_route}:", f"Обратно {back_route}:") + \
                "\n" + "\n".join(lines)
        else:
            ret = tr(lang, f"No return flights {back_route}.", f"Qayıdış uçuşu yoxdur: {back_route}.",
                     f"Обратных рейсов нет: {back_route}.")
        return out + "\n\n" + ret
    if not items:
        other = repo.search(params["origin"], params.get("dest"))
        msg = tr(lang, f"No flights found for {route}{when}.", f"{route}{when} üçün uçuş tapılmadı.",
                 f"Рейсов {route}{when} не найдено.")
        if other:
            days = ", ".join(fmt_day(d, lang) for d in sorted({f["departure_local"][:10] for f in other}))
            msg += " " + tr(lang, f"Dates with flights on this route: {days}.",
                            f"Bu istiqamətdə uçuş olan tarixlər: {days}.", f"Есть рейсы в эти даты: {days}.")
        return msg
    header = tr(lang, f"Flights {route}{when}:", f"Uçuşlar {route}{when}:", f"Рейсы {route}{when}:")
    return _show(items, lang, repo, header)


def _details(t, f, lang, repo):
    answer = ""
    if find(t, DIRECT + ["stop", "aktarma", "пересад"]):
        answer = (tr(lang, "Yes, it is direct. ", "Bəli, birbaşa uçuşdur. ", "Да, это прямой рейс. ")
                  if f["stops"] == 0 else
                  tr(lang, f"No, it has {_stops(f, lang, repo)}. ", f"Xeyr, {_stops(f, lang, repo)}. ",
                     f"Нет, {_stops(f, lang, repo)}. "))
    return answer + tr(lang, "Flight details:", "Uçuş məlumatı:", "Детали рейса:") + "\n" + _line(1, f, lang, repo)[3:]


def _compare(items, lang, repo):
    cheapest = min(items, key=lambda f: f["price_azn"])
    fastest = min(items, key=lambda f: f["duration_min"])
    lines = [_line(i, f, lang, repo) for i, f in enumerate(items, 1)]
    summary = tr(lang, f"Cheapest: {cheapest['flight_number']} · fastest: {fastest['flight_number']}",
                 f"Ən ucuz: {cheapest['flight_number']} · ən qısa: {fastest['flight_number']}",
                 f"Дешевле всего: {cheapest['flight_number']} · быстрее всего: {fastest['flight_number']}")
    if all(f["baggage_kg"] is not None for f in items):
        bags = max(items, key=lambda f: f["baggage_kg"])["flight_number"]
        summary += tr(lang, f" · most baggage: {bags}", f" · ən çox baqaj: {bags}", f" · больше багажа: {bags}")
    return "\n".join(lines + [summary])


def _reserve(t, s, repo, f):
    lang = s["lang"]
    count = nlp.parse_count(t) or s["prefs"].get("party") or 1
    booking = repo.reserve(f["id"], count)
    if booking is None:
        return tr(lang, f"Sorry, {f['flight_number']} has only {f['seats_available']} seats left.",
                  f"Təəssüf, {f['flight_number']} reysində cəmi {f['seats_available']} yer qalıb.",
                  f"К сожалению, на {f['flight_number']} осталось только {f['seats_available']} мест.")
    s["flights"]["selected"] = f["id"]
    total = money(f["price_azn"] * count)
    return tr(lang, f"Reserved ✅ Booking {booking['ref']}: {count} passenger(s), total {total} (mock, no payment).",
              f"Bron edildi ✅ Kod {booking['ref']}: {count} sərnişin, cəmi {total} (test bronu, ödəniş yoxdur).",
              f"Забронировано ✅ Код {booking['ref']}: пассажиров {count}, итого {total} (тестовая бронь, без оплаты).") \
        + "\n" + _line(1, f, lang, repo)[3:] + _buy_link(booking, lang)


def _buy_link(booking, lang):
    if not booking.get("url"):
        return ""
    return "\n" + tr(lang, f"Buy the ticket on Aviasales: {booking['url']}",
                     f"Bileti Aviasales-də alın: {booking['url']}",
                     f"Купить билет на Aviasales: {booking['url']}")


def handle(t, s, repo):
    lang, st = s["lang"], s["flights"]
    origin, dest = live_route(t, repo, *find_route(t))
    split = min([t.find(key) for key in RETURN if find(t, [key])] or [len(t)])  # "... and back on 9 Nov"
    day = nlp.parse_date(t[:split])
    return_day = nlp.parse_date(t[split:]) if split < len(t) else None
    place = None if (origin and dest) else unknown_place(t, repo, lang)
    if place and hasattr(repo, "resolve_city"):
        return tr(lang, f"Sorry, I could not find a city called '{place}'. Please check the spelling.",
                  f"Təəssüf, '{place}' adlı şəhər tapmadım. Yazılışı yoxlayın.",
                  f"К сожалению, я не нашёл город «{place}». Проверьте написание.")
    if place:
        cities = ", ".join(sorted({_city(repo, c) for c in CITY_ALIASES if c != "GYD"}))
        return tr(lang, f"Sorry, we have no flights for '{place}'. Available destinations: {cities}.",
                  f"Təəssüf, '{place}' üçün uçuş yoxdur. Mövcud istiqamətlər: {cities}.",
                  f"К сожалению, рейсов для «{place}» нет. Доступные направления: {cities}.")
    shown = [repo.get(i) for i in st["results"]]
    ref = None if (origin or dest or day) else nlp.pick(
        t, shown, name=lambda f: f"{f['airline']} {f['flight_number']}", clock=lambda f: f["departure_local"][11:16])
    if ref:
        st["selected"] = ref["id"]
    selected = repo.get(st["selected"]) if st["selected"] else None
    pending = st.pop("pending_book", None)
    if pending and ref:  # answer to "Which flight should I reserve?" keeps the original request
        t = pending + " " + t

    if find(t, BOOK):
        target = ref or selected or (shown[0] if len(shown) == 1 else None)
        if target:
            return _reserve(t, s, repo, target)
        if shown:
            st["pending_book"] = t
            return _show(shown, lang, repo, tr(lang, "Which flight should I reserve? For example: 'the first one'.",
                                               "Hansı reysi bron edim? Məsələn: 'birincini'.",
                                               "Какой рейс забронировать? Например: «первый»."))
        return tr(lang, "Which flight would you like to book? Tell me the route and date.",
                  "Hansı uçuşu bron etmək istəyirsiniz? İstiqaməti və tarixi yazın.",
                  "Какой рейс забронировать? Укажите направление и дату.")
    if origin or dest or day:
        return _search(t, s, repo, origin, dest, day, return_day)
    if find(t, COMPARE) and len(shown) >= 2:
        chosen = nlp.pick_many(t, shown)
        return _compare(chosen if len(chosen) >= 2 else shown, lang, repo)
    if ref:
        return _details(t, ref, lang, repo)
    if shown and _has_filters(t, repo):
        items = _filter(t, shown, repo)
        if not items:  # keep the earlier list, so "book the cheapest" still has something to refer to
            return tr(lang, "None of those flights match.", "Bu uçuşlardan heç biri uyğun gəlmir.",
                      "Ни один из этих рейсов не подходит.")
        st["results"] = [f["id"] for f in items[:LIMIT]]
        return _show(items, lang, repo, tr(lang, "Matching flights:", "Uyğun uçuşlar:", "Подходящие рейсы:"))
    if selected:
        return _details(t, selected, lang, repo)
    if shown:  # "back to the flights": the earlier results are still there
        return _show(shown, lang, repo, tr(lang, "Your flights:", "Uçuşlarınız:", "Ваши рейсы:"))
    return tr(lang, "Where and when would you like to fly? For example: 'Baku to Istanbul on Friday'.",
              "Haraya və nə vaxt uçmaq istəyirsiniz? Məsələn: 'cümə günü Bakıdan İstanbula'.",
              "Куда и когда хотите лететь? Например: «из Баку в Стамбул в пятницу».")
