# ============================================================
# auto_lecture/experiments/scripts/07_pack_animation_review.py
#
# Step7: 人手評価用データ生成（アニメーション妥当性チェック用）
#
# 目的:
#   実験 3-1（アニメーションが正しいか）を人手で評価できるように，
#   「1文ごと」にアニメーション付与情報を見やすく整形して出力する。
#
# 重要ポリシー:
#   - 画像は不要（コピーしない・参照もしない）
#   - bbox は "番号" として出す（座標や画像は扱わない）
#   - 1文 = 1評価単位
#   - CSV と Markdown（可読）を両方出す
#
# 入力（Step3の抽出結果を前提）:
#   experiments/runs/<run_id>/extracted/index.csv
#   experiments/runs/<run_id>/extracted/<lecture_key>/<cond_id>/sentence_table.csv
#
# sentence_table.csv に期待する列（あれば使う）:
#   - sent_id / sentence_id / idx 等（無ければ行番号で代替）
#   - page / slide_page / page_index 等（無ければ空）
#   - text（必須）
#   - anim_type / animation_type 等（無ければ空）
#   - bbox_id / bbox_ids / region_id 等（無ければ空）
#
# 出力:
#   experiments/runs/<run_id>/review/animation_review/
#     ├─ animation_review.csv
#     ├─ animation_review.md
#     └─ per_lecture/
#         └─ <lecture_key>/<cond_id>.md
#
# CLI:
#   python experiments/scripts/07_pack_animation_review.py --run-id <RUN_ID>
# ============================================================

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple


# ----------------------------
# Paths
# ----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]  # auto_lecture/
EXPERIMENT_ROOT = PROJECT_ROOT / "experiments"
RUNS_ROOT = EXPERIMENT_ROOT / "runs"


# ----------------------------
# Logging
# ----------------------------
def log(msg: str) -> None:
    print(f"[STEP7][REVIEW_PACK] {msg}", flush=True)


# ----------------------------
# CSV helpers
# ----------------------------
def read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        return [dict(row) for row in r]


def write_csv(path: Path, header: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, "") for k in header})


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# ----------------------------
# Row normalizer
# ----------------------------
def pick_first(d: Dict[str, str], keys: List[str], default: str = "") -> str:
    for k in keys:
        v = d.get(k, "")
        if v is None:
            continue
        v = str(v).strip()
        if v != "":
            return v
    return default


def normalize_sentence_row(row: Dict[str, str], fallback_idx: int) -> Dict[str, str]:
    """
    sentence_table.csv の列名が多少違っても吸収して，
    review 用の正規化フォーマットにする。
    """
    sent_id = pick_first(row, ["sent_id", "sentence_id", "idx", "index", "row_id"], default=str(fallback_idx))
    page = pick_first(row, ["page", "slide_page", "page_index", "slide_index"], default="")
    text = pick_first(row, ["text", "sentence", "content"], default="")

    anim_type = pick_first(row, ["anim_type", "animation_type", "anim", "animation"], default="")
    bbox = pick_first(row, ["bbox_id", "bbox_ids", "region_id", "region_ids", "box_id", "boxes"], default="")

    # 余分な空白を軽く整形
    text = " ".join(text.split())
    return {
        "sent_id": sent_id,
        "page": page,
        "text": text,
        "anim_type": anim_type,
        "bbox": bbox,
    }


def is_animation_like(normalized_rows: List[Dict[str, str]]) -> bool:
    """
    その条件が「アニメ付きっぽいか」を雑に推定。
    anim_type が1つでも入っていればアニメ条件として扱う。
    """
    for r in normalized_rows:
        if r.get("anim_type", "").strip():
            return True
    return False


