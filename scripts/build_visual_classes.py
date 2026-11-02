"""Builds data/visual_classes.json: one CLIP text embedding per visual class.

The mock catalogue has no product photos, so visual search is zero-shot: an uploaded photo
is compared with text descriptions of what each product looks like. Classes without
products ("not_in_catalogue") let the model say a photo shows something we do not sell.

Dev-only. Needs: pip install onnxruntime tokenizers huggingface_hub numpy
Usage:  python scripts/build_visual_classes.py
"""
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
from huggingface_hub import hf_hub_download
from tokenizers import Tokenizer

REPO = "Xenova/clip-vit-base-patch32"
OUT = Path(__file__).resolve().parent.parent / "data" / "visual_classes.json"
TEMPLATES = ["a photo of {}.", "a product photo of {}.", "{} on a white background."]

# (label, product ids, descriptions)
CLASSES = [
    ("headphones", ["P001"], ["over-ear wireless headphones", "a pair of headphones"]),
    ("earbuds", ["P002"], ["wireless earbuds", "wireless earbuds with a charging case", "in-ear earphones"]),
    ("laptop", ["P003", "P004"], ["a laptop computer", "an open notebook computer"]),
    ("smartphone", ["P005", "P006"], ["a smartphone", "a mobile phone"]),
    ("smartwatch", ["P007"], ["a smartwatch", "a fitness smart watch with a digital screen"]),
    ("speaker", ["P008"], ["a portable bluetooth speaker", "a smart speaker"]),
    ("running_shoes", ["P009"], ["running shoes", "sneakers", "sports shoes"]),
    ("backpack", ["P010"], ["a backpack", "a rucksack"]),
    ("coffee_machine", ["P011"], ["an espresso coffee machine", "a coffee maker"]),
    ("board_game", ["P012"], ["a board game", "a board game box with cards and pieces"]),
    # Not in the catalogue
    ("analog_watch", [], ["a classic analog wristwatch", "a luxury wrist watch with hands"]),
    ("food", [], ["food", "fruit", "vegetables", "a grocery item", "meat", "a jar of food", "a packaged food product"]),
    ("furniture", [], ["furniture", "a sofa", "a bed", "a chair", "a table", "a bathroom sink"]),
    ("kitchen_appliance", [], ["a blender", "a kettle", "an electric stove", "a microwave oven", "a toaster"]),
    ("tablet", [], ["a tablet computer", "an ipad"]),
    ("other_footwear", [], ["high heel shoes", "women's shoes", "slippers", "sandals", "boots"]),
    ("vehicle", [], ["a car", "a motorcycle", "a vehicle"]),
    ("cosmetics", [], ["cosmetics", "makeup", "a perfume bottle", "lipstick"]),
    ("kitchenware", [], ["a kitchen utensil", "cookware", "a pan", "a knife", "a cup", "a mug", "a grater"]),
    ("clothing", [], ["clothing", "a shirt", "a dress", "a jacket"]),
    ("sports_gear", [], ["a ball", "sports equipment"]),
    ("phone_accessory", [], ["a phone charger", "a phone case", "a cable"]),
    ("other", [], ["a person", "an animal", "a landscape", "a building", "a screenshot of text"]),
    ("fashion_accessory", [], ["sunglasses", "jewelry", "a handbag"]),
]


def main():
    tokenizer = Tokenizer.from_file(hf_hub_download(REPO, "tokenizer.json"))
    session = ort.InferenceSession(hf_hub_download(REPO, "onnx/text_model.onnx"))
    out = []
    for label, products, descriptions in CLASSES:
        texts = [t.format(d) for d in descriptions for t in TEMPLATES]
        # One prompt per run: CLIP pads with its end token, so batching would need care.
        vecs = np.vstack([session.run(None, {"input_ids": np.array([tokenizer.encode(x).ids], dtype=np.int64)})[0]
                          for x in texts])
        vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
        mean = vecs.mean(axis=0)
        mean /= np.linalg.norm(mean)
        out.append({"label": label, "products": products, "embedding": [round(float(v), 6) for v in mean]})
    OUT.write_text(json.dumps({"model": REPO, "classes": out}), encoding="utf-8")
    print(f"wrote {len(out)} classes to {OUT}")


if __name__ == "__main__":
    main()
