# scripts/run_allLD_audio_only_lecture.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from datetime import datetime

# ============================
# プロジェクトルート & src を sys.path に追加
# ============================
# このファイル: auto_lecture/scripts/run_allLD_audio_only_lecture.py
PROJECT_ROOT = Path(__file__).resolve().parents[1]   # .../auto_lecture
SRC_ROOT = PROJECT_ROOT / "src"

if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))


# ============================
# パッケージ内モジュールの読み込み
# ============================
from auto_lecture.paths import build_paths  # type: ignore
from auto_lecture.config import DEFAULT_MATERIAL_ROOT  # type: ignore
from auto_lecture.audio_only_lecture import (  # type: ignore
    run_audio_only_lecture as generate_audio_only_lecture,
)
from auto_lecture.tts_simple import tts_from_textfile  # type: ignore
from auto_lecture.audio_only_style_axes import (  # type: ignore
    LEVEL_TEXTS,
    DETAIL_TEXTS,
)


# 全スタイル一覧（audio_only_style_axes に依存）
ALL_LEVELS = list(LEVEL_TEXTS.keys())
ALL_DETAILS = list(DETAIL_TEXTS.keys())


# ============================
# 引数パーサ
# ============================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "スライドから音声のみ講義（台本 + 音声）を、"
            "定義されているすべてのスタイル(LxDy)に対して一括生成するスクリプト。\n"
            "1) audio_only_lecture でスタイル別台本生成 → "
            "2) 各スタイルの台本を TTS で mp3 に変換します。"
        )
    )

    # --- 教材 PDF 名 ---
    parser.add_argument(
        "--material",
        "-m",
        required=True,
        help="教材PDFファイル名（例: 'パターン認識への誘い.pdf'）",
    )

    # --- teachingmaterial ルート ---
    parser.add_argument(
        "--material-root",
        default=str(DEFAULT_MATERIAL_ROOT),
        help=(
            "教材フォルダ teachingmaterial のルート "
            f"(デフォルト: config.DEFAULT_MATERIAL_ROOT = {DEFAULT_MATERIAL_ROOT})"
        ),
    )

    # --- 対象とするレベル / 詳細度（省略時は全スタイル） ---
    parser.add_argument(
        "--levels",
        nargs="+",
        choices=ALL_LEVELS,
        default=ALL_LEVELS,
        help=(
            "生成対象とする講義レベル（複数指定可, 省略時は全レベル）。"
            f" 例: --levels {' '.join(ALL_LEVELS)}"
        ),
    )
    parser.add_argument(
        "--details",
        nargs="+",
        choices=ALL_DETAILS,
        default=ALL_DETAILS,
        help=(
            "生成対象とする詳細度（複数指定可, 省略時は全詳細度）。"
            f" 例: --details {' '.join(ALL_DETAILS)}"
        ),
    )

    # --- ステッチを無効化するか（デバッグ用） ---
    parser.add_argument(
        "--no-stitch",
        action="store_true",
        help="ステッチ処理（台本の再整形）をスキップしたい場合に指定。",
    )

    # --- TTS オプション（必要なら上書き） ---
    parser.add_argument(
        "--tts-model",
        default=None,
        help="TTS モデル名（省略時は config.API_TTS_MODEL を使用）。",
    )
    parser.add_argument(
        "--tts-voice",
        default=None,
        help="TTS の声（省略時は config.API_TTS_VOICE を使用）。",
    )
    parser.add_argument(
        "--tts-speed",
        type=float,
        default=None,
        help="TTS の話速（省略時は config.API_TTS_VOICE_SPEED を使用）。",
    )

    return parser.parse_args()


# ============================
# メイン処理
# ============================

