# scripts/run_audio_only_lecture.py
# -*- coding: utf-8 -*-
"""
音声のみ講義生成（audio-only） 実行スクリプト

✅ 最新仕様（確定）
- Step3 は cond_id を最優先にして mode を確定（このスクリプトは audio-only 専用なので cond_id で自動TTSのON/OFFだけ見る）
- 音声のみ(cond_id に _audio)ではアニメ関連は不要
- 音声のみで音声が出ない場合は TTS 呼び出しを cond_id/_audio で自動ON にし、mp3存在確認まで行う
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import json
import inspect
from pathlib import Path
from datetime import datetime
from typing import Any, Optional, Dict, Iterable

PROJECT_ROOT = Path(__file__).resolve().parents[1]  # .../auto_lecture
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from auto_lecture.paths import build_paths  # type: ignore
from auto_lecture.config import DEFAULT_MATERIAL_ROOT  # type: ignore
from auto_lecture.audio_only_lecture import run_audio_only_lecture  # type: ignore
from auto_lecture.tts_simple import tts_from_textfile  # type: ignore


def log(msg: str) -> None:
    print(msg, flush=True)

def warn(msg: str) -> None:
    print("[WARN] " + msg, flush=True)


def _to_project_rel_str(p: Path) -> str:
    try:
        return str(p.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(p)

def _write_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def stable_output_root_name(material_pdf_name: str, level: str, detail: str, run_id: str, cond_id: str) -> str:
    lecture_key = Path(str(material_pdf_name)).stem
    return f"exp_runs/{run_id}/generation/raw/{lecture_key}/{cond_id}_{level}{detail}"


def _build_paths_flexible(
    *,
    teaching_material_file_name: str,
    material_root: Path,
    level: str,
    detail: str,
    output_root_name: Optional[str],
):
    sig = inspect.signature(build_paths)
    params = set(sig.parameters.keys())

    def _call(**kwargs):
        filtered = {k: v for k, v in kwargs.items() if k in params}
        return build_paths(**filtered)

    base_kwargs = dict(
        teaching_material_file_name=teaching_material_file_name,
        material_root=material_root,
        create_lp_timestamp_dir=False,
    )

    if output_root_name and "output_root_name" in params:
        return _call(**base_kwargs, output_root_name=output_root_name)

    if ("level" in params) or ("detail" in params):
        return _call(**base_kwargs, level=level, detail=detail)

    return _call(**base_kwargs)


def _call_audio_only_lecture_with_paths(*, paths: Any, mode: str, no_stitch: bool) -> Any:
    fn = run_audio_only_lecture
    sig = inspect.signature(fn)
    params = set(sig.parameters.keys())

    kwargs: Dict[str, Any] = {}

    if "paths" in params:
        kwargs["paths"] = paths
    else:
        # 位置引数版
        return fn(paths)

    # selected_modes / mode の揺れ対応
    if "selected_modes" in params:
        kwargs["selected_modes"] = [mode]
    elif "mode" in params:
        kwargs["mode"] = mode

    # stitch の揺れ対応
    if "do_stitch" in params:
        kwargs["do_stitch"] = (not no_stitch)
    elif "stitch" in params:
        kwargs["stitch"] = (not no_stitch)

    return fn(**kwargs)


def _find_mp3s(tts_root: Path) -> list[Path]:
    if not tts_root.exists():
        return []
    return [p for p in tts_root.rglob("*.mp3") if p.is_file()]


def run_pipeline(
    teaching_material_file_name: str,
    material_root: Path = DEFAULT_MATERIAL_ROOT,
    level: str = "L2",
    detail: str = "D2",
    mode: str = "detailed",
    do_tts: bool = False,
    no_stitch: bool = False,
    run_id: str = "",
    cond_id: str = "",
    emit_meta_path: Optional[str] = None,
) -> None:
    os.environ.setdefault("PYTHONUTF8", "1")

    # ✅ cond_id に _audio が入っていたら TTS を強制ON（確定仕様）
    if cond_id and ("_audio" in cond_id):
        do_tts = True

    output_root_name = None
    if run_id and cond_id:
        output_root_name = stable_output_root_name(teaching_material_file_name, level, detail, run_id, cond_id)

    paths = _build_paths_flexible(
        teaching_material_file_name=teaching_material_file_name,
        material_root=material_root,
        level=level,
        detail=detail,
        output_root_name=output_root_name,
    )

    output_dir = Path(getattr(paths, "output_dir", Path("OUTPUTS") / "UNKNOWN_OUTPUT_DIR"))
    log(f"[audio_only] 教材          : {teaching_material_file_name}")
    log(f"[audio_only] material_root: {material_root}")
    log(f"[audio_only] level/detail : {level} {detail}")
    log(f"[audio_only] mode         : {mode}")
    log(f"[audio_only] cond_id      : {cond_id or '(none)'}")
    log(f"[audio_only] do_tts       : {do_tts}")
    log(f"Outputs root: {_to_project_rel_str(output_dir)}")
    if emit_meta_path:
        log(f"[EXPERIMENT] emit_meta={_to_project_rel_str(Path(emit_meta_path))}")

    t0_all = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="seconds")

    # 1) 台本生成
    t0_gen = time.perf_counter()
    result = _call_audio_only_lecture_with_paths(paths=paths, mode=mode, no_stitch=no_stitch)
    t1_gen = time.perf_counter()

    # 2) script_path 推定
    script_path: Optional[Path] = None
    if isinstance(result, dict):
        for k in ("script_path", "script", "lecture_script_path", "lecture_script_stitched_path"):
            v = result.get(k)
            if isinstance(v, (str, Path)):
                script_path = Path(v)
                break
        if script_path is None and isinstance(result.get("scripts"), dict):
            v = result["scripts"].get(mode)
            if isinstance(v, (str, Path)):
                script_path = Path(v)
    elif isinstance(result, (str, Path)):
        script_path = Path(result)

    # 3) TTS
    t0_tts = time.perf_counter()
    tts_root: Optional[Path] = None
    if do_tts:
        # paths から tts 出力先を推定
        for attr in ("tts_output_dir", "tts_output_root"):
            v = getattr(paths, attr, None)
            if isinstance(v, (str, Path)):
                tts_root = Path(v)
                break

        if script_path and script_path.exists():
            try:
                sig = inspect.signature(tts_from_textfile)
                params = set(sig.parameters.keys())
                kwargs: Dict[str, Any] = {}

                if "text_file" in params:
                    kwargs["text_file"] = script_path
                if "paths" in params:
                    kwargs["paths"] = paths
                if "mode" in params:
                    kwargs["mode"] = mode
                if "fmt" in params:
                    kwargs["fmt"] = "mp3"

                if kwargs:
                    tts_from_textfile(**kwargs)
                else:
                    # 位置引数のみ版
                    tts_from_textfile(str(script_path))
            except Exception as e:
                raise RuntimeError(f"[audio_only] TTS failed: {repr(e)}") from e
        else:
            raise RuntimeError(f"[audio_only] do_tts=True but script_path not found: {script_path}")

        # ✅ mp3存在確認（確定仕様）
        if tts_root is None:
            # 最後の保険：output_dir 配下で探索
            tts_root = output_dir / "lecture_outputs" / "tts_outputs"
        mp3s = _find_mp3s(tts_root)
        if not mp3s:
            raise RuntimeError(f"[audio_only] TTS ran but no mp3 found under: {tts_root}")
        log(f"[audio_only] mp3 OK: {len(mp3s)} files under {tts_root}")

    t1_tts = time.perf_counter()

    t1_all = time.perf_counter()
    finished_at = datetime.now().isoformat(timespec="seconds")

    sec_gen = round(t1_gen - t0_gen, 1)
    sec_tts = round(t1_tts - t0_tts, 1) if do_tts else 0.0
    sec_all = round(t1_all - t0_all, 1)

    # meta
    if emit_meta_path:
        artifacts = {
            "output_dir": str(output_dir),
            "script_path": str(script_path) if script_path else None,
        }
        if tts_root:
            artifacts["tts_root"] = str(tts_root)

        meta = {
            "kind": "audio_only_generation_meta",
            "run_id": run_id or None,
            "lecture_title": Path(str(teaching_material_file_name)).stem,
            "cond_id": cond_id or None,
            "type": "audio",
            "output_root": _to_project_rel_str(output_dir),
            "output_root_abs": str(output_dir),
            "inputs": {
                "teaching_material_file_name": teaching_material_file_name,
                "material_root": str(material_root),
                "style_axes": {"level": level, "detail": detail},
                "mode": mode,
                "no_stitch": bool(no_stitch),
                "do_tts": bool(do_tts),
            },
            "result_type": type(result).__name__,
            "artifacts": artifacts,
            "timing": {
                "started_at": started_at,
                "finished_at": finished_at,
                "seconds_total": sec_all,
                "seconds_generation": sec_gen,
                "seconds_tts": sec_tts,
            },
        }
        _write_json_atomic(Path(emit_meta_path), meta)
        log(f"emit_meta: {_to_project_rel_str(Path(emit_meta_path))}")

    log(f"TIME: generation={sec_gen}s, tts={sec_tts}s, total={sec_all}s")
    log("OK")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--material", required=True)
    ap.add_argument("--material-root", default=str(DEFAULT_MATERIAL_ROOT))
    ap.add_argument("--level", default="L2")
    ap.add_argument("--detail", default="D2")
    ap.add_argument("--mode", default="detailed")
    ap.add_argument("--tts", action="store_true")
    ap.add_argument("--no-stitch", action="store_true")

    ap.add_argument("--run-id", default="")
    ap.add_argument("--cond-id", default="")
    ap.add_argument("--emit-meta", default=None)

    args = ap.parse_args()
    os.environ.setdefault("PYTHONUTF8", "1")

    run_pipeline(
        teaching_material_file_name=args.material,
        material_root=Path(args.material_root),
        level=args.level,
        detail=args.detail,
        mode=args.mode,
        do_tts=args.tts,  # cond_id が _audio なら中で強制ONされる
        no_stitch=args.no_stitch,
        run_id=args.run_id,
        cond_id=args.cond_id,
        emit_meta_path=args.emit_meta,
    )


if __name__ == "__main__":
    main()
