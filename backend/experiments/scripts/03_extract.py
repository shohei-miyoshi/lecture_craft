# experiments/scripts/03_extract.py
# ============================================================
# Step3: extract  (manifest-driven / dest直参照)
#
# 目的:
#   (A) 文単位データ (sentence_table.csv)
#   (B) 人手評価用：台本文 ↔ アニメ対応表 (script_animation_table.csv / .md) ※animation条件のみ
#
# 入力（唯一の真実）:
#   experiments/runs/<run_id>/generation/manifest_step02.jsonl
#   - 各行: lecture, cond_id, status, dest
#   - dest は output_root（生成物フォルダ）
#
# 追加入力（確定）:
#   experiments/runs/<run_id>/generation/meta/<lecture>/<cond_id>/meta.json
#   - "type": "animation" | "audio"
#   - Step3 はこの type を最優先に mode を確定する（存在しない場合のみ fallback）
#
# 出力:
#   experiments/runs/<run_id>/extracted/<lecture>/<cond_id>/
#     - script_merged.txt
#     - sentence_table.csv
#     - (animation条件のみ) script_animation_table.csv / .md
#     - meta.json
#   experiments/runs/<run_id>/extracted/index.csv
#   experiments/runs/<run_id>/reports/step03_extract_summary.json
#
# ポリシー:
#   - outputs/ を探索しない。manifest の dest だけ参照する。
#   - 命名規則に基づき「存在するものは漏れなく拾う。無いものは空欄」で表を固める。
#
# ★確定変更（重要）
#   - 台本テキストに混入するメタ行（BOM / created at / # image / 画像パス /
#     === slide === など）を Step3 で除去して「台本だけ」に正規化する。
#   - audio（音声のみ）のときは、アニメ関連（bbox_no/anim_type/LP/mapping/mp4）は不要。
#     → Step3 はアニメ関係ファイル自体を生成しない（tableを作らない）。
#   - mapping から bbox_no を取るときは「region_id」を読む
#     ★sent_no-1 を許すせいでズレる問題があったので、完全一致優先の2パス方式に修正
#
# ★今回の追加修正（ズレ最終対策）
#   - bbox_no(region_id) は「mp4が存在する行（=anim_typeが埋まる行）」だけに書く
#     → anim_type が空の行は bbox_no も必ず空にする（前行のはみ出し・誤救済を遮断）
# ============================================================

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def log(msg: str) -> None:
    print(f"[STEP3] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[STEP3][WARN] {msg}", flush=True)


def fatal(msg: str, code: int = 2) -> None:
    print(f"[STEP3][FATAL] {msg}", flush=True)
    raise SystemExit(code)


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def safe_relpath(p: Path, base: Path) -> str:
    try:
        return str(p.resolve().relative_to(base.resolve())).replace("/", "\\")
    except Exception:
        return str(p)


