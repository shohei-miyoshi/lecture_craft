# src/auto_lecture/config.py
import os
from pathlib import Path
from dataclasses import dataclass

# ============================================================
#  API / モデル設定
# ============================================================

# --- GPT モデル ---
def _env_str(name: str, default: str, legacy_name: str | None = None) -> str:
    for env_name in (name, legacy_name):
        if not env_name:
            continue
        value = os.getenv(env_name)
        if value is not None and value.strip():
            return value.strip()
    return default


def _env_int(name: str, default: int, legacy_name: str | None = None) -> int:
    for env_name in (name, legacy_name):
        if not env_name:
            continue
        value = os.getenv(env_name)
        if value is None or not str(value).strip():
            continue
        try:
            return int(value)
        except Exception:
            continue
    return default


# ナレーション生成
API_MODEL_EXPLANATION = _env_str("LECTURE_CRAFT_MODEL_EXPLANATION", "gpt-5", "KENKYU_MODEL_EXPLANATION")
API_MODEL_EXPLANATION_TEMPERATURE = 1.0

# 各ステップごとの上書き設定
API_MODEL_DECK_SCAN = _env_str("LECTURE_CRAFT_MODEL_DECK_SCAN", API_MODEL_EXPLANATION, "KENKYU_MODEL_DECK_SCAN")
API_MODEL_AUDIO_MATERIAL = _env_str("LECTURE_CRAFT_MODEL_AUDIO_MATERIAL", API_MODEL_EXPLANATION, "KENKYU_MODEL_AUDIO_MATERIAL")
API_MODEL_AUDIO_OUTLINE = _env_str("LECTURE_CRAFT_MODEL_AUDIO_OUTLINE", API_MODEL_EXPLANATION, "KENKYU_MODEL_AUDIO_OUTLINE")
API_MODEL_AUDIO_NARRATION = _env_str("LECTURE_CRAFT_MODEL_AUDIO_NARRATION", API_MODEL_EXPLANATION, "KENKYU_MODEL_AUDIO_NARRATION")
API_MODEL_AUDIO_STITCH = _env_str("LECTURE_CRAFT_MODEL_AUDIO_STITCH", API_MODEL_EXPLANATION, "KENKYU_MODEL_AUDIO_STITCH")

# アニメーション割り当て
API_MODEL_ANIMATION = _env_str("LECTURE_CRAFT_MODEL_ANIMATION", "gpt-5", "KENKYU_MODEL_ANIMATION")
API_MODEL_ANIMATION_TEMPERATURE = 1.0

# --- TTS ---
API_TTS_MODEL = "gpt-4o-mini-tts"  # "tts-1" でも可
API_TTS_VOICE = "alloy"
API_TTS_VOICE_SPEED = 1.0

# API キーはファイルではなく環境変数から受け取る
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

# ローカルデバッグ時の秘密情報置き場
LOCAL_CONFIG_DIR = Path.home() / ".config" / "lecture_craft"
LEGACY_LOCAL_CONFIG_DIR = Path.home() / ".config" / "kenkyu"
LOCAL_OPENAI_API_KEY_FILES = (
    LOCAL_CONFIG_DIR / "openai_api_key",
    LOCAL_CONFIG_DIR / "openai_api_key.txt",
    LOCAL_CONFIG_DIR / "apikey.txt",
    LEGACY_LOCAL_CONFIG_DIR / "openai_api_key",
    LEGACY_LOCAL_CONFIG_DIR / "openai_api_key.txt",
    LEGACY_LOCAL_CONFIG_DIR / "apikey.txt",
)

# 互換のため残すが、gpt_client ではファイル読み込みを行わない
API_KEY_PATH = Path("apikey.txt")

# ============================================================
#  教材データの場所
# ============================================================

# teachingmaterial/ 内に PDF と img/ が置かれている
DEFAULT_MATERIAL_ROOT = Path("./teachingmaterial")

# teachingmaterial/img/<PDF名>/ に PDF から変換した PNG を入れる
IMG_DIR_NAME = "img"

# ============================================================
#  出力ルート（paths.py の build_paths() が参照）
# ============================================================

# 出力はすべて ./outputs/ 以下
OUTPUTS_ROOT = Path("./outputs")

# LP_output は「教材ごとに共通」
# outputs/LP_output/<PDF名>/
LP_OUTPUT_DIR_NAME = "LP_output"

# lecture_outputs のディレクトリ名
LECTURE_OUTPUTS_NAME = "lecture_outputs"

# lecture_outputs 以下
ALL_PAGE_SCAN_OUTPUT_DIR_NAME = "all_page_scan_outputs"
LECTURE_TEXTS_DIR_NAME = "lecture_texts"
TTS_OUTPUT_DIR_NAME = "tts_outputs"
ANIMATION_OUTPUT_DIR_NAME = "region_id_based_animation_outputs"
ADD_ANIMATION_OUTPUT_DIR_NAME = "add_animation_outputs"
LECTURE_OUTPUTS_FINAL_DIR_NAME = "output_final"

# ============================================================
#  実行制御
# ============================================================

AUDIO_MATERIAL_MAX_WORKERS = max(
    1,
    _env_int("LECTURE_CRAFT_AUDIO_MATERIAL_MAX_WORKERS", 3, "KENKYU_AUDIO_MATERIAL_MAX_WORKERS"),
)

# ============================================================
#  データクラス
# ============================================================

@dataclass
class TTSConfig:
    model: str = API_TTS_MODEL
    voice: str = API_TTS_VOICE
    speed: float = API_TTS_VOICE_SPEED


@dataclass
# GPT モデルの設定（共通）
class ModelConfig:
    explanation_model: str = API_MODEL_EXPLANATION
    explanation_temperature: float = API_MODEL_EXPLANATION_TEMPERATURE
    animation_model: str = API_MODEL_ANIMATION
    animation_temperature: float = API_MODEL_ANIMATION_TEMPERATURE
