# src/auto_lecture/config.py
from pathlib import Path
from dataclasses import dataclass

# ============================================================
#  API / モデル設定
# ============================================================

# --- GPT モデル ---
# ナレーション生成
API_MODEL_EXPLANATION = "gpt-5"
API_MODEL_EXPLANATION_TEMPERATURE = 1.0

# アニメーション割り当て
API_MODEL_ANIMATION = "gpt-5"
API_MODEL_ANIMATION_TEMPERATURE = 1.0

# --- TTS ---
API_TTS_MODEL = "gpt-4o-mini-tts"  # "tts-1" でも可
API_TTS_VOICE = "alloy"
API_TTS_VOICE_SPEED = 1.0

# API キーはファイルではなく環境変数から受け取る
OPENAI_API_KEY_ENV = "OPENAI_API_KEY"

# ローカルデバッグ時の秘密情報置き場
LOCAL_CONFIG_DIR = Path.home() / ".config" / "kenkyu"
LOCAL_OPENAI_API_KEY_FILES = (
    LOCAL_CONFIG_DIR / "openai_api_key",
    LOCAL_CONFIG_DIR / "openai_api_key.txt",
    LOCAL_CONFIG_DIR / "apikey.txt",
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
