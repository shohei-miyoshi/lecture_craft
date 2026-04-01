# src/auto_lecture/gpt_utils.py
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI

from . import config


def ask_gpt(
    client: OpenAI,
    messages: List[Dict[str, Any]],
    modelname: str = config.API_MODEL_EXPLANATION,
    seed: int = 12345,
    temperature: float = config.API_MODEL_EXPLANATION_TEMPERATURE,
    top_p: Optional[float] = None,
    logit_bias: Optional[Dict[str, float]] = None,
    logprobs: bool = False,
    top_logprobs: Optional[int] = None,
    max_tokens: int = 1000,
    max_completion_tokens: Optional[int] = None,
    presence_penalty: float = 0.0,
    frequency_penalty: float = 0.0,
    RETRY: int = 3,
) -> List[Dict[str, Any]]:
    """
    GPT への問い合わせユーティリティ（chat.completions 用）。

    - messages は chat.completions 形式:
        {"role": "system"|"user"|"assistant",
         "content": [{"type": "text"|"image_url", ...}, ...]}
    - top_p や logprobs などは「指定されたときだけ」payload に入れる。
    """
    res: List[Dict[str, Any]] = []

    for _ in range(RETRY):
        success = True
        try:
            payload: Dict[str, Any] = {
                "model": modelname,
                "messages": messages,
                "temperature": temperature,
                "seed": seed,
                "presence_penalty": presence_penalty,
                "frequency_penalty": frequency_penalty,
                "max_completion_tokens": max_completion_tokens or max_tokens,
            }

            # 任意パラメータ（指定された場合だけ入れる）
            if logit_bias is not None:
                payload["logit_bias"] = logit_bias
            if top_p is not None:
                payload["top_p"] = top_p
            if logprobs:
                payload["logprobs"] = True
            if top_logprobs is not None:
                payload["top_logprobs"] = top_logprobs

            response = client.chat.completions.create(**payload)
            res_dict = dict(
                result=response.choices[0].message.content,
                response=response,
            )

        except Exception as e:
            print("[ask_gpt] Error:", e)
            res_dict = dict(error=str(e))
            time.sleep(6)
            success = False
        finally:
            res.append(res_dict)
            if success:
                break

    return res


# ===== 画像 → base64 → image_content =====

def encode_image(image_path: str | Path) -> str:
    image_path = Path(image_path)
    with image_path.open("rb") as image_file:
        return base64.b64encode(image_file.read()).decode("utf-8")


def image_content(image_path: str | Path) -> Dict[str, Any]:
    """
    chat.completions 用: type='image_url'
    """
    base64_image = encode_image(image_path)
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/png;base64,{base64_image}"},
    }


def create_user_message(text: str, img_paths: List[str | Path]) -> Dict[str, Any]:
    """
    ユーザーメッセージ（テキスト + 画像）を chat.completions 形式で組み立てる。
    - テキスト: type='text'
    - 画像   : type='image_url'
    """
    content: List[Dict[str, Any]] = [
        {"type": "text", "text": text}
    ]
    for p in img_paths:
        content.append(image_content(p))

    return {"role": "user", "content": content}
