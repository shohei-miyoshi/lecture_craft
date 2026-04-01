# scripts/tts_custom_text.py
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path
from datetime import datetime

# Windows の cp932 事故対策（プロジェクト既存思想に合わせる）
os.environ.setdefault("PYTHONUTF8", "1")

# src を import 可能にする（run_all.py と同じやり方）
PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../auto_lecture
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from auto_lecture.paths import build_paths  # type: ignore
from auto_lecture.tts_simple import tts_from_textfile  # type: ignore


DEFAULT_TEXT = """最後に、「よい分割」とは何かを考えます。
N個のデータをK個に分ける方法は、ざっくり K の N 乗通りあります。
たとえば、100個を10に分けるなら、約 10 の 100 乗通りです。
桁外れに多いので、全候補を試して選ぶのは現実的ではありません。
では指針は何か。
近くにあるデータが、なるべく同じ部分集合に入るように分けることです。
まとまりの中を境界で引き裂かない。
密に集まるものは同じクラスタに残す。
このシンプルな方針が、分割を選ぶときの基本になります。
ここまでが、クラスタリングの基本的な考え方と用語の整理です。
次は、この方針を具体的な手法でどう実現するかを見ていきます。
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--text-file",
        type=str,
        default="",
        help="読み上げたい本文を入れたUTF-8テキストファイル（指定しない場合はスクリプト内のDEFAULT_TEXTを使用）",
    )
    ap.add_argument(
        "--mode",
        type=str,
        default="custom_tail",
        help="出力ファイル名に使うモード名（lecture_<mode>.mp3）",
    )
    ap.add_argument(
        "--output-root-name",
        type=str,
        default="",
        help="outputs/ 配下の出力先フォルダ名（指定しない場合は manual_tts_<timestamp>）",
    )
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root_name = args.output_root_name or f"manual_tts_{ts}"

    # build_paths は img_root も作りますが、TTSだけなら存在しなくてもOK
    paths = build_paths(
        teaching_material_file_name="manual_tts",
        output_root_name=output_root_name,
        create_lp_timestamp_dir=False,
    )

    # 入力テキストを確定
    if args.text_file:
        text_path = Path(args.text_file).resolve()
        if not text_path.exists():
            raise FileNotFoundError(f"--text-file not found: {text_path}")
    else:
        # 生成物の管理を楽にするため output_dir 配下に保存
        text_path = Path(paths.explanation_save_dir) / f"custom_text_{ts}.txt"
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(DEFAULT_TEXT, encoding="utf-8")

    # ✅ ここが「今回の講義と同じ音声」：
    # tts_from_textfile は config の既定 (model/voice/speed) を使う
    out_mp3 = tts_from_textfile(
        text_file=text_path,
        paths=paths,
        mode=args.mode,
        fmt="mp3",
        # model/voice/speed を渡さない = config(API_TTS_*)に一致
    )

    print("")
    print("[OK] TTS generated:")
    print(f"  text : {text_path}")
    print(f"  mp3  : {out_mp3}")
    print(f"  dir  : {Path(paths.tts_output_dir).resolve()}")


if __name__ == "__main__":
    main()