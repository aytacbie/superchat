"""Rule-based router: decides which domain module(s) handle a message.

Categories: flights, shopping, cinema, mixed, follow_up, ambiguous, out_of_scope, greeting."""
from . import nlp
from .nlp import find, tr

BOOK = ["book", "reserve", "bron", "брон", "заброн"]
SEATS = ["seat", "ticket", "yer$", "bilet", "мест", "билет"]
CORE_FLIGHT = ["flight", "fly", "plane", "airline", "ucus", "ucaq", "reys", "aviabilet", "рейс", "перел",
               "самолет", "авиа"]
FOLLOW_UP = nlp.REFERENCE + BOOK + [
    "seat", "ticket", "yer$", "yerler", "bilet", "мест", "билет", "and for", "what about", "how about",
    "bes$", "а на$", "а в$", "more$", "daha", "еще", "price", "qiymet", "цена", "стоимост",
    "only$", "ones$", "yalniz", "только", "sort", "order by", "sirala", "сортир", "compare", "muqayise", "сравн"]
VAGUE = ["something", "anything", "recommend", "suggest", "bir sey", "maraqli", "tovsiye", "что-нибудь",
         "что-то", "посоветуй", "порекомендуй"]
TONIGHT = ["tonight", "bu axsam$", "сегодня вечером"]
GREETING = ["hi$", "hello", "hey$", "salam", "привет", "здравств", "help", "komek", "помо", "what can you do",
            "ne ede bilersen", "что ты умеешь"]
THANKS = ["thanks", "thank you", "thx", "ok$", "okay$", "great$", "cool$", "sag ol", "tesekkur", "eladir",
          "спасибо", "хорошо$", "отлично"]
# Topics we do not serve; a city name next to them ("hotel in Istanbul") is not a flight request.
OUT_OF_SCOPE = ["weather", "hotel", "taxi", "restaurant", "news", "joke", "visa", "hava$", "otel", "taksi",
                "restoran", "xeber", "погод", "отел", "гостиниц", "такси", "ресторан", "новост", "анекдот", "виз"]


def classify(t, session, keywords):
    """Return (category, domains to call) for the folded message t."""
    hits = [d for d, keys in keywords.items() if find(t, keys)]
    if find(t, OUT_OF_SCOPE):
        hits = [d for d in hits if d != "flights" or find(t, CORE_FLIGHT)]
    active = session["active"]
    if len(hits) > 1:
        return "mixed", hits
    if hits:
        if hits[0] == active and find(t, FOLLOW_UP):
            return "follow_up", hits
        return hits[0], hits
    if find(t, TONIGHT):
        return "cinema", ["cinema"]
    follow = find(t, FOLLOW_UP) or nlp.parse_date(t) is not None or nlp.time_window(t) is not None
    if find(t, BOOK + SEATS):
        options = bookable(session)
        if len(options) > 1:  # "book it" with a flight AND a film on the table: ask which
            return "ambiguous", []
        if len(options) == 1 and options[0] != active:  # shopping cannot book; use the one that can
            return "follow_up", options
    if active and (follow or find(t, VAGUE)):
        return "follow_up", [active]
    if follow or find(t, VAGUE):
        return "ambiguous", []
    if find(t, GREETING + THANKS):
        return "greeting", []
    return "out_of_scope", []


def bookable(session):
    """Domains where the user has something on the table that 'book it' could refer to."""
    return [d for d in ("flights", "cinema")
            if session[d]["results"] or session[d].get("selected") or session[d].get("showtime")]


def clarify(t, session):
    lang = session["lang"]
    if find(t, BOOK + SEATS) and len(bookable(session)) > 1:
        return tr(lang, "Should I book the flight ✈️ or the cinema tickets 🎬?",
                  "Uçuşu ✈️ bron edim, yoxsa kino biletini 🎬?",
                  "Что забронировать: рейс ✈️ или билеты в кино 🎬?")
    if find(t, BOOK + SEATS):
        return tr(lang, "What would you like to book: cinema tickets or a flight? Please tell me the film and "
                        "showtime, or the route and date.",
                  "Nəyi bron etmək istəyirsiniz: kino bileti, yoxsa uçuş? Film və seansı, ya da istiqamət "
                  "və tarixi yazın.",
                  "Что забронировать: билеты в кино или рейс? Укажите фильм и сеанс или направление и дату.")
    return tr(lang, "Happy to help! Do you mean flights ✈️, products 🛒 or films 🎬?",
              "Məmnuniyyətlə! Uçuşları ✈️, məhsulları 🛒, yoxsa filmləri 🎬 nəzərdə tutursunuz?",
              "С удовольствием! Вы имеете в виду рейсы ✈️, товары 🛒 или фильмы 🎬?")


def help_text(t, lang):
    if find(t, THANKS):
        return tr(lang, "You're welcome! Anything else: flights, shopping or cinema?",
                  "Buyurun! Başqa nə lazımdır: uçuş, alış-veriş, yoxsa kino?",
                  "Пожалуйста! Что-нибудь ещё: рейсы, покупки или кино?")
    return _help(lang)


def _help(lang):
    return tr(lang, "Hi! I am SuperChat. I can find flights ✈️, shop for products 🛒 and find films and "
                    "showtimes at CinemaPlus 🎬. Try: 'Flights from Baku to Istanbul on Friday'.",
              "Salam! Mən SuperChat-am. Uçuş ✈️, məhsul 🛒 və CinemaPlus-da film və seans 🎬 tapa bilərəm. "
              "Məsələn: 'Cümə günü Bakıdan İstanbula uçuş'.",
              "Привет! Я SuperChat. Помогу найти рейсы ✈️, товары 🛒, фильмы и сеансы в CinemaPlus 🎬. "
              "Например: «Рейсы из Баку в Стамбул в пятницу».")


def out_of_scope(lang):
    return tr(lang, "Sorry, I can't help with that. I can search flights ✈️, products 🛒 and films at "
                    "CinemaPlus 🎬.",
              "Bağışlayın, bu mövzuda kömək edə bilmirəm. Uçuş ✈️, məhsul 🛒 və CinemaPlus filmləri 🎬 "
              "üzrə kömək edə bilərəm.",
              "Извините, с этим я не помогу. Я умею искать рейсы ✈️, товары 🛒 и фильмы в CinemaPlus 🎬.")
