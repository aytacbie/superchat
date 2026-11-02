"""Visual search (bonus): identify a catalogue product from a photo with CLIP, zero-shot.

The photo's CLIP embedding is compared with one text embedding per visual class
(data/visual_classes.json, built by scripts/build_visual_classes.py). A softmax over the
similarities gives a confidence. High confidence -> show the products; medium -> ask which
of the top guesses it is; low, or a class we do not sell -> say so and ask the user to describe it."""
import io
import json
import logging
import os
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

from . import shopping
from .nlp import tr

log = logging.getLogger("superchat")
ROOT = Path(__file__).resolve().parent.parent
MODEL_REPO = "Xenova/clip-vit-base-patch32"
MODEL_FILE = "onnx/vision_model_quantized.onnx"  # int8: ~90 MB, fits a 512 MB free instance
MODEL_PATH = ROOT / "models" / MODEL_FILE
CLASSES_PATH = ROOT / "data" / "visual_classes.json"
CONFIDENT = 0.60  # show the products
POSSIBLE = 0.20   # ask the user to confirm
# CLIP image preprocessing constants (224 px, OpenAI mean/std)
SIZE = 224
MEAN = np.array([0.48145466, 0.4578275, 0.40821073], dtype=np.float32)
STD = np.array([0.26862954, 0.26130258, 0.27577711], dtype=np.float32)

NAMES = {
    "headphones": ("headphones", "qulaqlıq", "наушники"),
    "earbuds": ("wireless earbuds", "simsiz qulaqcıq", "беспроводные вкладыши"),
    "laptop": ("a laptop", "noutbuk", "ноутбук"),
    "smartphone": ("a smartphone", "smartfon", "смартфон"),
    "smartwatch": ("a smartwatch", "ağıllı saat", "умные часы"),
    "speaker": ("a speaker", "dinamik", "колонка"),
    "running_shoes": ("running shoes", "qaçış ayaqqabısı", "беговые кроссовки"),
    "backpack": ("a backpack", "çanta", "рюкзак"),
    "coffee_machine": ("a coffee machine", "qəhvə maşını", "кофемашина"),
    "board_game": ("a board game", "stolüstü oyun", "настольная игра"),
}


class ImageError(Exception):
    """The upload is not an image we can read."""


class ModelUnavailable(Exception):
    pass


_session = None
_classes = None


def _load():
    global _session, _classes
    if _session is None:
        import onnxruntime as ort
        if not MODEL_PATH.exists():  # normally fetched at build time by scripts/download_model.py
            try:
                from huggingface_hub import hf_hub_download
                hf_hub_download(MODEL_REPO, MODEL_FILE, local_dir=ROOT / "models")
            except Exception as e:
                raise ModelUnavailable("vision model not available") from e
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("SUPERCHAT_THREADS", "1"))
        _session = ort.InferenceSession(str(MODEL_PATH), options, providers=["CPUExecutionProvider"])
        data = json.loads(CLASSES_PATH.read_text(encoding="utf-8"))["classes"]
        _classes = ([c["label"] for c in data], [c["products"] for c in data],
                    np.array([c["embedding"] for c in data], dtype=np.float32))
    return _session, _classes


def _pixels(image_bytes):
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise ImageError("not an image") from e
    w, h = img.size
    scale = SIZE / min(w, h)
    img = img.resize((max(SIZE, round(w * scale)), max(SIZE, round(h * scale))), Image.Resampling.BICUBIC)
    w, h = img.size
    left, top = (w - SIZE) // 2, (h - SIZE) // 2
    arr = (np.asarray(img.crop((left, top, left + SIZE, top + SIZE)), dtype=np.float32) / 255.0 - MEAN) / STD
    return arr.transpose(2, 0, 1)[None]


