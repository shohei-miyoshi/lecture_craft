# src/auto_lecture/paths.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from . import config


@dataclass
class ProjectPaths:
    # プロジェクト
    project_root: Path
    material_root: Path
    teaching_material_file_name: str

    # teachingmaterial/
    img_root: Path

    # outputs/<run_name>/
    output_dir: Path

    # lecture_outputs/
    explanation_save_dir: Path
    animation_output_dir: Path
    tts_output_dir: Path
    add_animation_output_dir: Path
    lecture_outputs_final: Path
    all_page_scan_output_dir: Path

    # LP_output（paths.py が完全に管理）
    lp_output_root: Path           # outputs/LP_output/
    lp_dir: Path                   # outputs/LP_output/<PDF名>/
    lp_snapshot_dir: Path          # outputs/<run_name>/LP_output/


def _resolve_under_project(project_root: Path, p: Path | str) -> Path:
    p = Path(p)
    return p if p.is_absolute() else (project_root / p)


def build_paths(
    teaching_material_file_name: str,
    material_root: Path | str = config.DEFAULT_MATERIAL_ROOT,
    output_root_name: Optional[str] = None,
    create_lp_timestamp_dir: bool = False,  # 互換のため残すが無視される
) -> ProjectPaths:

    # ----------------------------------------
    # project_root / material_root
    # ----------------------------------------
    project_root = Path(__file__).resolve().parents[2]
    material_root = _resolve_under_project(project_root, material_root)

    # teachingmaterial/img/<PDF名>
    img_root = material_root / "img" / teaching_material_file_name

    # outputs/
    outputs_root = project_root / "outputs"
    outputs_root.mkdir(parents=True, exist_ok=True)

    # outputs/<run_name>/
    output_dir = outputs_root / (output_root_name or teaching_material_file_name)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------
    # lecture_outputs 以下
    # ----------------------------------------
    lecture_root = output_dir / "lecture_outputs"
    lecture_root.mkdir(parents=True, exist_ok=True)

    explanation_save_dir = lecture_root / "lecture_texts"
    explanation_save_dir.mkdir(parents=True, exist_ok=True)

    animation_output_dir = lecture_root / "region_id_based_animation_outputs"
    animation_output_dir.mkdir(parents=True, exist_ok=True)

    tts_output_dir = lecture_root / "tts_outputs"
    tts_output_dir.mkdir(parents=True, exist_ok=True)

    add_animation_output_dir = lecture_root / "add_animation_outputs"
    add_animation_output_dir.mkdir(parents=True, exist_ok=True)

    lecture_outputs_final = lecture_root / "output_final"
    lecture_outputs_final.mkdir(parents=True, exist_ok=True)

    all_page_scan_output_dir = output_dir / "all_page_scan_outputs"
    all_page_scan_output_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------
    # LP_output （paths.py が100%管理）
    # ----------------------------------------
    lp_output_root = outputs_root / "LP_output"
    lp_output_root.mkdir(parents=True, exist_ok=True)

    # 公式 LP_output（教材別）
    lp_dir = lp_output_root / teaching_material_file_name
    lp_dir.mkdir(parents=True, exist_ok=True)

    # run_all の snapshot 先
    lp_snapshot_dir = output_dir / "LP_output"
    lp_snapshot_dir.mkdir(parents=True, exist_ok=True)

    # ----------------------------------------
    # 戻り値 dataclass
    # ----------------------------------------
    return ProjectPaths(
        project_root=project_root,
        material_root=material_root,
        teaching_material_file_name=teaching_material_file_name,
        img_root=img_root,
        output_dir=output_dir,
        explanation_save_dir=explanation_save_dir,
        animation_output_dir=animation_output_dir,
        tts_output_dir=tts_output_dir,
        add_animation_output_dir=add_animation_output_dir,
        lecture_outputs_final=lecture_outputs_final,
        all_page_scan_output_dir=all_page_scan_output_dir,
        lp_output_root=lp_output_root,
        lp_dir=lp_dir,
        lp_snapshot_dir=lp_snapshot_dir,
    )