def read_text_best_effort(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


# ============================================================
# Step2 manifest row
# ============================================================
@dataclass(frozen=True)
class Step2Row:
    index: int
    lecture: str
    cond_id: str
    status: str  # moved / skip / error
    src: str
    dest: str
    output_root_dirname: str
    started_at: str
    finished_at: str
    elapsed_sec: float
    error: str

    @staticmethod
    def from_dict(d: dict) -> "Step2Row":
        return Step2Row(
            index=int(d.get("index") or 0),
            lecture=str(d.get("lecture") or ""),
            cond_id=str(d.get("cond_id") or ""),
            status=str(d.get("status") or ""),
            src=str(d.get("src") or ""),
            dest=str(d.get("dest") or ""),
            output_root_dirname=str(d.get("output_root_dirname") or ""),
            started_at=str(d.get("started_at") or ""),
            finished_at=str(d.get("finished_at") or ""),
            elapsed_sec=float(d.get("elapsed_sec") or 0.0),
            error=str(d.get("error") or d.get("reason") or ""),
        )


def load_step2_manifest_jsonl(path: Path) -> List[Step2Row]:
    if not path.exists():
        fatal(f"Step2 manifest not found: {path}")
    rows: List[Step2Row] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            try:
                obj = json.loads(s)
            except Exception as e:
                fatal(f"invalid json at line {line_no} in {path}: {e}")
            if not isinstance(obj, dict):
                fatal(f"jsonl line {line_no} is not an object")
            rows.append(Step2Row.from_dict(obj))
    return rows


# ============================================================
# sentence split
# ============================================================
_SENT_SPLIT_RE = re.compile(r"(?:\r?\n)+|(?:[。！？!?]+)")
_WS_RE = re.compile(r"[ \t]+")


# ============================================================
# text cleaning (重要: Step3で台本以外のメタ行を除去)
# ============================================================
_RE_WIN_PATH = re.compile(r"[A-Za-z]:\\[^\n]*\.(?:png|jpg|jpeg|webp|pdf|json|txt)", re.IGNORECASE)
_RE_DRIVE_ONLY = re.compile(r"^[A-Za-z]:\\?$")


def _should_drop_line(line: str) -> bool:
    s = line.strip()
    if not s:
        return True

    # BOM (utf-8-sig の \ufeff が混ざる)
    s = s.lstrip("\ufeff").strip()
    if not s:
        return True

    low = s.lower()

    # メタ行
    if low.startswith("#"):
        return True
    if low.startswith("===") and low.endswith("==="):
        return True
    if "created at" in low:
        return True
    if low.startswith("image:") or low.startswith("# image:"):
        return True

    # Windowsパス（行が分割されるケースも含む）
    if _RE_DRIVE_ONLY.match(s):
        return True
    if _RE_WIN_PATH.search(s):
        return True

    # teachingmaterial/img の実パス片割れ（drive無しでも落とす）
    if "teachingmaterial" in low and ("\\img\\" in low or "/img/" in low):
        if any(ext in low for ext in (".png", ".jpg", ".jpeg", ".webp", ".pdf")):
            return True
        return True

    # 明らかにパス片割れっぽい（kenkyu\auto_lecture\...）
    if ("auto_lecture" in low) and ("\\" in s) and any(ext in low for ext in (".png", ".jpg", ".jpeg", ".webp")):
        return True

    return False


def clean_script_text(text: str) -> str:
    """
    Step3の正規化用:
    - 台本以外のメタ行を除去
    - 行結合して読みやすい台本へ
    """
    if not text:
        return ""
    text = text.lstrip("\ufeff")
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    kept: List[str] = []
    for ln in lines:
        if _should_drop_line(ln):
            continue
        kept.append(_WS_RE.sub(" ", ln.strip()))

    return "\n".join(kept).strip()


def split_sentences(text: str) -> List[str]:
    text = clean_script_text(text)
    if not text:
        return []

    parts = _SENT_SPLIT_RE.split(text.strip())
    out: List[str] = []
    for p in parts:
        s = _WS_RE.sub(" ", p.strip())
        if not s:
            continue
        out.append(s)
    return out


# ============================================================
# mode detection (確定: meta.json type 最優先)
# ============================================================
RE_SLIDE_TXT = re.compile(r"^slide_(\d{3})\.txt$", re.IGNORECASE)
RE_MATERIALS_SLIDE = re.compile(r"^materials_slide_(\d{3})\.txt$", re.IGNORECASE)
RE_ANIM_MP4 = re.compile(r"^slide_(\d{3})_sent(\d{2})(?:_(.+))?\.mp4$", re.IGNORECASE)


def _candidate_generation_meta_paths(run_dir: Path, lecture: str, cond_id: str) -> List[Path]:
    """
    generation/meta の配置揺れに対応。
    例:
      generation/meta/<lecture>/<cond_id>/meta.json
      generation/meta/<lecture_stem>/<cond_id>/meta.json
    """
    lecture_p = Path(lecture)
    lecture_stem = lecture_p.stem

    cands = [
        run_dir / "generation" / "meta" / lecture / cond_id / "meta.json",
        run_dir / "generation" / "meta" / lecture_stem / cond_id / "meta.json",
    ]
    return cands


def read_generation_meta_type(run_dir: Path, lecture: str, cond_id: str) -> Optional[str]:
    for p in _candidate_generation_meta_paths(run_dir, lecture, cond_id):
        if p.exists():
            try:
                obj = read_json(p)
                if isinstance(obj, dict):
                    t = obj.get("type")
                    if isinstance(t, str) and t.strip():
                        return t.strip().lower()
            except Exception:
                return None
    return None


def detect_mode_from_outputs(output_root: Path) -> str:
    """
    fallback（互換用）: 生成物から推測。
    ただし確定仕様では meta.json type を優先する。
    """
    lt = output_root / "lecture_outputs" / "lecture_texts"
    if (lt / "all_explanations.txt").exists():
        return "animation"
    if list((output_root / "lecture_outputs" / "add_animation_outputs").glob("slide_*_sent*.mp4")):
        return "animation"
    if (lt / "audio_only").exists():
        return "audio"
    return "unknown"


def detect_page_count(output_root: Path, mode: str) -> Tuple[int, str, List[int]]:
    lt = output_root / "lecture_outputs" / "lecture_texts"
    ao = lt / "audio_only"

    if mode == "animation":
        idx: List[int] = []
        if lt.exists():
            for p in lt.iterdir():
                if p.is_file():
                    m = RE_SLIDE_TXT.match(p.name)
                    if m:
                        idx.append(int(m.group(1)))
        if idx:
            return max(idx), "lecture_outputs/lecture_texts/slide_###.txt", sorted(idx)

    if mode == "audio":
        idx = []
        if ao.exists():
            for p in ao.iterdir():
                if p.is_file():
                    m = RE_MATERIALS_SLIDE.match(p.name)
                    if m:
                        idx.append(int(m.group(1)))
        if idx:
            return max(idx), "lecture_outputs/lecture_texts/audio_only/materials_slide_###.txt", sorted(idx)

    # fallback (両方拾う)
    idx1: List[int] = []
    if lt.exists():
        for p in lt.iterdir():
            if p.is_file():
                m = RE_SLIDE_TXT.match(p.name)
                if m:
                    idx1.append(int(m.group(1)))

    idx2: List[int] = []
    if ao.exists():
        for p in ao.iterdir():
            if p.is_file():
                m = RE_MATERIALS_SLIDE.match(p.name)
                if m:
                    idx2.append(int(m.group(1)))

    idx = sorted(set(idx1 + idx2))
    if idx:
        return max(idx), "fallback(slide_###.txt or materials_slide_###.txt)", idx

    return 0, "none", []


# ============================================================
# animations / mappings
# ============================================================
def parse_animation_clips(output_root: Path) -> Dict[Tuple[int, int], Dict[str, str]]:
    anim_dir = output_root / "lecture_outputs" / "add_animation_outputs"
    out: Dict[Tuple[int, int], Dict[str, str]] = {}
    if not anim_dir.exists():
        return out
    for p in sorted(anim_dir.glob("slide_*_sent*.mp4")):
        m = RE_ANIM_MP4.match(p.name)
        if not m:
            continue
        slide_no = int(m.group(1))
        sent_no = int(m.group(2))  # 1-based
        style = (m.group(3) or "").strip()
        out[(slide_no, sent_no)] = {"anim_type": style if style else "", "clip_path": str(p)}
    return out


def load_slide_mapping_json(output_root: Path, slide_no: int) -> Optional[Any]:
    map_dir = output_root / "lecture_outputs" / "region_id_based_animation_outputs"
    # よくある: slide_002_mappings.json
    p = map_dir / f"slide_{slide_no:03d}_mappings.json"
    if not p.exists():
        # 揺れ: slide_002_mapping.json / mapping_slide_002.json 等
        for cand in [
            map_dir / f"slide_{slide_no:03d}_mapping.json",
            map_dir / f"mapping_slide_{slide_no:03d}.json",
        ]:
            if cand.exists():
                p = cand
                break
        else:
            return None
    try:
        return read_json(p)
    except Exception:
        return None


def find_bbox_for_sentence_in_mapping(mapping_obj: Any, sent_no_1based: int) -> str:
    """
    ✅ bbox_no列に「region_id」を入れる（animate.region_id が正）

    ★重要修正:
      以前: target={sent_no, sent_no-1} を同時に探索 → 先に見つかった別文の region_id を誤採用しズレる
      今回: 2パス方式
        (1) sent_idx == sent_no の完全一致のみ
        (2) 見つからない場合のみ sent_idx == sent_no-1（0-based救済）
    """

    def norm_int(x: Any) -> Optional[int]:
        try:
            if isinstance(x, bool):
                return None
            if isinstance(x, int):
                return int(x)
            if isinstance(x, str) and x.strip().lstrip("-").isdigit():
                return int(x.strip())
        except Exception:
            return None
        return None

    def get_region_id_from_animate(animate: Any) -> Optional[str]:
        if not animate:
            return None
        if isinstance(animate, dict):
            # 最優先：region_id
            for k in ("region_id", "rid", "region", "region_idx", "region_index"):
                if k in animate:
                    v = animate.get(k)
                    if v is None:
                        return None
                    if isinstance(v, (int, str)):
                        return str(v)
        return None

    def find_by_sent_idx(target_sent: int) -> Optional[str]:
        # まず「あなたの実例のschema」を最優先で処理（最も確実）
        if isinstance(mapping_obj, dict) and isinstance(mapping_obj.get("sentences"), list):
            for s in mapping_obj["sentences"]:
                if not isinstance(s, dict):
                    continue
                sent_idx = None
                for k in ("sent_idx", "sentence_idx", "sent_no", "idx", "index"):
                    if k in s:
                        sent_idx = norm_int(s.get(k))
                        if sent_idx is not None:
                            break
                if sent_idx != target_sent:
                    continue
                animate = s.get("animate")
                rid = get_region_id_from_animate(animate)
                if rid is not None:
                    return rid
            return None

        # fallback: 走査（ただし「完全一致のみ」を守る）
        SENT_KEYS = {
            "sent",
            "sent_id",
            "sent_idx",
            "sentence",
            "sentence_id",
            "sentence_idx",
            "sentence_index",
            "sent_no",
            "idx",
            "index",
        }

        def walk(node: Any, current_sent: Optional[int]) -> Optional[str]:
            if isinstance(node, dict):
                local_sent = current_sent
                # この dict 自身に sent があれば更新
                for k, v in node.items():
                    if str(k).lower() in SENT_KEYS:
                        nv = norm_int(v)
                        if nv is not None:
                            local_sent = nv

                # animate がある場合は animate.region_id を読む
                if local_sent == target_sent and "animate" in node:
                    rid = get_region_id_from_animate(node.get("animate"))
                    if rid is not None:
                        return rid

                # 他にも region_id を直接持つ揺れがあるなら拾う（ただし sent 一致が前提）
                if local_sent == target_sent:
                    for k in ("region_id", "rid", "region"):
                        if k in node and node.get(k) is not None:
                            v = node.get(k)
                            if isinstance(v, (int, str)):
                                return str(v)

                for v in node.values():
                    r = walk(v, local_sent)
                    if r is not None:
                        return r
                return None

            if isinstance(node, list):
                for it in node:
                    r = walk(it, current_sent)
                    if r is not None:
                        return r
                return None

            return None

        return walk(mapping_obj, None)

    # 1) 完全一致（1-based）
    rid1 = find_by_sent_idx(sent_no_1based)
    if rid1 is not None:
        return rid1

    # 2) 救済（0-basedの可能性がある場合のみ）
    if sent_no_1based > 0:
        rid2 = find_by_sent_idx(sent_no_1based - 1)
        if rid2 is not None:
            return rid2

    return ""


# ============================================================
# output writers
# ============================================================
def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_markdown_table(path: Path, rows: List[Dict[str, Any]], title: str) -> None:
    cols = ["slide_no", "sentence_no", "bbox_no", "anim_type", "text"]
    lines = [f"# {title}", ""]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join(["---"] * len(cols)) + " |")
    for r in rows:
        vals = []
        for c in cols:
            v = str(r.get(c, "") or "").replace("\n", " ").replace("|", "｜")
            vals.append(v)
        lines.append("| " + " | ".join(vals) + " |")
    write_text(path, "\n".join(lines) + "\n")


