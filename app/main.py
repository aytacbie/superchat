"""SuperChat web server: one chat endpoint plus the chat page."""
import logging
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import cinema, flights, nlp, router, shopping, sources, visual
from .repositories import DataSourceError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("superchat")
app = FastAPI(title="SuperChat")

repos = sources.build()
modules = {"flights": flights, "shopping": shopping, "cinema": cinema}
LIVE = any(repo.source != "mock dataset" for repo in repos.values())
ICONS = {"flights": "✈️", "shopping": "🛒", "cinema": "🎬"}
SERVICE = {"flights": "Aviasales", "shopping": "Shopping", "cinema": "CinemaPlus"}
sessions = {}
MAX_IMAGE_BYTES = 8 * 1024 * 1024
_keywords = {"at": 0.0, "words": {}}


def keywords():
    """Routing words per domain. Live catalogues change (new films every week, and the rest of
    the week loads in the background after start-up), so they are rebuilt every two minutes."""
    if not _keywords["words"] or (LIVE and time.monotonic() - _keywords["at"] > 120):
        words = {}
        for name, mod in modules.items():
            try:
                words[name] = mod.keywords(repos[name])
            except DataSourceError:
                words[name] = _keywords["words"].get(name) or mod.BASE_KEYWORDS
        _keywords.update(at=time.monotonic(), words=words)
    return _keywords["words"]


def unavailable(name, lang):
    svc = SERVICE[name]
    return nlp.tr(lang, f"Sorry, {svc} is not responding right now. Please try again in a minute.",
                  f"Bağışlayın, {svc} hazırda cavab vermir. Bir dəqiqədən sonra yenidən cəhd edin.",
                  f"Извините, {svc} сейчас не отвечает. Попробуйте через минуту.")


def new_session():
    return {"lang": "en", "active": None, "prefs": {},
            "flights": {"search": {}, "results": [], "selected": None},
            "shopping": {"results": [], "selected": None, "cart": {}},
            "cinema": {"results": [], "showtime": None, "focus": None}}


def respond(text, s):
    if LIVE:
        nlp.TODAY = nlp.baku_today()  # real data: "tonight" means today in Baku
    s["lang"] = nlp.detect_lang(text, s["lang"])
    t = nlp.fold(text)
    party = nlp.party_size(t)  # shared across domains: "we are 2 people" also sizes a cinema booking
    if party:
        s["prefs"]["party"] = party
    category, domains = router.classify(t, s, keywords())
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
        try:
            reply = modules[name].handle(t, s, repos[name])
        except DataSourceError as e:
            log.warning("%s source failed: %s", name, e)
            reply = unavailable(name, s["lang"])
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


@app.get("/api/health")
def health():
    """Which data source each domain uses, plus call, cache and error counters for live APIs."""
    out = {}
    for name, repo in repos.items():
        out[name] = {"source": repo.source}
        for attr in ("api", "data"):
            client = getattr(repo, attr, None)
            if client is not None:
                out[name][client.name] = client.status()
    return {"today": nlp.TODAY.isoformat(), "domains": out}


@app.get("/")
def index():
    return FileResponse(Path(__file__).resolve().parent.parent / "static" / "index.html")
