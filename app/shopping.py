"""Shopping module: product search, details, comparison, stock and cart."""
import re

from . import nlp
from .nlp import find, fold, money, tr

CATEGORIES = {
    "audio": ["headphone", "earphone", "earbud", "speaker", "audio", "qulaqliq", "qulaqciq", "dinamik",
              "наушник", "колонк"],
    "computers": ["laptop", "notebook", "computer", "noutbuk", "kompyuter", "ноутбук", "компьютер"],
    "phones": ["phone", "smartphone", "telefon", "smartfon", "телефон", "смартфон"],
    "wearables": ["smartwatch", "smart watch", "agilli saat", "умные час", "часы$"],
    "sport": ["shoe", "sneaker", "ayaqqabi", "кроссовк", "обув"],
    "accessories": ["backpack", "bag$", "bags$", "canta", "рюкзак", "сумк"],
    "home": ["coffee", "qehve", "кофе"],
    "gifts": ["board game", "gift", "game$", "games$", "oyun", "hediyye", "игра$", "игру$", "игры$",
              "настольн", "подар"],
    # categories that only the live catalogue has
    "tablets": ["tablet", "ipad", "planset", "планшет"],
    "fragrances": ["perfume", "fragrance", "etir", "духи", "парфюм"],
    "beauty": ["makeup", "mascara", "lipstick", "kosmetik", "косметик"],
    "sunglasses": ["sunglass", "gunes eyney", "солнцезащит"],
    "groceries": ["grocer", "meyve", "terevez", "продукт"],
}
COLORS = {
    "black": ["black", "qara", "черн"],
    "white": ["white", "ag$", "бел"],
    "silver": ["silver", "gumus", "серебр"],
    "grey": ["grey", "gray", "boz$", "серый", "серого", "серые"],
    "blue": ["blue", "mavi", "goy$", "син"],
}
ADD = ["add", "put", "elave", "добав", "положи"]
REMOVE = ["remove", "delete", "take out", "sil$", "silin", "cixar", "удал", "убер"]
CART = ["cart", "basket", "sebet", "корзин"]
STOCK = ["stock", "stok", "налич"]
COMPARE = ["compare", "comparison", "difference", "vs$", "versus", "muqayise", "ferq", "сравн", "разниц"]
_SKIP = {"saat", "dest", "speak", "lite", "pro"}
# Short words in live product names ("Green and Black Glasses", "CK One") that are not model names.
_SHORT_SKIP = {"and", "the", "for", "with", "one", "men", "new", "set", "of", "in", "by", "to", "on", "at", "red"}
LIMIT = 10  # the live catalogue can match dozens of products; longer lists are cut with a hint
# Words that only express wanting something; what is left of the message is the product asked for.
_FILLER = {"salam", "hi", "hello", "hey", "привет", "здравствуйте", "mene", "menim", "ucun", "lazim", "lazimdi",
           "lazimdir", "lazimdır", "need", "i", "a", "an", "the", "want", "to", "buy", "please", "do", "you", "have",
           "sell", "is", "there", "any", "almaq", "isteyirem", "axtariram", "varmi", "var", "satirsiz", "mi", "bir",
           "мне", "нужен", "нужна", "нужно", "купить", "хочу", "ищу", "есть", "у", "вас", "ли", "пожалуйста"}
BASE_KEYWORDS = sum(CATEGORIES.values(), []) + sum(COLORS.values(), []) + CART + STOCK + [
    "shop", "product", "mehsul", "magaza", "alis-veris", "товар", "магазин", "покупк"]


def _stems(p):
    """Word stems from a product's names in all three languages ('headphones' -> 'headphon')."""
    out = set()
    for name in p["name"].values():
        for w in re.findall(r"\w+", fold(name)):
            if len(w) >= 4 and not w.isdigit():
                stem = w[:max(4, len(w) - 2)]
                if stem not in _SKIP:
                    out.add(stem)
    return out