def classify(image_bytes):
    """[(label, product ids, probability)], most likely first."""
    session, (labels, products, text) = _load()
    emb = session.run(["image_embeds"], {"pixel_values": _pixels(image_bytes)})[0][0]
    emb /= np.linalg.norm(emb)
    logits = 100.0 * text @ emb  # CLIP's logit scale
    probs = np.exp(logits - logits.max())
    probs /= probs.sum()
    order = np.argsort(-probs)
    return [(labels[i], products[i], float(probs[i])) for i in order]


def _name(label, lang):
    en, az, ru = NAMES[label]
    return tr(lang, en, az, ru)


def handle_image(image_bytes, s, repo):
    lang, st = s["lang"], s["shopping"]
    ranked = classify(image_bytes)
    ours = [r for r in ranked if r[1]]
    best, second = ours[0], ours[1]
    top = ranked[0]
    pct = lambda p: f"{round(100 * p)}%"

    if best[2] >= CONFIDENT:
        # the mock catalogue lists product ids per class; a live catalogue matches by title words
        ids = repo.visual_matches(best[0]) if hasattr(repo, "visual_matches") else best[1]
        items = [p for p in map(repo.get, ids) if p][:shopping.LIMIT]
        if not items:
            name = _name(best[0], lang)
            return tr(lang, f"This looks like {name} (confidence {pct(best[2])}), but we have none in the catalogue.",
                      f"Bu, {name} kimi görünür (əminlik {pct(best[2])}), amma kataloqumuzda yoxdur.",
                      f"Похоже, это {name} (уверенность {pct(best[2])}), но в каталоге такого нет.")
        st["results"] = [p["id"] for p in items]
        st["selected"] = items[0]["id"] if len(items) == 1 else None
        name = _name(best[0], lang)
        header = tr(lang, f"This looks like {name} (confidence {pct(best[2])}). From our catalogue:",
                    f"Bu, {name} kimi görünür (əminlik {pct(best[2])}). Kataloqumuzda:",
                    f"Похоже, это {name} (уверенность {pct(best[2])}). В нашем каталоге:")
        return header + "\n" + "\n".join(shopping._line(i, p, lang) for i, p in enumerate(items, 1))

    if best[2] >= POSSIBLE and not (top is not best and top[2] >= CONFIDENT):
        a = _name(best[0], lang)
        live = hasattr(repo, "visual_matches")
        first = repo.visual_matches(best[0])[:shopping.LIMIT] if live else list(best[1])
        st["results"] = first
        st["selected"] = first[0] if len(first) == 1 else None
        if second[2] >= POSSIBLE / 2:
            b = _name(second[0], lang)
            st["results"] += repo.visual_matches(second[0])[:shopping.LIMIT] if live else list(second[1])
            st["selected"] = None
            return tr(lang, f"I'm not sure. Is it {a} ({pct(best[2])}) or {b} ({pct(second[2])})?",
                      f"Əmin deyiləm. Bu {a} ({pct(best[2])}), yoxsa {b} ({pct(second[2])})?",
                      f"Не уверен. Это {a} ({pct(best[2])}) или {b} ({pct(second[2])})?")
        return tr(lang, f"I'm not sure. Is it {a} ({pct(best[2])})?",
                  f"Əmin deyiləm: {a} ({pct(best[2])})? Düzdür?",
                  f"Не уверен. Это {a} ({pct(best[2])})?")

    guess = best[2] >= 0.10
    return tr(lang, "I couldn't match this photo to a product in our catalogue"
                    + (f" (closest: {_name(best[0], lang)}, {pct(best[2])})" if guess else "")
                    + ". Could you describe what you are looking for?",
              "Bu şəkli kataloqumuzdakı məhsulla uyğunlaşdıra bilmədim"
              + (f" (ən yaxın: {_name(best[0], lang)}, {pct(best[2])})" if guess else "")
              + ". Nə axtardığınızı yaza bilərsiniz?",
              "Не удалось сопоставить фото с товаром из каталога"
              + (f" (ближе всего: {_name(best[0], lang)}, {pct(best[2])})" if guess else "")
              + ". Опишите, что вы ищете?")
