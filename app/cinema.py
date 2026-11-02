"""Cinema module: films, showtimes, seat availability and mock ticket reservations."""
import re

from . import nlp
from .nlp import find, fmt_day, fold, money, tr

GENRES = {
    "sci-fi": ["sci-fi", "sci fi", "scifi", "science fiction", "fantastik", "фантаст"],
    "thriller": ["thriller", "triller", "триллер"],
    "adventure": ["adventure", "macera", "приключ"],
    "drama": ["drama", "драм"],
    "comedy": ["comed", "komedi", "комеди"],
    "horror": ["horror", "qorxu", "ужас"],
    "mystery": ["mystery", "mistik", "детектив", "мистик"],
    "animation": ["animat", "cartoon", "cizgi", "мульт", "анимац"],
    "family": ["family film", "family movie", "ailevi", "семейн"],
    "action": ["action", "boyevik", "боевик"],
    "crime": ["crime", "kriminal", "криминал"],
    "romance": ["romance", "romantic", "romantik", "романт"],
    "fantasy": ["fantasy", "fentezi", "фэнтези"],
}
LANGUAGES = {
    "English": ["english", "ingilis", "англ"],
    "Russian": ["russian", "rus dilinde", "rusca", "русск"],
    "Azerbaijani": ["azerbaijani", "azeri", "azerbaycan", "азербайдж"],
    "Turkish": ["turkish", "turk dilinde", "turkce", "турецк"],
}
CINEMAS = {"C001": ["ganjlik", "genclik", "гянджлик"], "C002": ["28 mall", "28mall"],
           "C003": ["sumgayit", "sumqayit", "сумгаит"]}  # mock cinemas; live ones bring their own aliases
BOOK = ["book", "reserve", "bron", "брон", "заброн"]
BEST = ["best", "top", "highest", "en yaxsi", "reytinq", "лучш", "рейтинг", "good"]
CINEMA_LIST = ["cinemas$", "which cinema", "where is cinemaplus", "kinoteatrlar", "hansi kinoteatr",
               "кинотеатры", "какие кинотеатры"]
LIST_ALL = ["playing", "showing", "what's on", "what is on", "ne var", "ne gedir", "идет", "афиш"]


LIMIT = 10  # a real schedule has 100+ showtimes a day; longer lists are cut with a hint to narrow down
BASE_KEYWORDS = sum(GENRES.values(), []) + LIST_ALL + [
    "movie", "film", "cinema", "kino", "showtime", "session", "seans", "hall$",
    "кино", "фильм", "сеанс", "reytinq", "рейтинг"]


def _titles(m):
    return [fold(m["title"])] + m.get("aliases", [])


def _cinema_keys(repo):
    return {c["id"]: c.get("aliases") or CINEMAS.get(c["id"], []) for c in repo.cinemas}


def keywords(repo):
    # titles such as "44" or "Up" would grab unrelated messages, so short ones only match inside Cinema
    titles = [w for m in repo.movies for w in _titles(m) if len(w) >= 4 and not w.isdigit()]
    return titles + sum(_cinema_keys(repo).values(), []) + BASE_KEYWORDS


def _movie_label(m, lang, sh=None):
    parts = ["/".join(m["genre"]), (sh or {}).get("language") or m["language"], m["age_rating"]]
    if m["rating"] is not None:
        parts.append(f"★{m['rating']}")
    return f"{m['title']} ({' · '.join(p for p in parts if p)})"


def _seats(sh, lang):
    if sh["seats_available"] is None:
        return tr(lang, "seats: see cinemaplus.az", "yerlər: cinemaplus.az", "места: см. cinemaplus.az")
    if sh["seats_available"] == 0:
        return tr(lang, "sold out", "yer yoxdur", "мест нет")
    return tr(lang, f"{sh['seats_available']} seats left", f"{sh['seats_available']} boş yer",
              f"свободно {sh['seats_available']} мест")


def _line(i, sh, lang, repo):
    m, c = repo.movie(sh["movie_id"]), repo.cinema(sh["cinema_id"])
    return (f"{i}. {_movie_label(m, lang, sh)} — {fmt_day(sh['date'], lang)} {sh['time']} · {c['name']}, "
            f"{sh['hall']} · {money(sh['price_azn'])} · {_seats(sh, lang)}")