# ============================================================
# dest resolver (重要)
# ============================================================
def resolve_dest_path(dest_str: str, run_dir: Path) -> Path:
    """
    ✅確定ルール:
    - 絶対パスならそのまま
    - 相対パスなら run_dir 基準で解決（manifest が run_dir 配下にあるため）
    - それでも存在しない場合はプロジェクトルート(CWD)基準も試す（保険）
    """
    p = Path(dest_str)
    if p.is_absolute():
        return p

    cand1 = (run_dir / p).resolve()
    if cand1.exists():
        return cand1

    cand2 = (Path(".") / p).resolve()
    return cand2


# ============================================================
# core
# ============================================================
def extract_one(row: Step2Row, run_dir: Path, extracted_root: Path, force: bool) -> Dict[str, Any]:
    lecture = row.lecture
    cond_id = row.cond_id

    out_dir = extracted_root / lecture / cond_id
    out_dir.mkdir(parents=True, exist_ok=True)

    out_script = out_dir / "script_merged.txt"
    out_sent = out_dir / "sentence_table.csv"
    out_map_table_csv = out_dir / "script_animation_table.csv"
    out_map_table_md = out_dir / "script_animation_table.md"
    out_meta = out_dir / "meta.json"

    meta: Dict[str, Any] = {
        "run_id": run_dir.name,
        "lecture_title": lecture,
        "cond_id": cond_id,
        "step2": {"status": row.status, "dest": row.dest},
        "status": None,
        "mode": None,
        "page_count": None,
        "page_count_source": None,
        "notes": [],
        "errors": [],
        "outputs": {
            "script_merged_txt": safe_relpath(out_script, run_dir),
            "sentence_table_csv": safe_relpath(out_sent, run_dir),
            "script_animation_table_csv": "",
            "script_animation_table_md": "",
            "meta_json": safe_relpath(out_meta, run_dir),
        },
        "timestamps": {"extracted_at": now_iso()},
    }

    if row.status not in ("moved", "skip"):
        meta["status"] = "error"
        meta["errors"].append("step2 status is not moved/skip")
        write_json(out_meta, meta)
        return meta

    output_root = resolve_dest_path(row.dest, run_dir)
    meta["resolved_dest"] = str(output_root).replace("/", "\\")
    if not output_root.exists():
        meta["status"] = "error"
        meta["errors"].append(f"dest output_root not found: {output_root}")
        write_json(out_meta, meta)
        return meta

    meta_type = read_generation_meta_type(run_dir, lecture, cond_id)
    if meta_type in ("animation", "audio"):
        mode = meta_type
        meta["notes"].append(f"mode fixed by generation/meta type: {meta_type}")
    else:
        if "_audio" in (cond_id or ""):
            mode = "audio"
            meta["notes"].append("mode fallback by cond_id contains _audio")
        else:
            mode = detect_mode_from_outputs(output_root)
            meta["notes"].append(f"mode fallback by outputs detection: {mode}")

    meta["mode"] = mode

    if not force and out_meta.exists() and out_sent.exists() and out_script.exists():
        if mode == "audio":
            try:
                old = read_json(out_meta)
                if isinstance(old, dict) and old.get("status") == "ok":
                    meta["status"] = "skip"
                    meta["notes"].append("already extracted (audio)")
                    write_json(out_meta, meta)
                    return meta
            except Exception:
                pass
        else:
            if out_map_table_csv.exists():
                try:
                    old = read_json(out_meta)
                    if isinstance(old, dict) and old.get("status") == "ok":
                        meta["status"] = "skip"
                        meta["notes"].append("already extracted (animation)")
                        write_json(out_meta, meta)
                        return meta
                except Exception:
                    pass

    N, src, idxs = detect_page_count(output_root, mode)
    meta["page_count"] = N
    meta["page_count_source"] = src
    meta["page_indices_detected"] = idxs

    if N <= 0:
        meta["status"] = "error"
        meta["errors"].append("page_count not detected")
        write_json(out_meta, meta)
        return meta

    script_path: Optional[Path] = None
    script_source = ""

    lt = output_root / "lecture_outputs" / "lecture_texts"
    if mode == "animation":
        p = lt / "all_explanations.txt"
        if p.exists():
            script_path = p
            script_source = "animation:all_explanations.txt"
    elif mode == "audio":
        ao = lt / "audio_only"
        p1 = ao / "lecture_script_stitched.txt"
        p2 = ao / "lecture_script.txt"
        if p1.exists():
            script_path = p1
            script_source = "audio:lecture_script_stitched.txt"
        elif p2.exists():
            script_path = p2
            script_source = "audio:lecture_script.txt"

    if script_path is None:
        txts = [p for p in lt.rglob("*.txt") if p.is_file()] if lt.exists() else []
        if txts:
            txts.sort(key=lambda x: x.stat().st_size, reverse=True)
            script_path = txts[0]
            script_source = "fallback:largest_txt_under_lecture_texts"
            meta["notes"].append("fallback: picked largest txt under lecture_texts")

    if script_path is None or (not script_path.exists()):
        meta["status"] = "error"
        meta["errors"].append("script file not found")
        write_json(out_meta, meta)
        return meta

    meta["script_path"] = str(script_path).replace("/", "\\")
    meta["script_source"] = script_source

    script_raw = read_text_best_effort(script_path)
    script_text = clean_script_text(script_raw)

    if not script_text:
        meta["status"] = "error"
        meta["errors"].append("script is empty after cleaning")
        write_json(out_meta, meta)
        return meta

    write_text(out_script, script_text)

    sents = split_sentences(script_text)
    sent_rows: List[Dict[str, Any]] = []
    for i, s in enumerate(sents):
        sent_rows.append(
            {
                "lecture_title": lecture,
                "cond_id": cond_id,
                "sentence_id": f"s{i:05d}",
                "global_sentence_id": f"{lecture}__{cond_id}__s{i:05d}",
                "sentence_index": i,
                "text": s,
                "char_len": len(s),
            }
        )
    write_csv(out_sent, sent_rows)

    if mode == "animation":
        anim_clips = parse_animation_clips(output_root)
        table_rows: List[Dict[str, Any]] = []

        for slide in range(1, N + 1):
            slide3 = f"{slide:03d}"

            slide_txt = output_root / "lecture_outputs" / "lecture_texts" / f"slide_{slide3}.txt"
            slide_text = read_text_best_effort(slide_txt) if slide_txt.exists() else ""
            slide_sents = split_sentences(slide_text)

            mapping_obj = load_slide_mapping_json(output_root, slide)

            mp4_sent_nos = [sent_no for (sno, sent_no) in anim_clips.keys() if sno == slide]
            max_mp4 = max(mp4_sent_nos) if mp4_sent_nos else 0

            max_text = len(slide_sents)
            max_rows = max(max_text, max_mp4)

            for sent_no in range(1, max_rows + 1):  # 1-based
                sent_text = slide_sents[sent_no - 1] if (sent_no - 1) < len(slide_sents) else ""
                anim_type = ""
                bbox_no = ""

                clip = anim_clips.get((slide, sent_no))
                if clip:
                    anim_type = clip.get("anim_type", "") or ""

                # ★今回の追加修正:
                #   bbox_no(region_id) は anim_type と同じタイミングでのみ埋める
                #   → mp4が無い（anim_typeが空）なら bbox_no も必ず空
                if anim_type and mapping_obj is not None:
                    bbox_no = find_bbox_for_sentence_in_mapping(mapping_obj, sent_no)
                else:
                    bbox_no = ""

                table_rows.append(
                    {
                        "slide_no": slide,
                        "sentence_no": sent_no,
                        "bbox_no": bbox_no,
                        "anim_type": anim_type,
                        "text": sent_text,
                    }
                )

        write_csv(out_map_table_csv, table_rows)
        write_markdown_table(out_map_table_md, table_rows, title=f"{lecture} / {cond_id} : Script ↔ Animation Table")
        meta["outputs"]["script_animation_table_csv"] = safe_relpath(out_map_table_csv, run_dir)
        meta["outputs"]["script_animation_table_md"] = safe_relpath(out_map_table_md, run_dir)
        meta["stats"] = {"num_sentences_global": len(sent_rows), "num_rows_script_animation_table": len(table_rows)}
    else:
        meta["stats"] = {"num_sentences_global": len(sent_rows)}
        meta["notes"].append("audio mode: skipped generating script_animation_table.*")

        for p in (out_map_table_csv, out_map_table_md):
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass

    meta["status"] = "ok"
    write_json(out_meta, meta)
    return meta


