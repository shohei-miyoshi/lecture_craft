# src/auto_lecture/gpt_client.py
import os
from pathlib import Path
from openai import OpenAI

from . import config


def _looks_like_openai_api_key(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate or not candidate.isascii():
        return False
    return candidate.startswith("sk-")


def _load_api_key_from_local_config_dir() -> str:
    for path in config.LOCAL_OPENAI_API_KEY_FILES:
        if path.exists():
            candidate = path.read_text(encoding="utf-8").strip()
            if _looks_like_openai_api_key(candidate):
                return candidate
    return ""


def create_client(api_key_path: Path | str = config.API_KEY_PATH) -> OpenAI:
    """
    OpenAI クライアントを返す。

    セキュリティ方針:
    - 本番/実運用は `OPENAI_API_KEY` 環境変数を優先
    - ローカルデバッグ時のみ `~/.config/lecture_craft/openai_api_key` または
      `~/.config/lecture_craft/openai_api_key.txt` を優先フォールバックとして使う
    - 互換のため `~/.config/kenkyu/...` も引き続き読む
    - ワークスペース内ファイルは読まない
    - `api_key_path` 引数は互換のため受け取るが使用しない
    """
    _ = api_key_path
    api_key = os.getenv(config.OPENAI_API_KEY_ENV, "").strip()
    invalid_env_value = bool(api_key) and not _looks_like_openai_api_key(api_key)
    if invalid_env_value:
        api_key = ""
    if not api_key:
        api_key = _load_api_key_from_local_config_dir()
    if not api_key:
        if invalid_env_value:
            raise RuntimeError(
                f"{config.OPENAI_API_KEY_ENV} に設定されている値が OpenAI API キーの形式ではありません。"
                "日本語のプレースホルダではなく、実際の API キーを設定するか、"
                f"{config.OPENAI_API_KEY_ENV} を unset してください。"
            )
        raise RuntimeError(
            f"{config.OPENAI_API_KEY_ENV} が設定されておらず、"
            f"{config.LOCAL_CONFIG_DIR} にも API キーが見つかりません。"
            "本番は環境変数、ローカルデバッグでは ~/.config/lecture_craft 配下のキーを使ってください。"
        )

    client = OpenAI(api_key=api_key)
    return client
