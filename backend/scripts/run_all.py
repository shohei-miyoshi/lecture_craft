# scripts/run_all.py
from __future__ import annotations

import argparse
import sys
import shutil
import json
import inspect
import os
import time
from pathlib import Path
from datetime import datetime
from typing import Optional, Any, Dict, List, Iterable, Tuple, Callable

THIS_FILE = Path(__file__).resolve()
PROJECT_ROOT = THIS_FILE.parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

# UTF-8 強制（Windows cp932 事故対策）
os.environ.setdefault("PYTHONUTF8", "1")

from auto_lecture.config import DEFAULT_MATERIAL_ROOT  # type: ignore
from auto_lecture.paths import build_paths, ProjectPaths  # type: ignore

from auto_lecture import deck_scan  # type: ignore
from auto_lecture import lecture_script  # type: ignore
from auto_lecture import animation_assignment  # type: ignore
from auto_lecture import tts_generation  # type: ignore
from auto_lecture import add_animation_runner_from_mapping  # type: ignore
from auto_lecture import lecture_concat  # type: ignore

# OpenAI client 取得（既存の gpt_client.py に寄せる）
try:
    from auto_lecture.gpt_client import get_client as get_openai_client  # type: ignore
except Exception:
    try:
        from auto_lecture.gpt_client import create_client as get_openai_client  # type: ignore
    except Exception:
        from auto_lecture.gpt_client import init_client as get_openai_client  # type: ignore


# ----------------------------
# ログ
# ----------------------------
def log(msg: str) -> None:
    print(f"[AUTO_LECTURE] {msg}", flush=True)

def warn(msg: str) -> None:
    print(f"[AUTO_LECTURE][WARN] {msg}", flush=True)


# ----------------------------
# experiments 用ユーティリティ
# ----------------------------
def _to_project_rel_str(p: Path) -> str:
    """
    PROJECT_ROOT からの相対パス文字列（できなければ絶対パス）
    """
    try:
        return str(p.resolve().relative_to(PROJECT_ROOT))
    except Exception:
        return str(p)