def main() -> None:
    args = parse_args()

    teaching_material_file_name = args.material
    material_root = Path(args.material_root)
    levels = args.levels
    details = args.details

    print("[run_allLD_audio_only_lecture] 教材          :", teaching_material_file_name)
    print("[run_allLD_audio_only_lecture] material_root:", material_root)
    print("[run_allLD_audio_only_lecture] levels       :", levels)
    print("[run_allLD_audio_only_lecture] details      :", details)
    print()

    # ----------------------------------------
    # 共通の timestamp を確保
    # （同一バッチで生成したスタイルを揃えるため）
    # ----------------------------------------
    now = datetime.now()
    ts_date = now.strftime("%Y-%m-%d")
    ts_time = now.strftime("%H%M")

    generated_audios: list[tuple[str, Path]] = []

    for level in levels:
        for detail in details:
            style_label = f"{level}{detail}"
            print("=" * 70)
            print(f"[run_allLD_audio_only_lecture] ★ スタイル {style_label} の生成を開始します")
            print("=" * 70)

            # ----------------------------------------
            # 出力ルート名: <教材名>_YYYY-MM-DD_HHMM_LxDy
            # ----------------------------------------
            output_root_name = f"{teaching_material_file_name}_{ts_date}_{ts_time}_{style_label}"

            # ----------------------------------------
            # paths.py で ProjectPaths を構築
            # ----------------------------------------
            paths = build_paths(
                teaching_material_file_name=teaching_material_file_name,
                material_root=material_root,
                output_root_name=output_root_name,
                create_lp_timestamp_dir=False,  # 音声のみ処理なので LP タイムスタンプは作らない
            )

            # ----------------------------------------
            # Step1: スタイル別の音声のみ講義 台本生成
            #   ※ audio_only_lecture 側では:
            #      - アウトライン & 章ごとの台本生成
            #      - 台本整形（ステッチ）
            #     のどこでスタイルを効かせるかは実装側に委ねる。
            #     （このランナーは level/detail を渡すだけ）
            # ----------------------------------------
            print(f"[run_allLD_audio_only_lecture] Step1: 台本生成 (style={style_label})")

            result = generate_audio_only_lecture(
                paths=paths,
                level=level,
                detail=detail,
                do_stitch=not args.no_stitch,
            )

            audio_only_dir = result.get("audio_only_dir")
            materials_all_path = result.get("materials_all_path")
            outline_json_path = result.get("outline_json_path")
            outline_txt_path = result.get("outline_txt_path")
            lecture_title = result.get("lecture_title")
            script_path = result.get("script_path")  # 最終台本（ステッチ済みを想定）

            if script_path is None:
                raise RuntimeError(
                    f"[run_allLD_audio_only_lecture] style={style_label} の result に "
                    "'script_path' が含まれていません。\n"
                    "audio_only_lecture.generate_audio_only_lecture() が "
                    "'script_path' キーで最終台本の Path を返しているか確認してください。"
                )

            print()
            print(f"[run_allLD_audio_only_lecture] 台本生成完了 (style={style_label})")
            print("  出力ディレクトリ :", audio_only_dir)
            print("  講義タイトル     :", lecture_title)
            print("  材料テキスト     :", materials_all_path)
            print("  アウトライン JSON:", outline_json_path)
            print("  アウトライン TXT :", outline_txt_path)
            print("  使用台本         :", script_path)
            print("  スタイル         :", style_label)

            # ----------------------------------------
            # Step2: TTS で 1 本の mp3 に変換
            #   mode はファイル名用ラベルとして:
            #   lecture_audio_only_LxDy.mp3 のように使用
            # ----------------------------------------
            print()
            print(f"[run_allLD_audio_only_lecture] Step2: TTS で音声生成 (style={style_label})")

            tts_mode_label = f"audio_only_{style_label}"

            out_audio_path = tts_from_textfile(
                text_file=script_path,
                paths=paths,
                mode=tts_mode_label,
                model=args.tts_model,
                voice=args.tts_voice,
                speed=args.tts_speed,
                fmt="mp3",  # mp3 固定
            )

            generated_audios.append((style_label, out_audio_path))

            print()
            print(f"[run_allLD_audio_only_lecture] 完了 (style={style_label})")
            print("  TTS 出力ディレクトリ :", paths.tts_output_dir)
            print("  TTS 出力ファイル     :", out_audio_path)
            print()

    # ----------------------------------------
    # まとめ
    # ----------------------------------------
    print("=" * 70)
    print("[run_allLD_audio_only_lecture] すべてのスタイルの生成が完了しました。")
    print("生成された音声ファイル一覧:")
    for style_label, audio_path in generated_audios:
        print(f"  - style={style_label}: {audio_path}")
    print("=" * 70)


if __name__ == "__main__":
    main()
