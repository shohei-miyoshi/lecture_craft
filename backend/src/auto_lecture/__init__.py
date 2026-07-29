# src/auto_lecture/__init__.py

"""
auto_lecture パッケージの公開 API を集約。
外部からはここを import するだけで、主要機能にアクセスできる。
"""

from .config import ModelConfig, TTSConfig
from .paths import ProjectPaths, build_paths
from .gpt_client import create_client
from .gpt_utils import ask_gpt, encode_image, image_content, create_user_message
from .style_axes import resolve_level_detail, LEVEL_TEXTS, DETAIL_TEXTS

__all__ = [
    # --- Config ---
    "ModelConfig",
    "TTSConfig",

    # --- Paths ---
    "ProjectPaths",
    "build_paths",

    # --- GPT Client / Utils ---
    "create_client",
    "ask_gpt",
    "encode_image",
    "image_content",
    "create_user_message",

    # --- Style Axes ---
    "resolve_level_detail",
    "LEVEL_TEXTS",
    "DETAIL_TEXTS",
]