def _lines(items, lang, repo):
    """Numbered showtime lines, at most LIMIT of them; seat maps for those are loaded in parallel.
    Returns the text and the showtimes it shows (what 'the second one' refers to next)."""
    shown = items[:LIMIT]
    if hasattr(repo, "warm"):
        repo.warm(shown)
    text = "\n".join(_line(i, sh, lang, repo) for i, sh in enumerate(shown, 1))
    if len(items) > LIMIT:
        more = len(items) - LIMIT
        text += "\n" + tr(lang, f"…and {more} more. Name a film, cinema or time to narrow it down.",
                          f"…və daha {more} seans. Film, kinoteatr və ya vaxt yazın ki, daraldım.",
                          f"…и ещё {more}. Уточните фильм, кинотеатр или время.")
    return text, shown


def _details(sh, lang, repo):
    m, c = repo.movie(sh["movie_id"]), repo.cinema(sh["cinema_id"])
    runtime = f", {nlp.fmt_minutes(m['duration_min'], lang)}" if m["duration_min"] else ""
    return (f"{_movie_label(m, lang, sh)}{runtime}\n{m['synopsis']}\n"
            f"{fmt_day(sh['date'], lang)} {sh['time']} · {c['name']} ({c['address']}), {sh['hall']}\n"
            f"{tr(lang, 'Ticket', 'Bilet', 'Билет')}: {money(sh['price_azn'])} · {_seats(sh, lang)}")


def _min_rating(t):
    """'rating above 8', 'reytinqi 8-dən yuxarı', 'рейтинг выше 8' -> 8.0"""
    m = re.search(r"(?:rating|rated|reytinq|рейтинг)\D{0,20}?(\d(?:[.,]\d)?)(?!\d)", t)
    return float(m.group(1).replace(",", ".")) if m else None


def _search(repo, movies, genres, langs, cinemas, day, window, rating=None):
    out = []
    for sh in repo.search(date=day):
        m = repo.movie(sh["movie_id"])
        if day is None and sh["date"] < nlp.TODAY.isoformat():
            continue
        if movies and m["id"] not in movies:
            continue
        if genres and not set(genres) & set(m["genre"]):
            continue
        if langs and sh.get("language", m["language"]) not in langs:
            continue
        if cinemas and sh["cinema_id"] not in cinemas:
            continue
        if window and not window[0] <= int(sh["time"][:2]) < window[1]:
            continue
        if rating and (m["rating"] or 0) < rating:
            continue
        out.append(sh)
    return out


def _cinema_list(lang, repo):
    lines = [f"{i}. {c['name']} — {c['district']} · {c['address']}" for i, c in enumerate(repo.cinemas, 1)]
    return tr(lang, "Our cinemas:", "Kinoteatrlarımız:", "Наши кинотеатры:") + "\n" + "\n".join(lines)


def _reserve(t, s, repo, sh):
    lang = s["lang"]
    count = nlp.parse_count(t) or s["prefs"].get("party") or 1
    m = repo.movie(sh["movie_id"])
    booking = repo.reserve(sh["id"], count)
    if booking is None:
        return tr(lang, f"Sorry, only {sh['seats_available']} seats are left for that showtime.",
                  f"Təəssüf, bu seansa cəmi {sh['seats_available']} yer qalıb.",
                  f"К сожалению, на этот сеанс осталось только {sh['seats_available']} мест.")
    s["cinema"]["showtime"] = sh["id"]
    total = money(sh["price_azn"] * count)
    return tr(lang, f"Reserved ✅ Booking {booking['ref']}: {count} ticket(s) for {m['title']}, total {total} "
                    f"(mock, no payment).",
              f"Bron edildi ✅ Kod {booking['ref']}: {m['title']} üçün {count} bilet, cəmi {total} "
              f"(test bronu, ödəniş yoxdur).",
              f"Забронировано ✅ Код {booking['ref']}: {count} билет(а) на {m['title']}, итого {total} "
              f"(тестовая бронь, без оплаты).") + "\n" + _line(1, sh, lang, repo)[3:] + _buy_link(booking, lang)


def _buy_link(booking, lang):
    if not booking.get("url"):
        return ""
    return "\n" + tr(lang, f"Buy the tickets on CinemaPlus: {booking['url']}",
                     f"Biletləri CinemaPlus-da alın: {booking['url']}",
                     f"Купить билеты на CinemaPlus: {booking['url']}")


