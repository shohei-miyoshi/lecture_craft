# scripts/run_allLD_lecture.py
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List

# ----------------------------
# run_all.py の場所
# ----------------------------
THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]
RUN_ALL = PROJECT_ROOT / "scripts" / "run_all.py"

# ----------------------------
# style_axes から有効キーを取る（choicesに使う）
# ----------------------------
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from auto_lecture.style_axes import LEVEL_TEXTS, DETAIL_TEXTS  # type: ignore

ALL_LEVELS = list(LEVEL_TEXTS.keys())
ALL_DETAILS = list(DETAIL_TEXTS.keys())


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "アニメーション付き講義動画生成（scripts/run_all.py）を、"
            "複数スタイル(LxDy)で一括実行します。"
        )
    )
    p.add_argument("--material", "-m", required=True, help="教材PDF名（例: パターン認識への誘い.pdf）")
    p.add_argument("--material_root", default=None, help="teachingmaterial のルート（省略時は run_all.py のデフォルト）")

    p.add_argument("--levels", nargs="+", choices=ALL_LEVELS, default=ALL_LEVELS,
                   help=f"対象レベル（省略時は全レベル）: {' '.join(ALL_LEVELS)}")
    p.add_argument("--details", nargs="+", choices=ALL_DETAILS, default=ALL_DETAILS,
                   help=f"対象詳細度（省略時は全詳細度）: {' '.join(ALL_DETAILS)}")

    # run_all.py のオプションを“横流し”できるようにする
    p.add_argument("--skip-deck-scan", action="store_true")
    p.add_argument("--skip-script", action="store_true")
    p.add_argument("--skip-animation-assignment", action="store_true")
    p.add_argument("--skip-tts", action="store_true")
    p.add_argument("--skip-runner", action="store_true")
    p.add_argument("--skip-concat", action="store_true")
    p.add_argument("--stop-before", choices=["script", "animation", "tts", "runner"])

    p.add_argument("--continue-on-error", action="store_true",
                   help="失敗しても次のスタイルへ進む（実験一括生成向け）")
    return p.parse_args()


def _build_common_forward_args(args: argparse.Namespace) -> List[str]:
    forward: List[str] = []

    if args.material_root:
        forward += ["--material_root", str(args.material_root)]

    if args.skip_deck_scan:
        forward.append("--skip-deck-scan")
    if args.skip_script:
        forward.append("--skip-script")
    if args.skip_animation_assignment:
        forward.append("--skip-animation-assignment")
    if args.skip_tts:
        forward.append("--skip-tts")
    if args.skip_runner:
        forward.append("--skip-runner")
    if args.skip_concat:
        forward.append("--skip-concat")

    if args.stop_before:
        forward += ["--stop-before", args.stop_before]

    return forward


def main() -> None:
    if not RUN_ALL.exists():
        raise FileNotFoundError(f"run_all.py が見つかりません: {RUN_ALL}")

    args = parse_args()

    print("[run_allLD_lecture] material      :", args.material)
    print("[run_allLD_lecture] material_root :", args.material_root)
    print("[run_allLD_lecture] levels        :", args.levels)
    print("[run_allLD_lecture] details       :", args.details)
    print("[run_allLD_lecture] forward flags :", _build_common_forward_args(args))
    print()

    forward = _build_common_forward_args(args)
    results: List[tuple[str, int]] = []

    for level in args.levels:
        for detail in args.details:
            style = f"{level}{detail}"
            print("=" * 70)
            print(f"[run_allLD_lecture] ★ RUN style={style}")
            print("=" * 70)

            cmd = [
                sys.executable,
                str(RUN_ALL),
                "--material",
                args.material,
                "--level",
                level,
                "--detail",
                detail,
                *forward,
            ]
            print("[run_allLD_lecture] CMD:", " ".join(cmd))

            try:
                subprocess.run(cmd, check=True)
                results.append((style, 0))
            except subprocess.CalledProcessError as e:
                print(f"[run_allLD_lecture] ❗ FAILED style={style} (code={e.returncode})")
                results.append((style, e.returncode))
                if not args.continue_on_error:
                    raise

    print("\n" + "=" * 70)
    print("[run_allLD_lecture] すべてのスタイルの実行が完了しました。")
    print("結果一覧:")
    for style, code in results:
        status = "OK" if code == 0 else f"NG(code={code})"
        print(f"  - {style}: {status}")
    print("=" * 70)


if __name__ == "__main__":
    main()
