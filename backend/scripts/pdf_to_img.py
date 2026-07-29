# scripts/pdf_to_img.py
# -*- coding: utf-8 -*-

from pathlib import Path
import sys

# ============================
# プロジェクトルート & src を sys.path に追加
# ============================
# このファイル: auto_lecture/scripts/pdf_to_img.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]   # .../auto_lecture
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# これで src/auto_lecture が import できる
from auto_lecture.utils.pdf_utils import pdf_to_images

# ============================
# PDF 名だけ指定すれば変換
# ============================
teaching_material_file_name = "パターン認識への誘い.pdf"

# teachingmaterial の場所はプロジェクトルート基準で決める
material_root = PROJECT_ROOT / "teachingmaterial"
pdf_path = material_root / "pdf" / teaching_material_file_name
save_dir = material_root / "img" / teaching_material_file_name


if __name__ == "__main__":
    print("[INFO] Converting PDF → PNG ...")
    print(f"PDF:  {pdf_path}")
    print(f"OUT:  {save_dir}")

    pdf_to_images(str(pdf_path), str(save_dir), dpi=100)

    print("[DONE] PDF → PNG 完了")