def handle(t, s, repo):
    lang, st = s["lang"], s["cinema"]
    shown = [repo.get(i) for i in st["results"]]
    movies = [m["id"] for m in repo.movies if find(t, [w + "$" if len(w) < 4 else w for w in _titles(m)])]
    genres = [g for g, keys in GENRES.items() if find(t, keys)]
    langs = [name for name, keys in LANGUAGES.items() if find(t, keys)]
    cinemas = [cid for cid, keys in _cinema_keys(repo).items() if find(t, keys)]
    day = nlp.parse_date(t)
    window = nlp.time_window(t)
    rating = _min_rating(t)
    if movies or genres:
        st["focus"] = {"movies": movies, "genres": genres}
    elif find(t, LIST_ALL):
        st["focus"] = None
    elif day and st["focus"]:  # "and for Saturday?" keeps the film the user was asking about
        movies, genres = st["focus"]["movies"], st["focus"]["genres"]
    has_filter = movies or genres or langs or cinemas or day or window or rating
    ref = None if has_filter else nlp.pick(
        t, shown, name=lambda sh: repo.movie(sh["movie_id"])["title"], clock=lambda sh: sh["time"])
    if ref:
        st["showtime"] = ref["id"]
    selected = repo.get(st["showtime"]) if st["showtime"] else None
    pending = st.pop("pending_book", None)
    if pending and (ref or has_filter):  # answer to "Which showtime should I book?" keeps the request
        t = pending + " " + t

    if find(t, BOOK):
        found = _search(repo, movies, genres, langs, cinemas, day, window, rating) if has_filter else []
        free = [sh for sh in found if sh["seats_available"] > 0]
        target = ref or (free[0] if len(free) == 1 else None) or (None if has_filter else selected)
        if target is None and not found and len(shown) == 1:
            target = shown[0]
        if target:
            return _reserve(t, s, repo, target)
        if found and not free:
            return tr(lang, "Sorry, that showtime is sold out.", "Təəssüf, bu seansa bilet qalmayıb.",
                      "К сожалению, на этот сеанс билетов нет.") + "\n" + _lines(found, lang, repo)[0]
        options = free or [sh for sh in shown if sh["seats_available"] > 0]
        if options:
            text, options = _lines(options, lang, repo)
            st["results"] = [sh["id"] for sh in options]
            st["pending_book"] = t
            return tr(lang, "Which showtime should I book? For example: 'the first one'.",
                      "Hansı seansı bron edim? Məsələn: 'birincini'.",
                      "Какой сеанс забронировать? Например: «первый».") + "\n" + text
        return tr(lang, "Which film and showtime would you like to book?",
                  "Hansı film və seans üçün bron edim?", "На какой фильм и сеанс забронировать?")
    if ref:
        return _details(ref, lang, repo)
    if find(t, CINEMA_LIST) and not (movies or genres or day):
        return _cinema_list(lang, repo)
    if not has_filter and not find(t, LIST_ALL + BEST):
        if selected:
            return _details(selected, lang, repo)
        if shown:  # "back to the films": the earlier results are still there
            return tr(lang, "Your showtimes:", "Seanslarınız:", "Ваши сеансы:") + "\n" + _lines(shown, lang, repo)[0]

    if not (movies or genres or langs or cinemas or day or rating):
        day = nlp.TODAY.isoformat()
    found = _search(repo, movies, genres, langs, cinemas, day, window, rating)
    if find(t, BEST) or rating:
        found.sort(key=lambda sh: -(repo.movie(sh["movie_id"])["rating"] or 0))
    st["results"] = [sh["id"] for sh in found[:LIMIT]]
    st["showtime"] = found[0]["id"] if len(found) == 1 else None
    when = f" ({fmt_day(day, lang)})" if day else ""
    if not found:
        msg = tr(lang, f"No showtimes match{when}.", f"Uyğun seans yoxdur{when}.", f"Подходящих сеансов нет{when}.")
        other = _search(repo, movies, genres, langs, cinemas, None, None) if movies or genres else []
        if other:
            days = ", ".join(fmt_day(d, lang) for d in sorted({sh["date"] for sh in other}))
            msg += " " + tr(lang, f"Showing on: {days}.", f"Bu tarixlərdə göstərilir: {days}.",
                            f"Идёт в эти дни: {days}.")
        return msg
    text, _ = _lines(found, lang, repo)
    header = tr(lang, f"Showtimes{when}:", f"Seanslar{when}:", f"Сеансы{when}:")
    return header + "\n" + text