# ----------------------------
# Markdown formatter
# ----------------------------
def format_md_for_one_condition(
    lecture_key: str,
    cond_id: str,
    rows: List[Dict[str, str]],
) -> str:
    lines: List[str] = []
    lines.append(f"# Animation Review Pack")
    lines.append("")
    lines.append(f"- lecture: `{lecture_key}`")
    lines.append(f"- condition: `{cond_id}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    for r in rows:
        sent_id = r["sent_id"]
        page = r["page"]
        text = r["text"]
        anim = r["anim_type"]
        bbox = r["bbox"]

        lines.append(f"## Sentence {sent_id}")
        if page:
            lines.append(f"- Page: {page}")
        else:
            lines.append(f"- Page: (unknown)")
        lines.append(f"- Animation: `{anim}`" if anim else "- Animation: (none)")
        lines.append(f"- BBox/Region: `{bbox}`" if bbox else "- BBox/Region: (none)")
        lines.append("")
        lines.append(f"**Text**")
        lines.append("")
        lines.append(text if text else "(empty)")
        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--include-non-anim", action="store_true",
                    help="アニメ情報が無い条件も review 出力に含めたい場合（通常は不要）")
    args = ap.parse_args()

    run_id = args.run_id
    run_dir = RUNS_ROOT / run_id
    if not run_dir.exists():
        raise RuntimeError(f"run_dir not found: {run_dir}")

    extracted_root = run_dir / "extracted"
    index_path = extracted_root / "index.csv"
    if not index_path.exists():
        raise RuntimeError(f"extracted/index.csv not found: {index_path} (Step3 missing?)")

    review_root = run_dir / "review" / "animation_review"
    per_root = review_root / "per_lecture"
    review_root.mkdir(parents=True, exist_ok=True)
    per_root.mkdir(parents=True, exist_ok=True)

    index_rows = read_csv_dicts(index_path)
    log(f"index rows: {len(index_rows)}")

    # 全体CSV用
    out_rows: List[Dict[str, Any]] = []

    # 全体MD（リンク集として）
    md_index_lines: List[str] = []
    md_index_lines.append("# Animation Review Pack (Index)")
    md_index_lines.append("")
    md_index_lines.append(f"- run_id: `{run_id}`")
    md_index_lines.append("")
    md_index_lines.append("## Files")
    md_index_lines.append("")

    kept_conditions = 0
    skipped_conditions = 0

    for item in index_rows:
        lecture_key = item.get("lecture_key", "").strip()
        cond_id = item.get("cond_id", "").strip()
        sent_csv_rel = (item.get("sentence_table_csv") or "").strip()

        if not lecture_key or not cond_id or not sent_csv_rel:
            log(f"[WARN] index row missing lecture_key/cond_id/sentence_table_csv -> {item}")
            continue

        sent_csv_path = run_dir / sent_csv_rel
        if not sent_csv_path.exists():
            log(f"[WARN] missing sentence_table.csv: {sent_csv_path}")
            continue

        raw_rows = read_csv_dicts(sent_csv_path)
        norm_rows = [normalize_sentence_row(r, fallback_idx=i) for i, r in enumerate(raw_rows, 1)]

        # 条件がアニメ付きか推定
        anim_like = is_animation_like(norm_rows)
        if (not anim_like) and (not args.include_non_anim):
            skipped_conditions += 1
            continue

        kept_conditions += 1

        # per-condition markdown
        out_md = format_md_for_one_condition(lecture_key, cond_id, norm_rows)
        out_md_path = per_root / lecture_key / f"{cond_id}.md"
        write_text(out_md_path, out_md)

        # index md にリンク（相対パス）
        rel = out_md_path.relative_to(review_root)
        md_index_lines.append(f"- `{lecture_key}` / `{cond_id}` → `{rel.as_posix()}`")

        # 全体CSV：1文=1行
        for r in norm_rows:
            out_rows.append({
                "run_id": run_id,
                "lecture_key": lecture_key,
                "cond_id": cond_id,
                "sent_id": r["sent_id"],
                "page": r["page"],
                "text": r["text"],
                "anim_type": r["anim_type"],
                "bbox": r["bbox"],
                "source_sentence_table_csv": sent_csv_rel,
            })

    # 全体CSV出力
    if out_rows:
        header = [
            "run_id",
            "lecture_key",
            "cond_id",
            "sent_id",
            "page",
            "anim_type",
            "bbox",
            "text",
            "source_sentence_table_csv",
        ]
        out_csv_path = review_root / "animation_review.csv"
        write_csv(out_csv_path, header, out_rows)
        log(f"saved: {out_csv_path} (rows={len(out_rows)})")
    else:
        log("[WARN] no rows produced (maybe no animation conditions found?)")

    # 全体MD出力
    out_md_index = "\n".join(md_index_lines) + "\n"
    out_md_path = review_root / "animation_review.md"
    write_text(out_md_path, out_md_index)
    log(f"saved: {out_md_path}")

    log(f"kept_conditions   : {kept_conditions}")
    log(f"skipped_conditions: {skipped_conditions} (include_non_anim={args.include_non_anim})")


if __name__ == "__main__":
    main()
