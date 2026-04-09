# ABOUTME: Image embedding via SigLIP (local) or Vertex AI multimodal (cloud).
# ABOUTME: Produces embeddings in a shared vision-language space for cross-modal search.

from __future__ import annotations
from pathlib import Path
import numpy as np

# Lazy-loaded model cache — avoids reloading ~400MB model per call
_siglip_model = None
_siglip_processor = None


def _get_siglip():
    """Lazy-load SigLIP model and processor."""
    global _siglip_model, _siglip_processor
    if _siglip_model is None:
        from transformers import AutoProcessor, AutoModel
        _siglip_model = AutoModel.from_pretrained("google/siglip-base-patch16-224")
        _siglip_processor = AutoProcessor.from_pretrained("google/siglip-base-patch16-224")
    return _siglip_model, _siglip_processor


def embed_image(path: Path) -> np.ndarray | None:
    """Embed an image using SigLIP. Returns normalized embedding or None if unavailable."""
    try:
        import torch
        from PIL import Image

        model, processor = _get_siglip()
        image = Image.open(path).convert("RGB")
        inputs = processor(images=image, return_tensors="pt")
        with torch.no_grad():
            outputs = model.vision_model(**{k: v for k, v in inputs.items() if k != "input_ids" and k != "attention_mask"})
        embedding = outputs.pooler_output[0].numpy()
        return embedding / np.linalg.norm(embedding)
    except (ImportError, Exception):
        return None


def embed_image_text(text: str) -> np.ndarray | None:
    """Embed text using SigLIP text encoder — same latent space as image embeddings.

    Used for: embedding image descriptions, entity names, and text queries
    into the image index for cross-modal retrieval.
    """
    try:
        import torch

        model, processor = _get_siglip()
        inputs = processor(text=[text], return_tensors="pt", padding=True, truncation=True)
        text_inputs = {k: v for k, v in inputs.items() if k != "pixel_values"}
        with torch.no_grad():
            outputs = model.text_model(**text_inputs)
        embedding = outputs.pooler_output[0].numpy()
        return embedding / np.linalg.norm(embedding)
    except (ImportError, Exception):
        return None


def embed_image_batch(paths: list[Path]) -> list[np.ndarray | None]:
    """Embed multiple images in a batch."""
    try:
        import torch
        from PIL import Image

        model, processor = _get_siglip()
        images = [Image.open(p).convert("RGB") for p in paths]
        inputs = processor(images=images, return_tensors="pt")
        with torch.no_grad():
            outputs = model.get_image_features(**inputs)
        embeddings = outputs.numpy()
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return list(embeddings / norms)
    except ImportError:
        return [None] * len(paths)


def embed_text_batch(texts: list[str]) -> list[np.ndarray | None]:
    """Embed multiple texts via SigLIP text encoder in a batch."""
    try:
        import torch

        model, processor = _get_siglip()
        inputs = processor(text=texts, return_tensors="pt", padding=True, truncation=True)
        with torch.no_grad():
            outputs = model.get_text_features(**inputs)
        embeddings = outputs.numpy()
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1
        return list(embeddings / norms)
    except ImportError:
        return [None] * len(texts)