def write_index_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    cols = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--runs-root", default="experiments/runs")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--allow-partial", action="store_true")
    args = ap.parse_args()

    run_dir = Path(args.runs_root) / args.run_id
    if not run_dir.exists():
        fatal(f"run_dir not found: {run_dir}")

    manifest_path = Path(args.manifest) if args.manifest else (run_dir / "generation" / "manifest_step02.jsonl")
    if not manifest_path.is_absolute():
        manifest_path = (Path(".") / manifest_path).resolve()

    extracted_root = run_dir / "extracted"
    extracted_root.mkdir(parents=True, exist_ok=True)

    rows = load_step2_manifest_jsonl(manifest_path)

    log(f"run_id={args.run_id}")
    log(f"manifest={manifest_path}")
    log(f"rows={len(rows)}")

    index_rows: List[Dict[str, Any]] = []
    ok = 0
    skip = 0
    err = 0

    for r in rows:
        meta = extract_one(r, run_dir, extracted_root, force=args.force)
        st = meta.get("status")
        if st == "ok":
            ok += 1
        elif st == "skip":
            skip += 1
        else:
            err += 1

        outs = meta.get("outputs", {})
        index_rows.append(
            {
                "lecture_title": meta.get("lecture_title", r.lecture),
                "cond_id": meta.get("cond_id", r.cond_id),
                "status": st,
                "script_merged_txt": outs.get("script_merged_txt", ""),
                "sentence_table_csv": outs.get("sentence_table_csv", ""),
                "mapping_normalized_json": "",
                "meta_json": outs.get("meta_json", ""),
                "script_animation_table_csv": outs.get("script_animation_table_csv", ""),
                "script_animation_table_md": outs.get("script_animation_table_md", ""),
            }
        )

    index_csv = extracted_root / "index.csv"
    write_index_csv(index_csv, index_rows)

    summary = {
        "run_id": args.run_id,
        "rows": len(rows),
        "ok": ok,
        "skipped": skip,
        "error": err,
        "outputs": {"extracted_index_csv": safe_relpath(index_csv, run_dir)},
    }
    write_json(run_dir / "reports" / "step03_extract_summary.json", summary)

    log(f"ok={ok} skipped={skip} error={err}")
    log(f"wrote: {index_csv}")

    if err > 0 and (not args.allow_partial):
        fatal(f"Step3 failed for {err} rows (use --allow-partial to proceed)")

    log("OK")


if __name__ == "__main__":
    main()