def _short_names(p):
    """Short model words such as 'Pro', 'Air', 'X5' that only count as whole words."""
    return {w + "$" for name in p["name"].values() for w in re.findall(r"\w+", fold(name))
            if 2 <= len(w) < 4 and not w.isdigit() and w not in _SHORT_SKIP}


def keywords(repo):
    if hasattr(repo, "keywords"):  # a live catalogue picks its own distinctive words
        return repo.keywords() + BASE_KEYWORDS
    stems = {stem for p in repo.all() for stem in _stems(p)}
    brands = {fold(p["brand"]) for p in repo.all()}
    return sorted(stems | brands) + BASE_KEYWORDS


def _price_range(t):
    m = (re.search(r"(?:between|arasi|от)?\s*(\d+(?:[.,]\d+)?)\s*(?:azn|manat)?\s*(?:and|-|–|to|ile|до)\s*"
                   r"(\d+(?:[.,]\d+)?)\s*(?:azn|manat|ман)", t)
         or re.search(r"between\s*(\d+(?:[.,]\d+)?)\s*and\s*(\d+(?:[.,]\d+)?)", t))
    if m:  # "between 50 and 100 AZN", "50-100 AZN", "от 50 до 100 манат", "50 ilə 100 manat"
        return float(m.group(1).replace(",", ".")), float(m.group(2).replace(",", "."))
    lo = hi = None
    m = (re.search(r"(?:under|below|less than|up to|max|cheaper than|within|до|дешевле|меньше|не дороже)"
                   r"\s*(\d+(?:[.,]\d+)?)", t)
         or re.search(r"(\d+(?:[.,]\d+)?)\s*(?:azn|manat)?[\w-]*\s+(?:ucuz|asagi|qeder)", t))
    if m:
        hi = float(m.group(1).replace(",", "."))
    m = (re.search(r"(?:over|above|more than|from|от|дороже|больше)\s*(\d+(?:[.,]\d+)?)", t)
         or re.search(r"(\d+(?:[.,]\d+)?)\s*(?:azn|manat)?[\w-]*\s+(?:baha|yuxari)", t))
    if m:
        lo = float(m.group(1).replace(",", "."))
    return lo, hi


def _search(t, repo):
    """Products matching the message, or None if the message names no product criteria."""
    products = repo.all()
    hits = {p["id"]: sum(1 for key in _stems(p) | _short_names(p) if find(t, [key])) for p in products}
    best = max(hits.values())
    category = next((c for c, keys in CATEGORIES.items() if find(t, keys)), None)
    brand = next((p["brand"] for p in products if find(t, [fold(p["brand"])])), None)
    color = next((c for c, keys in COLORS.items() if find(t, keys)), None)
    lo, hi = _price_range(t)
    if not (best or category or brand or color or lo is not None or hi is not None):
        return None
    if best and category and hasattr(repo, "search_text"):
        # live titles often lack the category word ("MacBook Pro" is a laptop): take both
        products = [p for p in products if hits[p["id"]] == best or p["category"] == category]
    elif best:
        products = [p for p in products if hits[p["id"]] == best]
    elif category:
        products = [p for p in products if p["category"] == category]
    if brand:
        products = [p for p in products if p["brand"] == brand]
    if color:
        products = [p for p in products if p["color"] == color]
    if lo is not None:
        products = [p for p in products if p["price_azn"] >= lo]
    if hi is not None:
        products = [p for p in products if p["price_azn"] <= hi]
    return sorted(products, key=lambda p: p["price_azn"])


def _wanted(t):
    """The product named in a free-text request: 'Salam, mənə iphone18 lazımdı' -> 'iphone 18'."""
    t = re.sub(r"(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])", " ", t)  # iphone18 -> iphone 18
    return " ".join(w for w in re.findall(r"\w+", t) if w not in _FILLER)


def _missing_model(t, found):
    """'iphone18' when the list has iPhone 13 but no 18: the model number the user asked for."""
    m = re.search(r"([^\W\d_]{3,})\s?(\d{1,3})(?![\d.,])(?!\s*(?:azn|manat|ман|gb|tb|%))", t)
    if not m or nlp.parse_count(t[m.start():m.end()]):
        return None
    names = [fold(p["name"]["en"]) for p in found]
    if any(m.group(1)[:4] in n for n in names) and not any(re.search(rf"\b{m.group(2)}\b", n) for n in names):
        return f"{m.group(1)} {m.group(2)}"
    return None


