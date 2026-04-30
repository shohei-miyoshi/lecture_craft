# src/auto_lecture/lp_processor.py
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
import json
import re
import threading
from typing import List, Dict, Any

import layoutparser as lp
import cv2
from PIL import Image, ImageDraw, ImageFont

from .paths import ProjectPaths

# ----------------------------------------------------------------------
# Pillow>=10 getsize 対応（元コードと同じ処理）
# ----------------------------------------------------------------------
if not hasattr(ImageFont.FreeTypeFont, "getsize"):
    def getsize(self, text):
        bbox = self.getbbox(text)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]
    ImageFont.FreeTypeFont.getsize = getsize


# ----------------------------------------------------------------------
# モデル構築（元コード準拠だがパスはProjectPathsに合わせる）
# ----------------------------------------------------------------------
_LP_MODEL_LOCK = threading.Lock()


@lru_cache(maxsize=2)
def _build_lp_model_cached(config_path_str: str, model_path_str: str):
    config_path = Path(config_path_str)
    model_path = Path(model_path_str)
    if not config_path.exists():
        raise FileNotFoundError(
            f"LayoutParser config not found: {config_path}. "
            "Run: bash scripts/setup_backend_full.sh"
        )
    if not model_path.exists():
        raise FileNotFoundError(
            f"LayoutParser model not found: {model_path}. "
            "Run: bash scripts/setup_backend_full.sh"
        )

    return lp.Detectron2LayoutModel(
        config_path=str(config_path),
        model_path=str(model_path),
        label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"},
        extra_config=[
            "MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.5,
            "MODEL.ROI_HEADS.NMS_THRESH_TEST", 0.5,
            "INPUT.MIN_SIZE_TEST", 800,
            "INPUT.MAX_SIZE_TEST", 1333
        ]
    )


def build_lp_model(project_root: Path):
    config_path = (project_root / "models" / "config.yml").resolve()
    model_path = (project_root / "models" / "model_final.pth").resolve()
    with _LP_MODEL_LOCK:
        return _build_lp_model_cached(str(config_path), str(model_path))


# ----------------------------------------------------------------------
# page_001 / 001 / slide_001 → "001"
# ----------------------------------------------------------------------
_PAGE_RE = re.compile(r"(?:page_)?(\d{3})", re.IGNORECASE)

def slide_str_from_stem(stem: str) -> str:
    m = _PAGE_RE.search(stem)
    if m:
        return m.group(1)

    digits = re.sub(r"\D+", "", stem)
    if digits:
        return f"{int(digits):03d}"

    return stem.zfill(3)


# ----------------------------------------------------------------------
# 元コード完全再現版 LP Processor
# ----------------------------------------------------------------------
def process_slides_with_lp(paths: ProjectPaths):
    """
    teachingmaterial/img/<PDF名>/*.png を読み、
    outputs/LP_output/<PDF名>/<timestamp>/ に以下を保存：
      - result_001.json
      - result_001.png（全体可視化）
      - region_page_001_0_Text.png（領域ごと：枠つき・ラベルつき）
    """
    img_dir: Path = paths.img_root
    out_dir: Path = paths.lp_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if not img_dir.exists():
        raise FileNotFoundError(f"img_root not found: {img_dir}")

    pngs = sorted(img_dir.glob("*.png"))
    if not pngs:
        raise RuntimeError(f"No PNG images in {img_dir}")

    # フォント（元コードと同じ）
    try:
        font_big = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", size=48)
        font_small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", size=28)
    except Exception:
        font_big = ImageFont.load_default()
        font_small = ImageFont.load_default()

    model = build_lp_model(paths.project_root)

    for png_path in pngs:
        stem = png_path.stem
        slide_str = slide_str_from_stem(stem)

        # ------------------------------------------------------------------
        # 1) 画像読込（BGR）
        # ------------------------------------------------------------------
        image = cv2.imread(str(png_path))
        if image is None:
            print(f"⚠️ 読み込み失敗: {png_path}")
            continue

        # ------------------------------------------------------------------
        # 2) LayoutParser で推論
        # ------------------------------------------------------------------
        layout = model.detect(image)

        # ------------------------------------------------------------------
        # 3) JSON 出力（元コードと全く同じ形式）
        # ------------------------------------------------------------------
        json_out = out_dir / f"result_{slide_str}.json"
        elements: List[Dict[str, Any]] = [
            {
                "id": idx,
                "type": ele.type,
                "coordinates": [
                    int(ele.block.x_1),
                    int(ele.block.y_1),
                    int(ele.block.x_2),
                    int(ele.block.y_2),
                ],
                "score": float(ele.score),
            }
            for idx, ele in enumerate(layout)
        ]
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(elements, f, ensure_ascii=False, indent=2)
        print(f"📝 JSON: {json_out}")

        # ------------------------------------------------------------------
        # 4) 全体可視化（result_XXX.png）
        # ------------------------------------------------------------------
        pil_full = Image.open(png_path).convert("RGB")
        draw_full = ImageDraw.Draw(pil_full)

        for idx, ele in enumerate(layout):
            x1, y1 = int(ele.block.x_1), int(ele.block.y_1)
            x2, y2 = int(ele.block.x_2), int(ele.block.y_2)

            draw_full.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=3)

            label = str(idx)
            bbox = font_big.getbbox(label)
            th = bbox[3] - bbox[1]

            label_x = x1
            label_y = y1 - th - 4
            if label_y < 0:
                label_y = y1 + 4

            draw_full.text((label_x, label_y), label, fill=(255, 0, 0), font=font_big)

        full_png = out_dir / f"result_{slide_str}.png"
        pil_full.save(full_png)
        print(f"🖼 全体PNG: {full_png}")

        # ------------------------------------------------------------------
        # 5) 個別領域：元画像に枠とラベルを描いて保存（元コード完全一致）
        # ------------------------------------------------------------------
        for idx, ele in enumerate(layout):
            pil_orig = Image.open(png_path).convert("RGB")
            draw = ImageDraw.Draw(pil_orig)

            x1, y1 = int(ele.block.x_1), int(ele.block.y_1)
            x2, y2 = int(ele.block.x_2), int(ele.block.y_2)

            draw.rectangle([x1, y1, x2, y2], outline=(255, 0, 0), width=3)

            label = str(idx)
            bbox = font_small.getbbox(label)
            th = bbox[3] - bbox[1]

            label_x = x1
            label_y = y1 - th - 4
            if label_y < 0:
                label_y = y1 + 4

            draw.text((label_x, label_y), label, fill=(255, 0, 0), font=font_small)

            # 元コードと同じファイル名規則
            region_path = out_dir / f"region_{stem}_{idx}_{ele.type}.png"
            pil_orig.save(region_path)
            print(f"  🖼 個別領域: {region_path}")
