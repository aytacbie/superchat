"""Fetches the int8 CLIP vision model into models/ (run once at build time).

Usage: python scripts/download_model.py
"""
from pathlib import Path

from huggingface_hub import hf_hub_download

ROOT = Path(__file__).resolve().parent.parent

if __name__ == "__main__":
    path = hf_hub_download("Xenova/clip-vit-base-patch32", "onnx/vision_model_quantized.onnx", local_dir=ROOT / "models")
    print("model ready:", path)
