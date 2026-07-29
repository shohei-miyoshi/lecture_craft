# scripts/run_lp.py
from __future__ import annotations

from pathlib import Path
import sys
import argparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from auto_lecture.paths import build_paths  # type: ignore
from auto_lecture.lp_processor import process_slides_with_lp  # type: ignore
from auto_lecture.config import DEFAULT_MATERIAL_ROOT  # type: ignore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--material", required=True, help="教材PDF名（例: パターン認識への誘い.pdf）")
    parser.add_argument("--material_root", default=str(DEFAULT_MATERIAL_ROOT))
    args = parser.parse_args()

    # LP単体実行なので create_lp_timestamp_dir=True
    paths = build_paths(
        teaching_material_file_name=args.material,
        material_root=Path(args.material_root),
        output_root_name=None,
        create_lp_timestamp_dir=True,
    )

    print("[run_lp] img_root:", paths.img_root)
    print("[run_lp] lp_dir  :", paths.lp_dir)

    process_slides_with_lp(paths)


if __name__ == "__main__":
    main()