def _not_found(t, repo, lang):
    wanted = _wanted(t)
    groups = ", ".join(sorted({p["category"] for p in repo.all()}))
    if not wanted:
        return None
    return tr(lang, f"Sorry, '{wanted}' is not in our catalogue. We have: {groups}.",
              f"Təəssüf, '{wanted}' kataloqumuzda yoxdur. Bizdə olanlar: {groups}.",
              f"К сожалению, «{wanted}» нет в нашем каталоге. Есть: {groups}.")


def _stock(p, lang):
    if p["stock"] == 0:
        return tr(lang, "out of stock", "stokda yoxdur", "нет в наличии")
    return tr(lang, f"in stock: {p['stock']}", f"stokda: {p['stock']} ədəd", f"в наличии: {p['stock']} шт.")


def _facts(p, lang):
    color = f"{p['color']} · " if p["color"] else ""  # the live catalogue has no colour field
    return f"{money(p['price_azn'])} · ★{p['rating']} · {color}{_stock(p, lang)}"


def _line(i, p, lang):
    return f"{i}. {p['name'][lang]} — {p['brand']} · {_facts(p, lang)}"


def _lines(items, lang):
    text = "\n".join(_line(i, p, lang) for i, p in enumerate(items[:LIMIT], 1))
    if len(items) > LIMIT:
        more = len(items) - LIMIT
        text += "\n" + tr(lang, f"…and {more} more. Add a brand, colour or price to narrow it down.",
                          f"…və daha {more} məhsul. Marka, rəng və ya qiymət yazın ki, daraldım.",
                          f"…и ещё {more}. Уточните бренд, цвет или цену.")
    return text


def _details(p, lang):
    return f"{p['name'][lang]} — {p['brand']} ({p['category']})\n{_facts(p, lang)}\n{p['description']}"


def _cart(s, repo):
    lang, cart = s["lang"], s["shopping"]["cart"]
    if not cart:
        return tr(lang, "Your cart is empty.", "Səbətiniz boşdur.", "Корзина пуста.")
    lines, total = [], 0
    for pid, qty in cart.items():
        p = repo.get(pid)
        total += p["price_azn"] * qty
        lines.append(f"• {p['name'][lang]} × {qty} — {money(p['price_azn'] * qty)}")
    lines.append(tr(lang, f"Total: {money(total)}", f"Cəmi: {money(total)}", f"Итого: {money(total)}"))
    return tr(lang, "Your cart:", "Səbətiniz:", "Ваша корзина:") + "\n" + "\n".join(lines)


