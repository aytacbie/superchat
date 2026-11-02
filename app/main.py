"""SuperChat web server: one chat endpoint plus the chat page."""
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import cinema, flights, nlp, router, shopping, visual
from .repositories import FlightRepository, ProductRepository, ShowtimeRepository

log = logging.getLogger("superchat")
app = FastAPI(title="SuperChat")

repos = {"flights": FlightRepository(), "shopping": ProductRepository(), "cinema": ShowtimeRepository()}
modules = {"flights": flights, "shopping": shopping, "cinema": cinema}
keywords = {name: mod.keywords(repos[name]) for name, mod in modules.items()}
ICONS = {"flights": "✈️", "shopping": "🛒", "cinema": "🎬"}
sessions = {}
MAX_IMAGE_BYTES = 8 * 1024 * 1024


def new_session():
    return {"lang": "en", "active": None, "prefs": {},
            "flights": {"search": {}, "results": [], "selected": None},
            "shopping": {"results": [], "selected": None, "cart": {}},
            "cinema": {"results": [], "showtime": None, "focus": None}}


def respond(text, s):
    s["lang"] = nlp.detect_lang(text, s["lang"])
    t = nlp.fold(text)
    party = nlp.party_size(t)  # shared across domains: "we are 2 people" also sizes a cinema booking
    if party:
        s["prefs"]["party"] = party
    category, domains = router.classify(t, s, keywords)
    pending = s.pop("pending", None)
    if category == "ambiguous":
        if len(router.bookable(s)) > 1:
            s["pending"] = t  # remember "book two seats" until the user says flight or cinema
        return router.clarify(t, s), category
    if pending and len(domains) == 1 and domains[0] in ("flights", "cinema"):
        t = pending + " " + t
    if category == "greeting":
        return router.help_text(t, s["lang"]), category
    if not domains:
        return router.out_of_scope(s["lang"]), category
    parts = []
    for name in domains:
        reply = modules[name].handle(t, s, repos[name])
        parts.append(f"{ICONS[name]} {reply}" if len(domains) > 1 else reply)
    s["active"] = domains[-1]
    return "\n\n".join(parts), category


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


@app.post("/api/chat")
def chat(body: ChatIn):
    sid = body.session_id or uuid.uuid4().hex
    s = sessions.setdefault(sid, new_session())
    try:
        reply, category = respond(body.message.strip()[:500], s)
    except Exception:
        log.exception("chat failed")
        reply, category = nlp.tr(s["lang"], "Sorry, something went wrong. Please try again.",
                                 "Bağışlayın, xəta baş verdi. Yenidən cəhd edin.",
                                 "Извините, произошла ошибка. Попробуйте ещё раз."), "error"
    return {"session_id": sid, "reply": reply, "category": category, "domain": s["active"], "lang": s["lang"]}


@app.post("/api/image")
async def image(file: UploadFile = File(...), session_id: str | None = Form(None), message: str = Form("")):
    """Visual search: a product photo goes to the Shopping module. Text sent with the photo
    ("is it in stock?", "add it to my cart") is answered right after, against the photo's result."""
    sid = session_id or uuid.uuid4().hex
    s = sessions.setdefault(sid, new_session())
    message = message.strip()[:500]
    if message:
        s["lang"] = nlp.detect_lang(message, s["lang"])
    lang = s["lang"]
    data = await file.read(MAX_IMAGE_BYTES + 1)
    category = "shopping"
    try:
        if len(data) > MAX_IMAGE_BYTES:
            raise visual.ImageError("too large")
        reply = visual.handle_image(data, s, repos["shopping"])
        s["active"] = "shopping"
        if message:
            text_reply, text_category = respond(message, s)
            reply += "\n\n" + text_reply
            if text_category not in ("shopping", "follow_up"):  # the photo itself is always shopping
                category = text_category
    except visual.ImageError:
        reply, category = nlp.tr(lang, "Sorry, I could not read that file. Please send a JPG or PNG photo up to 8 MB.",
                                 "Bağışlayın, faylı oxuya bilmədim. 8 MB-a qədər JPG və ya PNG şəkil göndərin.",
                                 "Не удалось прочитать файл. Отправьте фото JPG или PNG до 8 МБ."), "error"
    except Exception:
        log.exception("visual search failed")
        reply, category = nlp.tr(lang, "Sorry, photo search is unavailable right now. You can describe the product instead.",
                                 "Bağışlayın, şəkillə axtarış hazırda işləmir. Məhsulu sözlə yaza bilərsiniz.",
                                 "Поиск по фото сейчас недоступен. Опишите товар словами."), "error"
    return {"session_id": sid, "reply": reply, "category": category, "domain": s["active"], "lang": s["lang"]}


@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent.parent / "static" / "index.html")
