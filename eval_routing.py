"""Routing test log: runs scripted conversations and reports routing accuracy plus answer checks.

Usage: python eval_routing.py        (add -v to print every reply)

Each turn is (message, expected category, text the reply must contain or None).
Every conversation starts from a fresh session and fresh mock data."""
import importlib
import os
import sys
from collections import defaultdict

os.environ["SUPERCHAT_DATA"] = "mock"  # routing is measured on the official mock dataset
import app.main  # noqa: E402

CONVERSATIONS = [
    # ---- the eight sample conversations from the brief (section 7) ----
    [("Find me a flight from Baku to Istanbul on Friday.", "flights", "CA101"),
     ("What is playing tonight?", "cinema", "Orbit Zero"),
     ("Do you have wireless headphones under 100 AZN?", "shopping", "89.90")],
    [("What is playing tonight?", "cinema", "Laugh Track"),
     ("Show me laptops.", "shopping", "Laptop 15"),
     ("Okay, and the sci-fi one, any seats on Saturday?", "cinema", "Sat 7 Nov")],
    [("Show me laptops.", "shopping", "Laptop 14"),
     ("The second one, is it in stock?", "follow_up", "in stock: 7")],
    [("Flights to Istanbul on 6 November.", "flights", "BA220"),
     ("The cheaper one, is it direct?", "follow_up", "No, it has 1 stop")],
    [("I need a flight to Istanbul on 6 November and a backpack for the trip.", "mixed", "Backpack 25L")],
    [("Show me something good.", "ambiguous", "flights")],
    [("What is the weather in Ganja?", "out_of_scope", "can't help")],
    [("Book two seats.", "ambiguous", "film and showtime")],

    # ---- Flights module (3.4) ----
    [("Flights from Baku to Dubai", "flights", "SB410"),
     ("Only direct ones", "follow_up", "SB412"),
     ("Compare them", "follow_up", "Cheapest"),
     ("Book the cheapest one for 2 passengers", "follow_up", "930.00 AZN")],
    [("Bakı-Moskva reysləri", "flights", "AW300"),
     ("Səhər uçanlar", "follow_up", "AW300"),
     ("Bunu bron et", "follow_up", "FL0001")],
    [("Flights to Istanbul on Friday sorted by price", "flights", "175.00"),
     ("What about Caspian Air?", "follow_up", "CA101"),
     ("How much baggage on CA101?", "flights", "20 kg")],
    [("Flights to Istanbul on Friday", "flights", "AW520"),
     ("The 14:20 one, how many seats are left?", "follow_up", "3 seats")],
    [("Flights from Baku to Istanbul", "flights", "CA107"),
     ("Sort by fewest stops", "follow_up", "1. Caspian Air CA101"),
     ("Sort by price", "follow_up", "1. Azerwings AW520"),
     ("Sort by departure time", "follow_up", "1. Azerwings AW520"),
     ("Compare the second and the third", "follow_up", "Cheapest: BA220")],
    [("Products between 50 and 100 AZN", "shopping", "Portable Speaker"),
     ("Compare the first and the third", "follow_up", "best rated: Portable Speaker"),
     ("Товары от 300 до 600 манат", "shopping", "Кофемашина")],
    [("Round trip Baku to Istanbul on 6 November, return on 9 November", "flights", "BA221")],
    [("Flights to Paris on Friday", "flights", "no flights for 'paris'")],
    [("Bakıdan Londona uçuş", "flights", "'london' üçün uçuş yoxdur")],
    [("Any flights to Tbilisi on Saturday?", "flights", "Dates with flights")],
    [("Рейсы из Баку в Ташкент", "flights", "SB610"),
     ("Забронируй его", "follow_up", "FL0001")],
    [("We are 2 people. Flights to Tbilisi tomorrow", "flights", "AW150"),
     ("Book it", "follow_up", "190.00 AZN")],

    # ---- Shopping module (3.5) ----
    [("Show me black products from Sonivo", "shopping", "Portable Speaker"),
     ("Compare them", "follow_up", "best rated")],
    [("Phones under 600 AZN", "shopping", "X5 Lite"),
     ("Add it to my cart", "follow_up", "549.00"),
     ("Add 2 board games", "shopping", "Board Game Set × 2"),
     ("What is in my cart?", "shopping", "627.00"),
     ("Remove the phone", "shopping", "Board Game Set"),
     ("Show my cart", "shopping", "78.00")],
    [("Wireless earbuds", "shopping", "out of stock"),
     ("Add them to the cart", "follow_up", "only 0")],
    [("Show me laptops", "shopping", "Laptop 15"),
     ("Is the Pro in stock?", "shopping", "in stock: 7")],
    [("Smartfonları müqayisə et", "shopping", "Ən ucuz"),
     ("Mavi olan hansıdır?", "shopping", "X5 Lite")],
    [("Наушники до 100 манат", "shopping", "Беспроводные наушники"),
     ("Добавь в корзину", "shopping", "Итого")],
    [("Do you sell bicycles?", "out_of_scope", None)],
    [("Salam mene iphone18 lazimdi", "shopping", "'iphone 18' kataloqumuzda yoxdur")],
    [("I need an iPhone 18", "shopping", "not in our catalogue")],
    [("Мне нужен айфон", "shopping", "нет в нашем каталоге")],

    # ---- Cinema module (3.6) ----
    [("Which films are showing on Friday?", "cinema", "Deep Signal"),
     ("Book 2 tickets for the first one", "follow_up", "CN0001")],
    [("Comedies in Russian", "cinema", "Laugh Track"),
     ("Films with rating above 8", "cinema", "Deep Signal")],
    [("Which cinemas do you have?", "cinema", "28 Mall"),
     ("What is on at CinemaPlus Sumgayit?", "cinema", "Paper Kites")],
    [("Book Deep Signal tonight", "cinema", "sold out")],
    [("Orbit Zero showtimes", "cinema", "Thu 5 Nov"),
     ("and for Saturday?", "follow_up", "5 seats left"),
     ("Book 6 seats", "follow_up", "only 5 seats")],
    [("Is Orbit Zero playing tomorrow?", "cinema", "Showing on"),
     ("The 19:30 one on Saturday", "follow_up", "14.00 AZN")],
    [("Şənbə günü hansı filmlər var?", "cinema", "Paper Kites"),
     ("İkincisinə 3 bilet bron et", "follow_up", "33.00 AZN")],
    [("Что идет в субботу?", "cinema", "Iron Ledger"),
     ("Фильмы на английском", "cinema", "Midnight Archive")],
    [("We are 3 people, any horror films?", "cinema", "Midnight Archive"),
     ("Book the first one", "follow_up", "33.00 AZN")],

    # ---- switching, returning to earlier topics, shared state (3.2, 3.3) ----
    [("Flights to Dubai on Sunday", "flights", "SB412"),
     ("Show me headphones", "shopping", "Wireless Headphones"),
     ("What's on tonight?", "cinema", "Orbit Zero"),
     ("Back to the flights", "flights", "SB412"),
     ("Back to the headphones", "shopping", "89.90"),
     ("And the film, the first one, any seats?", "cinema", "34 seats")],
    [("Cümə günü İstanbula uçuş", "flights", "AW520"),
     ("Kinoda bu axşam nə var?", "cinema", "Orbit Zero"),
     ("Qara qulaqlıq", "shopping", "Simsiz qulaqlıq"),
     ("Uçuşa qayıdaq, ən ucuzu", "flights", "175.00")],
    [("Нужен рейс в Стамбул 6 ноября и рюкзак", "mixed", "Рюкзак"),
     ("И что посмотреть в кино вечером?", "cinema", "Orbit Zero"),
     ("Какая погода в Баку?", "out_of_scope", None)],
    [("Laptop and a flight to Moscow", "mixed", "AW300"),
     ("Wireless headphones and tickets for Orbit Zero", "mixed", "Orbit Zero")],

    # ---- "book it" when both a flight and a film are on the table: ask, then remember the request ----
    [("We are 2. Flights to Tbilisi tomorrow", "flights", "AW150"),
     ("What's on tonight?", "cinema", "Orbit Zero"),
     ("Book it", "ambiguous", "flight ✈️ or the cinema"),
     ("The flight", "flights", "2 passenger")],
    [("Bakıdan Tbilisiyə sabah uçuş", "flights", "AW150"),
     ("Bu axşam kinoda nə var?", "cinema", "Laugh Track"),
     ("2 bilet bron et", "ambiguous", "kino biletini"),
     ("Kino", "cinema", "Hansı seansı"),
     ("Birincini", "follow_up", "24.00 AZN")],
    [("Flights to Dubai on Sunday", "flights", "SB412"),
     ("Show me headphones", "shopping", "Wireless Headphones"),
     ("Book it", "follow_up", "FL0001")],
    [("Which films are on Saturday?", "cinema", "Iron Ledger"),
     ("Book 2 tickets", "follow_up", "Which showtime"),
     ("The 19:30 one", "follow_up", "28.00 AZN")],
    [("What's on tonight?", "cinema", "Orbit Zero"),
     ("Book 2 seats", "follow_up", "Which showtime"),
     ("Deep Signal", "cinema", "Which showtime"),
     ("Friday", "follow_up", "26.00 AZN")],

    # ---- ambiguity, small talk and out of scope ----
    [("Book it", "ambiguous", None),
     ("Recommend something", "ambiguous", None),
     ("Hello", "greeting", "SuperChat"),
     ("Thanks!", "greeting", "welcome"),
     ("Hotel in Istanbul", "out_of_scope", None),
     ("Tell me a joke", "out_of_scope", None),
     ("Who won the football match?", "out_of_scope", None),
     ("Gəncədə hava necədir?", "out_of_scope", None),
     ("Сколько стоит такси в аэропорт?", "out_of_scope", None)],
]