def _write_json_atomic(path: Path, obj: Any) -> None:
    """
    JSON を atomic に書く（途中で落ちても壊れにくい）
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def stable_output_root_name(material_pdf_name: str, level: str, detail: str, run_id: str, cond_id: str) -> str:
    """
    experiments/ 側が「どこに出したか」を安定参照できるように、
    outputs 配下の “フォルダ名” を固定する。

    ✅ audio_only と同じ思想:
      outputs/exp_runs/<run_id>/generation/raw/<lecture_key>/<cond_id>_<LxDy>

    ここで返すのは output_root_name（= outputs/<output_root_name>）
    """
    lecture_key = Path(str(material_pdf_name)).stem
    return f"exp_runs/{run_id}/generation/raw/{lecture_key}/{cond_id}_{level}{detail}"

def _emit_meta_started(
    *,
    emit_meta_path: Optional[str],
    run_id: str,
    cond_id: str,
    material: str,
    material_root: Path,
    level: str,
    detail: str,
    output_dir: Path,
) -> None:
    if not emit_meta_path:
        return
    meta = {
        "kind": "animation_generation_meta",
        "run_id": run_id or None,
        "lecture_title": Path(str(material)).stem,
        "cond_id": cond_id or None,
        "type": "anim",
        # ✅ Step1/Step2 が期待するキー
        "output_root": _to_project_rel_str(output_dir),
        "output_root_abs": str(output_dir),
        "inputs": {
            "teaching_material_file_name": material,
            "material_root": str(material_root),
            "style_axes": {"level": level, "detail": detail},
        },
        "timing": {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "status": "started",
        },
    }
    _write_json_atomic(Path(emit_meta_path), meta)
    log(f"[EXPERIMENT] emit_meta(started): {_to_project_rel_str(Path(emit_meta_path))}")

def _emit_meta_finished(
    *,
    emit_meta_path: Optional[str],
    success: bool,
    output_dir: Path,
    extra_artifacts: Optional[Dict[str, Any]] = None,
    error: Optional[BaseException] = None,
    sec_total: Optional[float] = None,
) -> None:
    if not emit_meta_path:
        return
    p = Path(emit_meta_path)
    try:
        prev = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        prev = {}

    timing = prev.get("timing", {}) if isinstance(prev.get("timing"), dict) else {}
    timing["finished_at"] = datetime.now().isoformat(timespec="seconds")
    timing["status"] = "success" if success else "error"
    if sec_total is not None:
        timing["seconds_total"] = round(sec_total, 1)

    prev["output_root"] = _to_project_rel_str(output_dir)
    prev["output_root_abs"] = str(output_dir)
    prev["timing"] = timing

    if extra_artifacts:
        artifacts = prev.get("artifacts", {})
        if not isinstance(artifacts, dict):
            artifacts = {}
        artifacts.update(extra_artifacts)
        prev["artifacts"] = artifacts

    if not success and error is not None:
        prev["error_type"] = type(error).__name__
        prev["error"] = str(error)

    _write_json_atomic(p, prev)
    log(f"[EXPERIMENT] emit_meta(finished): {_to_project_rel_str(p)}")


# ----------------------------
# LP snapshot
# ----------------------------
def copy_lp_output_snapshot(paths: ProjectPaths) -> None:
    """
    outputs/LP_output/<pdf>/ を今回の run の LP_snapshot_dir にコピーする。
    """
    src = paths.lp_dir
    dst = paths.lp_snapshot_dir
    if not Path(src).exists():
        warn(f"LP_output が存在しません: {src}（この run では LP snapshot をスキップ）")
        return
    shutil.copytree(src, dst, dirs_exist_ok=True)
    log(f"[OK] LP snapshot copied: {src} -> {dst}")


# ----------------------------
# Step0: deck_scan
# ----------------------------
def step_deck_scan(paths: ProjectPaths, level: str, detail: str) -> Path:
    log(f"Step0: deck_scan.run_deck_scan を実行中... (level={level}, detail={detail})")
    client = get_openai_client()
    overview_path = deck_scan.run_deck_scan(client=client, paths=paths, level=level, detail=detail)
    log(f"Step0: 完了 (overview: {overview_path})")
    return Path(overview_path)


# ----------------------------
# Step1: lecture_script
# ----------------------------
def step_lecture_script(paths: ProjectPaths, level: str, detail: str):
    log(f"Step1: lecture_script.run_lecture_script を実行中... (level={level}, detail={detail})")
    client = get_openai_client()
    explanations = lecture_script.run_lecture_script(client=client, paths=paths, level=level, detail=detail)
    log("Step1: 完了")
    return explanations


# ----------------------------
# Step2: animation_assignment
# ----------------------------
def step_animation_assignment(paths: ProjectPaths, explanations) -> None:
    """
    Step2の役割：
    - GPTを使って、スライド内の領域(region/bbox)と、台本文(文番号)の対応関係を作る（mapping json）
    - ここで「意味評価」はしない
    """
    if explanations is None:
        warn("Step2: explanations が None のためスキップします")
        return

    log("Step2: animation_assignment.run_animation_assignment を実行中...")
    client = get_openai_client()
    animation_assignment.run_animation_assignment(client=client, paths=paths, explanations=explanations)
    log("Step2: mapping 生成 完了")

    # mapping を「見やすく機械的にまとめる」(TSV/MD)
    try:
        mapping_dir = detect_mapping_dir(paths)
        if mapping_dir is None:
            warn("Step2: mapping_dir が見つかりません（概要生成スキップ）")
            return
        write_mapping_overview(paths, mapping_dir)
        log(f"[OK] Step2: mapping overview saved (dir={mapping_dir})")
    except Exception as e:
        warn(f"Step2: mapping overview 生成で例外（処理は継続）: {e}")


# ----------------------------
# Step3: TTS
# ----------------------------
def step_tts_generation(paths: ProjectPaths, explanations) -> None:
    if explanations is None:
        warn("Step3: explanations が None のためスキップします")
        return
    log("Step3: tts_generation.run_tts_generation を実行中...")
    tts_generation.run_tts_generation(paths, explanations)
    log("Step3: 完了")


# ----------------------------
# Step4: runner_from_mapping
# ----------------------------
def step_runner_from_mapping(paths: ProjectPaths) -> None:
    """
    Step4の役割：
    - mapping(対応関係)に基づいて、アニメーション素材を生成する
    - 生成先は add_animation_outputs に入っていないと Step5(lecture_concat)が拾えず、
      最終動画が「音声だけ」の静止画動画になりがち。
    - ここで必ず「出力が入ったか」を検証して、silent failure を潰す。
    """
    log("Step4: add_animation_runner_from_mapping.run_from_mapping を実行中...")

    mapping_dir = detect_mapping_dir(paths)
    if mapping_dir is None:
        raise RuntimeError(
            "Step4: mapping_dir が見つかりません。"
            "（Step2の生成物が移動/削除されている、または paths の参照先が違う可能性）"
        )

    # runner のシグネチャ揺れに対応（mapping_dir を渡せるなら渡す）
    run_fn = add_animation_runner_from_mapping.run_from_mapping
    kwargs: Dict[str, Any] = {}
    try:
        sig = inspect.signature(run_fn)
        if "mapping_dir" in sig.parameters:
            kwargs["mapping_dir"] = mapping_dir
        elif "mapping_root" in sig.parameters:
            kwargs["mapping_root"] = mapping_dir
    except Exception:
        pass

    run_fn(paths, **kwargs)  # type: ignore
    log("Step4: runner 呼び出し完了")

    # 出力検証（ここが最重要）
    verify_runner_outputs_or_raise(paths, mapping_dir)


# ----------------------------
# Step5: concat
# ----------------------------
def step_lecture_concat(paths: ProjectPaths) -> None:
    log("Step5: lecture_concat.run_concat を実行中...")
    lecture_concat.run_concat(paths)
    log("Step5: 完了")


# ============================
# mapping_dir 検出 / 概要化
# ============================
def detect_mapping_dir(paths: ProjectPaths) -> Optional[Path]:
    """
    mapping（対応関係）が置かれがちなディレクトリを総当たりで検出。
    期待：
      - lecture_outputs/region_id_based_animation_outputs/slide_XXX*.json
      - lecture_outputs/mapping/...
      - など（実装揺れに対応）
    """
    candidates: List[Path] = []

    # 1) paths にそれっぽい属性があれば優先
    for attr in [
        "region_id_based_animation_outputs",
        "mapping_dir",
        "mapping_output_dir",
        "animation_mapping_dir",
    ]:
        if hasattr(paths, attr):
            p = Path(getattr(paths, attr))
            candidates.append(p)

    # 2) lecture_outputs 配下を推測
    if hasattr(paths, "lecture_outputs_dir"):
        lo = Path(getattr(paths, "lecture_outputs_dir"))
        candidates.extend([
            lo / "region_id_based_animation_outputs",
            lo / "mapping",
            lo / "animation_mappings",
            lo / "animation_assignment_outputs",
        ])

    # 3) output_dir 配下からも推測
    if hasattr(paths, "output_dir"):
        out = Path(getattr(paths, "output_dir"))
        candidates.extend([
            out / "lecture_outputs" / "region_id_based_animation_outputs",
            out / "lecture_outputs" / "mapping",
        ])

    # 存在して、かつ json があるディレクトリを採用
    for c in candidates:
        try:
            if c.exists() and c.is_dir():
                js = list(c.glob("**/*.json"))
                if len(js) > 0:
                    return c
        except Exception:
            continue

    # 最後の手段：lecture_outputs 配下を探索
    try:
        base = Path(getattr(paths, "output_dir")) / "lecture_outputs"  # type: ignore
        if base.exists():
            for c in base.rglob("*"):
                if c.is_dir() and ("mapping" in c.name or "region_id" in c.name or "animation" in c.name):
                    js = list(c.glob("**/*.json"))
                    if len(js) > 0:
                        return c
    except Exception:
        pass

    return None


def write_mapping_overview(paths: ProjectPaths, mapping_dir: Path) -> None:
    """
    mapping json を機械的に読みやすく一覧化する（意味評価はしない）。
    - TSV: mapping_overview.tsv
    - MD : mapping_overview.md
    """
    # 出力先
    lecture_outputs = None
    if hasattr(paths, "lecture_outputs_dir"):
        lecture_outputs = Path(getattr(paths, "lecture_outputs_dir"))
    elif hasattr(paths, "output_dir"):
        lecture_outputs = Path(getattr(paths, "output_dir")) / "lecture_outputs"  # type: ignore
    else:
        lecture_outputs = mapping_dir.parent

    lecture_outputs.mkdir(parents=True, exist_ok=True)
    out_tsv = lecture_outputs / "mapping_overview.tsv"
    out_md = lecture_outputs / "mapping_overview.md"

    rows: List[Dict[str, Any]] = []

    json_files = sorted(mapping_dir.glob("**/*.json"))
    for jf in json_files:
        try:
            data = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            # cp932や壊れjsonでも落とさない
            try:
                data = json.loads(jf.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                continue

        # slide_001 などをファイル名から推測
        slide_id = infer_slide_id_from_path(jf)

        extracted = extract_mapping_rows(slide_id, jf.name, data)
        rows.extend(extracted)

    # TSV
    cols = ["slide_id", "sentence_idx", "region_id", "bbox_no", "anim_type", "note", "source_file"]
    lines = ["\t".join(cols)]
    for r in rows:
        lines.append("\t".join(str(r.get(c, "")) for c in cols))
    out_tsv.write_text("\n".join(lines), encoding="utf-8")

    # MD（ざっくり）
    md_lines = [
        "# Mapping Overview (mechanical)",
        "",
        f"- mapping_dir: {mapping_dir}",
        f"- items: {len(rows)}",
        "",
        "## Preview (first 50 rows)",
        "",
        "| slide_id | sentence_idx | region_id | bbox_no | anim_type | note | source_file |",
        "|---|---:|---|---:|---|---|---|",
    ]
    for r in rows[:50]:
        md_lines.append(
            f"| {r.get('slide_id','')} | {r.get('sentence_idx','')} | {r.get('region_id','')} | {r.get('bbox_no','')} | "
            f"{r.get('anim_type','')} | {str(r.get('note','')).replace('|','/')} | {r.get('source_file','')} |"
        )
    out_md.write_text("\n".join(md_lines), encoding="utf-8")


def infer_slide_id_from_path(p: Path) -> str:
    name = p.stem
    import re
    m = re.search(r"(?:slide[_-]?)(\d{1,4})", name, flags=re.IGNORECASE)
    if m:
        return f"slide_{int(m.group(1)):03d}"
    return ""


def extract_mapping_rows(slide_id: str, source_file: str, data: Any) -> List[Dict[str, Any]]:
    """
    mapping json の schema が揺れても落とさない抽出。
    """
    def pick(d: Dict[str, Any], keys: Iterable[str]) -> Any:
        for k in keys:
            if k in d:
                return d[k]
        return ""

    out: List[Dict[str, Any]] = []

    if isinstance(data, dict):
        items = None
        for k in ["items", "mappings", "mapping", "assignments", "results", "data", "rows"]:
            if k in data and isinstance(data[k], list):
                items = data[k]
                break

        if items is None and any(isinstance(v, list) for v in data.values()):
            for v in data.values():
                if isinstance(v, list):
                    items = v
                    break

        if items is None:
            if all(k in data for k in ["region_id", "anim_type"]):
                items = [data]
            else:
                return []

        for it in items:
            if not isinstance(it, dict):
                continue
            row = {
                "slide_id": slide_id or pick(it, ["slide_id", "slide"]),
                "sentence_idx": pick(it, ["sentence_idx", "sent_idx", "idx", "sentence", "sent"]),
                "region_id": pick(it, ["region_id", "region", "rid"]),
                "bbox_no": pick(it, ["bbox_no", "bbox", "box_no"]),
                "anim_type": pick(it, ["anim_type", "animation", "type"]),
                "note": pick(it, ["note", "reason", "comment", "desc", "description"]),
                "source_file": source_file,
            }
            out.append(row)
        return out

    if isinstance(data, list):
        for it in data:
            if isinstance(it, dict):
                out.append({
                    "slide_id": slide_id or it.get("slide_id", it.get("slide", "")),
                    "sentence_idx": it.get("sentence_idx", it.get("sent_idx", it.get("idx", ""))),
                    "region_id": it.get("region_id", it.get("rid", it.get("region", ""))),
                    "bbox_no": it.get("bbox_no", it.get("bbox", it.get("box_no", ""))),
                    "anim_type": it.get("anim_type", it.get("animation", it.get("type", ""))),
                    "note": it.get("note", it.get("reason", it.get("comment", ""))),
                    "source_file": source_file,
                })
        return out

    return []


# ============================
# runner 出力検証（重要）
# ============================
def _count_files(p: Path, exts: Tuple[str, ...]) -> int:
    if not p.exists():
        return 0
    n = 0
    for ext in exts:
        n += len(list(p.rglob(f"*{ext}")))
    return n


def verify_runner_outputs_or_raise(paths: ProjectPaths, mapping_dir: Path) -> None:
    """
    Step4 後に、add_animation_outputs が空なら即落とす。
    """
    add_dir = None
    rid_dir = None

    if hasattr(paths, "add_animation_outputs_dir"):
        add_dir = Path(getattr(paths, "add_animation_outputs_dir"))
    if hasattr(paths, "region_id_based_animation_outputs"):
        rid_dir = Path(getattr(paths, "region_id_based_animation_outputs"))

    if add_dir is None:
        if hasattr(paths, "lecture_outputs_dir"):
            add_dir = Path(getattr(paths, "lecture_outputs_dir")) / "add_animation_outputs"
        else:
            add_dir = Path(getattr(paths, "output_dir")) / "lecture_outputs" / "add_animation_outputs"  # type: ignore

    if rid_dir is None:
        if hasattr(paths, "lecture_outputs_dir"):
            rid_dir = Path(getattr(paths, "lecture_outputs_dir")) / "region_id_based_animation_outputs"
        else:
            rid_dir = Path(getattr(paths, "output_dir")) / "lecture_outputs" / "region_id_based_animation_outputs"  # type: ignore

    add_mp4 = _count_files(add_dir, (".mp4",))
    add_png = _count_files(add_dir, (".png", ".webp", ".jpg", ".jpeg"))
    rid_mp4 = _count_files(rid_dir, (".mp4",))
    rid_png = _count_files(rid_dir, (".png", ".webp", ".jpg", ".jpeg"))
    rid_json = _count_files(rid_dir, (".json",))

    log(f"[CHECK] add_animation_outputs: {add_dir} (mp4={add_mp4}, img={add_png})")
    log(f"[CHECK] region_id_based_animation_outputs: {rid_dir} (mp4={rid_mp4}, img={rid_png}, json={rid_json})")
    log(f"[CHECK] mapping_dir: {mapping_dir}")

    if add_mp4 == 0 and add_png == 0:
        if rid_mp4 > 0:
            raise RuntimeError(
                "Step4: runner は何か(mp4)を生成していますが、add_animation_outputs が空です。\n"
                "→ concat が add_animation_outputs を参照しているなら、アニメ無し動画になります。\n"
                f"add_animation_outputs={add_dir}\n"
                f"region_id_based_animation_outputs={rid_dir}\n"
                "対処：runner の出力先を add_animation_outputs に揃えるか、concat の参照先を揃えてください。"
            )

        raise RuntimeError(
            "Step4: runner 後の出力が空です（add_animation_outputs も region_id_based_animation_outputs も mp4が無い）。\n"
            "→ mapping の読み込みに失敗している / 条件分岐でスキップしている / 入力パスが違う可能性。\n"
            f"add_animation_outputs={add_dir}\n"
            f"region_id_based_animation_outputs={rid_dir}\n"
            f"mapping_dir={mapping_dir}"
        )

    log("[OK] Step4 outputs look non-empty (good).")


# ============================
# パイプライン本体
# ============================
def run_pipeline(
    teaching_material_file_name: str,
    material_root: Path = DEFAULT_MATERIAL_ROOT,
    level: str = "L3",
    detail: str = "D2",
    skip_deck_scan: bool = False,
    skip_script: bool = False,
    skip_animation_assignment: bool = False,
    skip_tts: bool = False,
    skip_runner: bool = False,
    skip_concat: bool = False,
    stop_before: Optional[str] = None,
    output_root_name: Optional[str] = None,
    # ✅ experiments から渡される（単体実行では空でOK）
    run_id: str = "",
    cond_id: str = "",
    emit_meta_path: Optional[str] = None,
    progress_callback: Optional[Callable[[int, str], None]] = None,
    cancel_checker: Optional[Callable[[], None]] = None,
) -> None:
    os.environ.setdefault("PYTHONUTF8", "1")

    def report(progress: int, message: str) -> None:
        if progress_callback is not None:
            progress_callback(progress, message)

    def check_cancel() -> None:
        if cancel_checker is not None:
            cancel_checker()

    # ✅ run_id+cond_id が揃っているときは “安定パス” を優先
    if run_id and cond_id:
        output_root_name = stable_output_root_name(teaching_material_file_name, level, detail, run_id, cond_id)
    else:
        # 従来挙動：未指定なら timestamp 名
        now = datetime.now()
        ts_date = now.strftime("%Y-%m-%d")
        ts_time = now.strftime("%H%M")
        if output_root_name is None:
            output_root_name = f"{teaching_material_file_name}_{ts_date}_{ts_time}_{level}{detail}"

    paths = build_paths(
        teaching_material_file_name=teaching_material_file_name,
        material_root=material_root,
        output_root_name=output_root_name,
        create_lp_timestamp_dir=False,  # run_all では新規LPを切らない
    )

    output_dir = Path(getattr(paths, "output_dir"))
    log(f"教材: {teaching_material_file_name}")
    log(f"Style Axes: level={level}, detail={detail}")
    log(f"cond_id: {cond_id or '(none)'}")
    log(f"Outputs root: {_to_project_rel_str(output_dir)}")
    if emit_meta_path:
        log(f"[EXPERIMENT] emit_meta={_to_project_rel_str(Path(emit_meta_path))}")

    # emit_meta: started
    t0_all = time.perf_counter()
    _emit_meta_started(
        emit_meta_path=emit_meta_path,
        run_id=run_id,
        cond_id=cond_id,
        material=teaching_material_file_name,
        material_root=material_root,
        level=level,
        detail=detail,
        output_dir=output_dir,
    )

    explanations = None
    try:
        # Step0前に LP snapshot をコピー
        check_cancel()
        report(58, "動画パイプラインを初期化しています")
        copy_lp_output_snapshot(paths)

        if not skip_deck_scan:
            check_cancel()
            report(62, "スライド全体の構成を解析しています")
            step_deck_scan(paths, level=level, detail=detail)
        else:
            log("Step0: deck_scan skip")

        if stop_before == "script":
            log("stop_before=script で停止")
            _emit_meta_finished(
                emit_meta_path=emit_meta_path,
                success=True,
                output_dir=output_dir,
                extra_artifacts={"stopped_before": "script"},
                sec_total=time.perf_counter() - t0_all,
            )
            return

        if not skip_script:
            check_cancel()
            report(70, "各スライドの講義台本を生成しています")
            explanations = step_lecture_script(paths, level=level, detail=detail)
        else:
            log("Step1: lecture_script skip")

        if stop_before == "animation":
            log("stop_before=animation で停止")
            _emit_meta_finished(
                emit_meta_path=emit_meta_path,
                success=True,
                output_dir=output_dir,
                extra_artifacts={"stopped_before": "animation"},
                sec_total=time.perf_counter() - t0_all,
            )
            return

        if not skip_animation_assignment:
            check_cancel()
            report(78, "台本とハイライト演出を対応付けています")
            step_animation_assignment(paths, explanations)
        else:
            log("Step2: animation_assignment skip")

        if stop_before == "tts":
            log("stop_before=tts で停止")
            _emit_meta_finished(
                emit_meta_path=emit_meta_path,
                success=True,
                output_dir=output_dir,
                extra_artifacts={"stopped_before": "tts"},
                sec_total=time.perf_counter() - t0_all,
            )
            return

        if not skip_tts:
            check_cancel()
            report(84, "音声を合成しています")
            step_tts_generation(paths, explanations)
        else:
            log("Step3: tts skip")

        if stop_before == "runner":
            log("stop_before=runner で停止")
            _emit_meta_finished(
                emit_meta_path=emit_meta_path,
                success=True,
                output_dir=output_dir,
                extra_artifacts={"stopped_before": "runner"},
                sec_total=time.perf_counter() - t0_all,
            )
            return

        if not skip_runner:
            check_cancel()
            report(90, "各スライドの動画を生成しています")
            step_runner_from_mapping(paths)
        else:
            log("Step4: runner skip")

        if not skip_concat:
            check_cancel()
            report(96, "最終動画を連結しています")
            step_lecture_concat(paths)
        else:
            log("Step5: concat skip")

        # emit_meta: success
        _emit_meta_finished(
            emit_meta_path=emit_meta_path,
            success=True,
            output_dir=output_dir,
            extra_artifacts={
                "paths": {
                    "output_dir": str(output_dir),
                    "lecture_outputs_dir": str(Path(output_dir) / "lecture_outputs"),
                }
            },
            sec_total=time.perf_counter() - t0_all,
        )
        log("OK")
    except Exception as e:
        _emit_meta_finished(
            emit_meta_path=emit_meta_path,
            success=False,
            output_dir=output_dir,
            error=e,
            sec_total=time.perf_counter() - t0_all,
        )
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--material", required=True)
    parser.add_argument("--material_root", default=str(DEFAULT_MATERIAL_ROOT))
    parser.add_argument("--level", default="L3")
    parser.add_argument("--detail", default="D2")
    parser.add_argument("--output-root-name", default=None)

    parser.add_argument("--skip-deck-scan", action="store_true")
    parser.add_argument("--skip-script", action="store_true")
    parser.add_argument("--skip-animation-assignment", action="store_true")
    parser.add_argument("--skip-tts", action="store_true")
    parser.add_argument("--skip-runner", action="store_true")
    parser.add_argument("--skip-concat", action="store_true")
    parser.add_argument("--stop-before", choices=["script", "animation", "tts", "runner"])

    # ✅ experiments から渡される（無くても動く）
    parser.add_argument("--run-id", default="")
    parser.add_argument("--cond-id", default="")
    parser.add_argument("--emit-meta", default=None)

    args = parser.parse_args()

    run_pipeline(
        teaching_material_file_name=args.material,
        material_root=Path(args.material_root),
        level=args.level,
        detail=args.detail,
        skip_deck_scan=args.skip_deck_scan,
        skip_script=args.skip_script,
        skip_animation_assignment=args.skip_animation_assignment,
        skip_tts=args.skip_tts,
        skip_runner=args.skip_runner,
        skip_concat=args.skip_concat,
        stop_before=args.stop_before,
        output_root_name=args.output_root_name,
        run_id=args.run_id,
        cond_id=args.cond_id,
        emit_meta_path=args.emit_meta,
    )


if __name__ == "__main__":
    main()