def handle(t, s, repo):
    lang, st = s["lang"], s["shopping"]
    shown = [repo.get(i) for i in st["results"]]
    found = _search(t, repo)
    ref = nlp.pick(t, shown, name=lambda p: " ".join(p["name"].values())) if found is None else None
    if ref:
        st["selected"] = ref["id"]
    selected = repo.get(st["selected"]) if st["selected"] else None
    target = ref or (found[0] if found and len(found) == 1 else None)

    if find(t, REMOVE):
        cart = st["cart"]
        target = target or (repo.get(next(iter(cart))) if len(cart) == 1 else None)
        if target is None or target["id"] not in cart:
            return tr(lang, "Which item should I remove?", "Hansı məhsulu silim?", "Какой товар удалить?") \
                + "\n" + _cart(s, repo)
        del cart[target["id"]]
        return tr(lang, f"Removed {target['name'][lang]}.", f"{target['name'][lang]} silindi.",
                  f"{target['name'][lang]} удалён.") + "\n" + _cart(s, repo)
    if find(t, ADD):
        target = target or selected
        if target is None:
            return tr(lang, "Which product should I add? For example: 'add the first one'.",
                      "Hansı məhsulu əlavə edim? Məsələn: 'birincini əlavə et'.",
                      "Какой товар добавить? Например: «добавь первый».")
        digit = re.search(r"(?<![\w.,:])([1-9])(?![\w.,:])", t)  # "add 2 board games"
        qty = nlp.parse_count(t) or (int(digit.group(1)) if digit else 1)
        if target["stock"] < st["cart"].get(target["id"], 0) + qty:
            return tr(lang, f"Sorry, only {target['stock']} of {target['name'][lang]} in stock.",
                      f"Təəssüf, {target['name'][lang]} stokda cəmi {target['stock']} ədəddir.",
                      f"К сожалению, в наличии только {target['stock']} шт. {target['name'][lang]}.")
        st["cart"][target["id"]] = st["cart"].get(target["id"], 0) + qty
        st["selected"] = target["id"]
        return tr(lang, f"Added {target['name'][lang]} × {qty}.", f"{target['name'][lang]} × {qty} əlavə edildi.",
                  f"Добавлено: {target['name'][lang]} × {qty}.") + "\n" + _cart(s, repo)
    if find(t, CART):
        return _cart(s, repo)
    if find(t, COMPARE):
        chosen = nlp.pick_many(t, shown)
        items = found if found and len(found) >= 2 else (chosen if len(chosen) >= 2 else shown)
        if len(items) < 2:
            return tr(lang, "Which products should I compare?", "Hansı məhsulları müqayisə edim?",
                      "Какие товары сравнить?")
        best = max(items, key=lambda p: p["rating"])
        cheapest = min(items, key=lambda p: p["price_azn"])
        items = items[:LIMIT]
        return "\n".join([_line(i, p, lang) for i, p in enumerate(items, 1)] + [
            tr(lang, f"Cheapest: {cheapest['name'][lang]} · best rated: {best['name'][lang]}",
               f"Ən ucuz: {cheapest['name'][lang]} · ən yüksək reytinq: {best['name'][lang]}",
               f"Дешевле всего: {cheapest['name'][lang]} · лучший рейтинг: {best['name'][lang]}")])
    if found is None and not (ref or selected or shown) and hasattr(repo, "search_text") and _wanted(t):
        found = repo.search_text(_wanted(t)) or None  # free text no catalogue word matched: ask the API
    if found is not None:
        st["results"] = [p["id"] for p in found[:LIMIT]]
        st["selected"] = found[0]["id"] if len(found) == 1 else None
        if not found:
            return tr(lang, "Sorry, no products match that.", "Təəssüf, uyğun məhsul tapılmadı.",
                      "К сожалению, подходящих товаров нет.")
        model = _missing_model(t, found)
        if model:  # the model's own line first ("iPhone 13 Pro" before "iPhone charger")
            found = sorted(found, key=lambda p: not fold(p["name"]["en"]).startswith(model.split()[0]))
            st["results"] = [p["id"] for p in found[:LIMIT]]
            return tr(lang, f"There is no '{model}' in our catalogue. The closest products:",
                      f"Kataloqumuzda '{model}' yoxdur. Ən yaxın məhsullar:",
                      f"«{model}» в нашем каталоге нет. Ближайшие товары:") + "\n" + _lines(found, lang)
        if len(found) == 1:
            return _details(found[0], lang)
        return tr(lang, "Here is what I found:", "Tapdıqlarım:", "Вот что я нашёл:") + "\n" + _lines(found, lang)
    if ref or selected:
        return _details(ref or selected, lang)
    if shown:  # "back to shopping": the earlier results are still there
        return tr(lang, "Your earlier results:", "Əvvəlki nəticələr:", "Ваши результаты:") + "\n" + _lines(shown, lang)
    missing = _not_found(t, repo, lang)
    if missing:
        return missing
    return tr(lang, "What are you looking for? For example: 'wireless headphones under 100 AZN'.",
              "Nə axtarırsınız? Məsələn: '100 AZN-dən ucuz simsiz qulaqlıq'.",
              "Что вы ищете? Например: «беспроводные наушники до 100 AZN».")