def fresh():
    """Reload the app so every conversation starts with untouched mock data."""
    importlib.reload(app.main)
    return app.main.new_session()


def main(verbose):
    total = routed = answered = checks = 0
    per_cat = defaultdict(lambda: [0, 0])
    misses = []
    for conv in CONVERSATIONS:
        s = fresh()
        for message, expected, must in conv:
            reply, got = app.main.respond(message, s)
            total += 1
            per_cat[expected][1] += 1
            if got == expected:
                routed += 1
                per_cat[expected][0] += 1
            else:
                misses.append(f"ROUTE  {message!r}: expected {expected}, got {got}")
            if must:
                checks += 1
                if must.lower() in reply.lower():
                    answered += 1
                else:
                    misses.append(f"ANSWER {message!r}: missing {must!r}")
            if verbose:
                print(f"> {message}\n[{got}]\n{reply}\n")
    print(f"Routing accuracy: {routed}/{total} = {100 * routed / total:.1f}%")
    print(f"Answer checks:    {answered}/{checks} = {100 * answered / checks:.1f}%")
    print("Per category:")
    for cat, (ok, n) in sorted(per_cat.items()):
        print(f"  {cat:<13} {ok}/{n}")
    for line in misses:
        print("  MISS " + line)


if __name__ == "__main__":
    main("-v" in sys.argv)
