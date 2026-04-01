# -*- coding: utf-8 -*-
"""
experiments/scripts/step9_phase1.py
============================================================
Phase1 描画（付録向け raw）
+ Step9 共通ユーティリティ（Phase2/3もここをimportして使う）
"""

from __future__ import annotations

import csv
import json
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# ============================================================
# injected config (from 09_plot_pair_goal_judgements.py)
# ============================================================

PLOT: Any = None
METRIC_LABEL_OVERRIDES: Dict[str, str] = {}
COND_LABEL_OVERRIDES: Dict[str, str] = {}
EXPERIMENT_GROUP_LABEL_OVERRIDES: Dict[str, str] = {}


def configure(
    plot_config: Any,
    metric_label_overrides: Dict[str, str],
    cond_label_overrides: Dict[str, str],
    experiment_group_label_overrides: Dict[str, str],
) -> None:
    global PLOT, METRIC_LABEL_OVERRIDES, COND_LABEL_OVERRIDES, EXPERIMENT_GROUP_LABEL_OVERRIDES
    PLOT = plot_config
    METRIC_LABEL_OVERRIDES = dict(metric_label_overrides or {})
    COND_LABEL_OVERRIDES = dict(cond_label_overrides or {})
    EXPERIMENT_GROUP_LABEL_OVERRIDES = dict(experiment_group_label_overrides or {})


# ============================================================
# logging / misc
# ============================================================

def _log(msg: str) -> None:
    print(msg, flush=True)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def safe_slug(s: str, max_len: int = 100) -> str:
    s = str(s or "").strip()
    s = re.sub(r"[\\/:*?\"<>|]+", "_", s)
    s = re.sub(r"\s+", "_", s)
    s = s[:max_len]
    return s if s else "untitled"


def normalize_lecture_name(name: str) -> str:
    t = str(name or "").strip().replace("\\", "/")
    t = t.split("/")[-1].strip()
    if t.lower().endswith(".pdf"):
        t = t[:-4]
    return t.strip()


def safe_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if s == "" or s.lower() in {"nan", "none", "null"}:
        return None
    try:
        return float(s)
    except Exception:
        return None


def mean(vals: List[float]) -> Optional[float]:
    if not vals:
        return None
    return sum(vals) / float(len(vals))


def read_csv_rows(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"CSV not found: {path}")
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_csv(path: Path, rows: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


# ============================================================
# font
# ============================================================

def try_set_japanese_font() -> None:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")
    try:
        from matplotlib import font_manager
        available = {f.name for f in font_manager.fontManager.ttflist}
        chosen = None
        for fam in PLOT.font_preferred_families:
            if fam in available:
                chosen = fam
                break
        if chosen:
            plt.rcParams["font.family"] = [chosen]
            _log(f"[Step9] font selected: {chosen}")
        else:
            _log("[Step9][WARN] no preferred JP font found; using matplotlib default font.")
    except Exception as e:
        _log(f"[Step9][WARN] font selection failed: {e}")


# ============================================================
# column key detection
# ============================================================

def find_col_key(sample_row: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    if not sample_row:
        return None
    for k in candidates:
        if k in sample_row:
            return k
    low_map = {str(k).lower(): k for k in sample_row.keys()}
    for k in candidates:
        kk = str(k).lower()
        if kk in low_map:
            return low_map[kk]
    return None


# ============================================================
# label formatting helpers (cond / experiment_group_id)
# ============================================================

def format_cond_label(cond_id: str, fallback: str) -> str:
    cid = (cond_id or "").strip()
    if cid in COND_LABEL_OVERRIDES:
        return str(COND_LABEL_OVERRIDES[cid])
    return str(fallback or cid or "unknown")


def _wrap_each_line(s: str, width: int) -> str:
    if width <= 0:
        return s
    parts = str(s).split("\n")
    wrapped: List[str] = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        wrapped.append(textwrap.fill(p, width=width))
    return "\n".join(wrapped) if wrapped else s


def format_experiment_group_label(group_id: str) -> str:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")

    g = (group_id or "").strip()
    if g in EXPERIMENT_GROUP_LABEL_OVERRIDES:
        return str(EXPERIMENT_GROUP_LABEL_OVERRIDES[g])

    if not getattr(PLOT, "group_label_auto_prettify", True):
        return g

    s = g
    s = re.sub(r"^(\d+-\d+)_", r"\1\n", s)
    s = s.replace("_vs_", "\nvs\n")
    s = s.replace("_", " ")
    s = _wrap_each_line(s, getattr(PLOT, "group_label_wrap_at", 0))
    return s


# ============================================================
# cond order / label / baseline ids from run config
# ============================================================

@dataclass
class CondMeta:
    order: List[str]
    label: Dict[str, str]
    baseline_ids: Set[str]


def load_run_config(run_dir: Path) -> Optional[Dict[str, Any]]:
    p = run_dir / "config" / "experiment_config.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def resolve_cond_meta(cfg: Optional[Dict[str, Any]], cond_ids_fallback: Set[str]) -> CondMeta:
    order: List[str] = []
    label: Dict[str, str] = {}
    baseline_ids: Set[str] = set()

    if cfg:
        if isinstance(cfg.get("conditions"), list):
            for c in cfg["conditions"]:
                if not isinstance(c, dict):
                    continue
                cid = c.get("cond_id") or c.get("id")
                if not cid:
                    continue
                cid = str(cid)
                order.append(cid)
                lab = c.get("label") or c.get("name") or c.get("title") or cid
                label[cid] = str(lab)
                if c.get("is_baseline") is True:
                    baseline_ids.add(cid)

        if not order and isinstance(cfg.get("cond_specs"), dict):
            for cid, c in cfg["cond_specs"].items():
                cid = str(cid)
                order.append(cid)
                if isinstance(c, dict):
                    lab = c.get("label") or c.get("name") or c.get("title") or cid
                    if c.get("is_baseline") is True:
                        baseline_ids.add(cid)
                else:
                    lab = cid
                label[cid] = str(lab)

        bcid = cfg.get("baseline_cond_id")
        if bcid:
            baseline_ids.add(str(bcid))

    if not order:
        order = sorted(cond_ids_fallback)
        for cid in order:
            label[cid] = cid

    for cid in order:
        label.setdefault(cid, cid)

    if not baseline_ids:
        for cid in order:
            if "baseline" in cid.lower():
                baseline_ids.add(cid)

    # 方法B: cond_id 表示名の上書き
    for cid in list(order):
        label[cid] = format_cond_label(cid, label.get(cid, cid))

    return CondMeta(order=order, label=label, baseline_ids=baseline_ids)


# ============================================================
# modality classifier (Phase1用)
# ============================================================

def classify_modality_from_cond(cond_id: str) -> str:
    cid = (cond_id or "").lower()
    if "audio" in cid:
        return "audio"
    if "anim" in cid or "animation" in cid or "video" in cid:
        return "video"
    return "unknown"


def pick_baseline_for_group(cond_order: List[str], cond_ids: List[str], baseline_ids: Set[str]) -> Optional[str]:
    s = set(cond_ids)
    inter = [c for c in cond_order if c in s and c in baseline_ids]
    if inter:
        return inter[0]
    fallback = [c for c in cond_order if c in s and ("baseline" in c.lower())]
    if fallback:
        return fallback[0]
    return None


# ============================================================
# Step4 index (metrics_basic.csv)
# ============================================================

@dataclass
class Step4Index:
    idx: Dict[Tuple[str, str], Dict[str, float]]
    numeric_cols: List[str]
    col_lecture: str
    col_cond: str
    col_modality: Optional[str]
    modality_by_cond: Dict[str, str]


def build_step4_index(step4_rows: List[Dict[str, str]]) -> Step4Index:
    if not step4_rows:
        return Step4Index(
            idx={}, numeric_cols=[],
            col_lecture="lecture_title", col_cond="cond_id",
            col_modality=None, modality_by_cond={}
        )

    sample = step4_rows[0]
    col_lecture = find_col_key(sample, ["lecture_title", "lecture", "lecture_norm", "lecture_key"])
    col_cond = find_col_key(sample, ["cond_id", "cond"])
    col_modality = find_col_key(sample, ["modality"])
    if not col_lecture or not col_cond:
        raise ValueError("Step4 metrics_basic.csv: cannot find lecture_title / cond_id columns")

    exclude = {col_lecture, col_cond, "run_id", "baseline_cond_id", "timestamp", "model"}
    if col_modality:
        exclude.add(col_modality)
    cols = [c for c in sample.keys() if c not in exclude]

    numeric_cols: List[str] = []
    for c in cols:
        ok = False
        for r in step4_rows[:80]:
            if safe_float(r.get(c)) is not None:
                ok = True
                break
        if ok:
            numeric_cols.append(c)

    modality_by_cond: Dict[str, str] = {}
    bucket: Dict[Tuple[str, str], Dict[str, List[float]]] = {}

    for r in step4_rows:
        lec = normalize_lecture_name(r.get(col_lecture, "") or "")
        cid = (r.get(col_cond, "") or "").strip()
        if not lec or not cid:
            continue

        if cid not in modality_by_cond:
            if col_modality and (r.get(col_modality) or "").strip():
                m = (r.get(col_modality) or "").strip().lower()
                if "audio" in m:
                    modality_by_cond[cid] = "audio"
                elif "anim" in m or "animation" in m or "video" in m:
                    modality_by_cond[cid] = "video"
                else:
                    modality_by_cond[cid] = "unknown"
            else:
                modality_by_cond[cid] = classify_modality_from_cond(cid)

        key = (lec, cid)
        b = bucket.setdefault(key, {})
        for c in numeric_cols:
            v = safe_float(r.get(c))
            if v is None:
                continue
            b.setdefault(c, []).append(v)

    idx: Dict[Tuple[str, str], Dict[str, float]] = {}
    for k, b in bucket.items():
        out: Dict[str, float] = {}
        for c, vals in b.items():
            m = mean(vals)
            if m is None:
                continue
            out[c] = m
        idx[k] = out

    return Step4Index(
        idx=idx,
        numeric_cols=numeric_cols,
        col_lecture=col_lecture,
        col_cond=col_cond,
        col_modality=col_modality,
        modality_by_cond=modality_by_cond,
    )


# ============================================================
# Step5 index (gpt_counts.csv) long -> pivot
# ============================================================

@dataclass
class Step5Index:
    idx: Dict[Tuple[str, str, str], Dict[str, float]]
    aspect_ids: List[str]
    primary_models: List[str]
    col_model: str
    col_lecture: str
    col_cond: str
    col_aspect: str
    col_value: str


def build_step5_index(step5_rows: List[Dict[str, str]]) -> Step5Index:
    if not step5_rows:
        return Step5Index(
            idx={}, aspect_ids=[], primary_models=[],
            col_model="model", col_lecture="lecture_key", col_cond="cond_id",
            col_aspect="aspect_id", col_value="value",
        )

    sample = step5_rows[0]
    col_model = find_col_key(sample, ["model"])
    col_lecture = find_col_key(sample, ["lecture_key", "lecture_title", "lecture", "lecture_norm"])
    col_cond = find_col_key(sample, ["cond_id", "cond"])
    col_aspect = find_col_key(sample, ["aspect_id", "aspect"])
    col_value = find_col_key(sample, ["value"])
    col_ok = find_col_key(sample, ["ok"])

    if not (col_model and col_lecture and col_cond and col_aspect and col_value):
        raise ValueError("Step5 gpt_counts.csv: missing required columns (model/lecture_key/cond_id/aspect_id/value)")

    bucket: Dict[Tuple[str, str, str, str], List[float]] = {}
    aspect_set: Set[str] = set()
    model_set: Set[str] = set()

    for r in step5_rows:
        if col_ok:
            okv = (r.get(col_ok, "") or "").strip()
            if okv not in {"1", "true", "True"}:
                continue

        m = (r.get(col_model, "") or "").strip()
        lec = normalize_lecture_name(r.get(col_lecture, "") or "")
        cid = (r.get(col_cond, "") or "").strip()
        aid = (r.get(col_aspect, "") or "").strip()
        v = safe_float(r.get(col_value))
        if not (m and lec and cid and aid):
            continue
        if v is None:
            continue

        model_set.add(m)
        aspect_set.add(aid)
        bucket.setdefault((m, lec, cid, aid), []).append(v)

    idx: Dict[Tuple[str, str, str], Dict[str, float]] = {}
    for (m, lec, cid, aid), vals in bucket.items():
        mv = mean(vals)
        if mv is None:
            continue
        rec = idx.setdefault((m, lec, cid), {})
        rec[f"aspect__{aid}"] = mv

    return Step5Index(
        idx=idx,
        aspect_ids=sorted(aspect_set),
        primary_models=sorted(model_set),
        col_model=col_model,
        col_lecture=col_lecture,
        col_cond=col_cond,
        col_aspect=col_aspect,
        col_value=col_value,
    )


# ============================================================
# Step8 pair_long_canon loader
# ============================================================

@dataclass
class PairLong:
    rows: List[Dict[str, str]]
    cond_ids: Set[str]
    models: Set[str]
    keys: Set[str]
    experiment_groups: Set[str]


def load_pair_long(pair_path: Path) -> PairLong:
    rows = read_csv_rows(pair_path)
    cond_ids: Set[str] = set()
    models: Set[str] = set()
    keys: Set[str] = set()
    groups: Set[str] = set()

    for r in rows:
        a = (r.get("anchor_cond") or "").strip()
        b = (r.get("other_cond") or "").strip()
        if a:
            cond_ids.add(a)
        if b:
            cond_ids.add(b)

        m = (r.get("model") or "").strip()
        if m:
            models.add(m)

        k = (r.get("key") or "").strip()
        if k:
            keys.add(k)

        g = (r.get("experiment_group_id") or "").strip()
        if g:
            groups.add(g)

        if not (r.get("lecture_norm") or "").strip():
            r["lecture_norm"] = normalize_lecture_name(r.get("lecture") or "")

        if not (r.get("comparison_id") or "").strip():
            if a and b:
                r["comparison_id"] = f"{a}__vs__{b}"

    return PairLong(rows=rows, cond_ids=cond_ids, models=models, keys=keys, experiment_groups=groups)


# ============================================================
# key -> trait 判定（Step6/Step8仕様を考慮）
# ============================================================

def infer_cond_traits(cond_id: str) -> Dict[str, bool]:
    cid = (cond_id or "").lower()
    return {
        "summary": ("summary" in cid),
        "detail": ("detail" in cid),
        "intro": ("intro" in cid or "beginner" in cid or "basic" in cid),
        "advanced": ("advanced" in cid),
        "audio": ("audio" in cid),
        "animation": ("anim" in cid or "animation" in cid),
    }


def trait_name_from_key(key: str) -> Optional[str]:
    k = (key or "").strip().lower()
    if k == "modality_audio_fitness":
        return "audio"
    if k == "modality_visual_fitness":
        return "animation"
    if k in {"summary", "detail", "intro", "advanced", "audio", "animation"}:
        return k
    return None


def which_side_has_trait(key: str, anchor_cond: str, other_cond: str) -> str:
    tname = trait_name_from_key(key)
    if not tname:
        return "unknown"

    a = infer_cond_traits(anchor_cond)
    b = infer_cond_traits(other_cond)
    ta = bool(a.get(tname, False))
    tb = bool(b.get(tname, False))

    if ta and not tb:
        return "anchor"
    if tb and not ta:
        return "other"
    if ta and tb:
        return "both"
    return "none"


# ============================================================
# Plot helpers（設定ブロックで見た目調整可能）
# ============================================================

def _metric_label(col: str) -> str:
    return METRIC_LABEL_OVERRIDES.get(col, col)


def _to_plot_value(v: Optional[float]) -> float:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")
    if v is None:
        return float("nan") if PLOT.missing_bar_policy == "nan" else 0.0
    return float(v)


def _figsize_for_nbars(n: int) -> Tuple[float, float]:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")
    w = max(PLOT.fig_width_min, PLOT.fig_width_per_bar * max(1, n))
    return (w, PLOT.fig_height)


def plot_bar_simple_with_baseline(
    labels: List[str],
    values: List[Optional[float]],
    baseline_flags: List[bool],
    title: str,
    xlabel: str,
    ylabel: str,
    out_png: Path,
) -> None:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")

    ensure_dir(out_png.parent)

    miss = sum(1 for v in values if v is None)
    v2 = [_to_plot_value(v) for v in values]
    n = len(labels)

    plt.figure(figsize=_figsize_for_nbars(n))
    plt.bar(range(n), v2)

    base_x = [i for i, f in enumerate(baseline_flags) if f]
    base_y = [v2[i] for i in base_x]
    if base_x:
        plt.bar(base_x, base_y, color=PLOT.baseline_color, label=PLOT.baseline_legend_label)

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(range(n), labels, rotation=PLOT.xtick_rotation, ha="right")
    if base_x:
        plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=PLOT.dpi)
    plt.close()

    if miss > 0 and PLOT.missing_bar_policy == "nan":
        _log(f"[WARN] {out_png.name}: {miss}/{n} values missing -> plotted as NaN (no bar)")


def plot_grouped_bars(
    x_labels: List[str],
    series: Dict[str, List[Optional[float]]],
    title: str,
    xlabel: str,
    ylabel: str,
    out_png: Path,
) -> None:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")

    ensure_dir(out_png.parent)
    keys = list(series.keys())
    if not keys:
        return

    n = len(x_labels)
    m = len(keys)

    w = max(10.0, PLOT.fig_width_per_group * max(1, n))
    h = 5.2
    plt.figure(figsize=(w, h))

    x = list(range(n))
    total_width = PLOT.grouped_total_width
    bar_w = total_width / max(1, m)
    offset0 = -total_width / 2 + bar_w / 2

    for i, k in enumerate(keys):
        vals2 = [_to_plot_value(v) for v in series[k]]
        offs = offset0 + i * bar_w
        xs = [xx + offs for xx in x]
        plt.bar(xs, vals2, width=bar_w, label=k)

    x_disp = [format_experiment_group_label(g) for g in x_labels]

    plt.title(title)
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.xticks(x, x_disp, rotation=min(30, PLOT.xtick_rotation), ha="right")
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png, dpi=PLOT.dpi)
    plt.close()


# ============================================================
# PHASE 1: Step4/5 raw plots（audio/video分離 + baseline色 + 増加率）
# ============================================================

def _cond_ids_by_modality(cond_order: List[str], modality_map: Dict[str, str]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {"audio": [], "video": [], "unknown": []}
    for cid in cond_order:
        m = modality_map.get(cid) or classify_modality_from_cond(cid)
        if m not in out:
            m = "unknown"
        out[m].append(cid)
    return out


def _increase_rate(v: Optional[float], base: Optional[float]) -> Optional[float]:
    if v is None or base is None:
        return None
    if base == 0:
        return None
    return (v - base) / base * 100.0


def phase1_appendix_raw(
    step4: Step4Index,
    step5: Step5Index,
    out_root: Path,
    cond_meta: CondMeta,
    max_raw_aspects: int = 12,
) -> None:
    if PLOT is None:
        raise RuntimeError("step9_phase1: configure() not called (PLOT is None).")

    p1 = out_root / "phase1_appendix_raw"
    ensure_dir(p1)

    modality_by_cond: Dict[str, str] = {}
    for cid in cond_meta.order:
        modality_by_cond[cid] = step4.modality_by_cond.get(cid, classify_modality_from_cond(cid))

    conds_by_mod = _cond_ids_by_modality(cond_meta.order, modality_by_cond)

    # -----------------------
    # Step4 raw
    # -----------------------
    p4 = p1 / "step4_metrics_basic"
    ensure_dir(p4)

    lectures = sorted({lec for (lec, _cid) in step4.idx.keys()})
    _log(f"[Step4] detected cols: lecture='{step4.col_lecture}' cond='{step4.col_cond}'")
    _log(f"[Step4] lectures={len(lectures)} numeric_cols={len(step4.numeric_cols)} rows={len(step4.idx)}")

    step4_plot_cols = [c for c in PLOT.step4_focus_metrics if c in step4.numeric_cols]
    if not step4_plot_cols:
        step4_plot_cols = step4.numeric_cols[:6]

    for mod in ["audio", "video", "unknown"]:
        mod_conds = conds_by_mod.get(mod, [])
        if not mod_conds:
            continue

        base_cid = pick_baseline_for_group(cond_meta.order, mod_conds, cond_meta.baseline_ids)
        _log(f"[Step4][Phase1] modality={mod} conds={len(mod_conds)} baseline={base_cid}")

        by_lec_dir = p4 / f"by_modality_{mod}" / "by_lecture"
        ensure_dir(by_lec_dir)

        for lec in lectures:
            lec_dir = by_lec_dir / safe_slug(lec)
            ensure_dir(lec_dir)

            for col in step4_plot_cols:
                labels = [cond_meta.label[c] for c in mod_conds]
                vals: List[Optional[float]] = []
                base_flags: List[bool] = []
                for cid in mod_conds:
                    rec = step4.idx.get((lec, cid), {})
                    vals.append(rec.get(col))
                    base_flags.append(cid == base_cid)

                metric_disp = _metric_label(col)

                plot_bar_simple_with_baseline(
                    labels=labels,
                    values=vals,
                    baseline_flags=base_flags,
                    title=PLOT.title_step4_raw.format(lecture=lec, mod=mod, metric=metric_disp),
                    xlabel=PLOT.xlabel_cond,
                    ylabel=metric_disp,
                    out_png=lec_dir / f"raw_{col}.png",
                )

                if base_cid:
                    base_v = step4.idx.get((lec, base_cid), {}).get(col)
                    rates = [_increase_rate(v, base_v) for v in vals]
                    plot_bar_simple_with_baseline(
                        labels=labels,
                        values=rates,
                        baseline_flags=base_flags,
                        title=PLOT.title_step4_inc.format(lecture=lec, mod=mod, metric=metric_disp),
                        xlabel=PLOT.xlabel_cond,
                        ylabel=PLOT.ylabel_increase_rate,
                        out_png=lec_dir / f"increase_rate_{col}.png",
                    )

        overall_dir = p4 / f"by_modality_{mod}" / "overall_mean_by_cond"
        ensure_dir(overall_dir)

        for col in step4_plot_cols:
            vals_by_cond: Dict[str, List[float]] = {cid: [] for cid in mod_conds}
            for (lec, cid), rec in step4.idx.items():
                if cid not in vals_by_cond:
                    continue
                v = rec.get(col)
                if v is not None:
                    vals_by_cond[cid].append(v)

            labels = [cond_meta.label[c] for c in mod_conds]
            vals_mean = [mean(vals_by_cond[cid]) for cid in mod_conds]
            base_flags = [(cid == base_cid) for cid in mod_conds]

            metric_disp = _metric_label(col)

            plot_bar_simple_with_baseline(
                labels=labels,
                values=vals_mean,
                baseline_flags=base_flags,
                title=PLOT.title_step4_mean.format(mod=mod, metric=metric_disp),
                xlabel=PLOT.xlabel_cond,
                ylabel=metric_disp,
                out_png=overall_dir / f"mean_{col}.png",
            )

            if base_cid:
                base_mean = vals_mean[mod_conds.index(base_cid)] if base_cid in mod_conds else None
                inc_mean = [_increase_rate(v, base_mean) for v in vals_mean]
                plot_bar_simple_with_baseline(
                    labels=labels,
                    values=inc_mean,
                    baseline_flags=base_flags,
                    title=PLOT.title_step4_mean_inc.format(mod=mod, metric=metric_disp),
                    xlabel=PLOT.xlabel_cond,
                    ylabel=PLOT.ylabel_increase_rate,
                    out_png=overall_dir / f"increase_rate_mean_{col}.png",
                )

    # -----------------------
    # Step5 raw
    # -----------------------
    p5 = p1 / "step5_gpt_counts"
    ensure_dir(p5)

    _log(
        f"[Step5] detected cols: model='{step5.col_model}' lecture='{step5.col_lecture}' "
        f"cond='{step5.col_cond}' aspect='{step5.col_aspect}' value='{step5.col_value}'"
    )
    _log(f"[Step5] models={step5.primary_models} aspects={len(step5.aspect_ids)} rows={len(step5.idx)}")

    aspect_ids = step5.aspect_ids[:max_raw_aspects]

    for m in step5.primary_models:
        mdir = p5 / f"by_model_{safe_slug(m)}"
        ensure_dir(mdir)

        lectures5 = sorted({lec for (mm, lec, _cid) in step5.idx.keys() if mm == m})

        for mod in ["audio", "video", "unknown"]:
            mod_conds = conds_by_mod.get(mod, [])
            if not mod_conds:
                continue
            base_cid = pick_baseline_for_group(cond_meta.order, mod_conds, cond_meta.baseline_ids)
            _log(f"[Step5][Phase1] model={m} modality={mod} conds={len(mod_conds)} baseline={base_cid}")

            by_lec_dir5 = mdir / f"by_modality_{mod}" / "by_lecture"
            ensure_dir(by_lec_dir5)

            for lec in lectures5:
                lec_dir = by_lec_dir5 / safe_slug(lec)
                ensure_dir(lec_dir)

                for aid in aspect_ids:
                    col = f"aspect__{aid}"
                    labels = [cond_meta.label[c] for c in mod_conds]
                    vals: List[Optional[float]] = []
                    base_flags: List[bool] = []
                    for cid in mod_conds:
                        rec = step5.idx.get((m, lec, cid), {})
                        vals.append(rec.get(col))
                        base_flags.append(cid == base_cid)

                    plot_bar_simple_with_baseline(
                        labels=labels,
                        values=vals,
                        baseline_flags=base_flags,
                        title=PLOT.title_step5_raw.format(model=m, lecture=lec, mod=mod, aspect=aid),
                        xlabel=PLOT.xlabel_cond,
                        ylabel=PLOT.ylabel_value,
                        out_png=lec_dir / f"raw_{safe_slug(aid)}.png",
                    )

                    if base_cid:
                        base_v = step5.idx.get((m, lec, base_cid), {}).get(col)
                        rates = [_increase_rate(v, base_v) for v in vals]
                        plot_bar_simple_with_baseline(
                            labels=labels,
                            values=rates,
                            baseline_flags=base_flags,
                            title=PLOT.title_step5_inc.format(model=m, lecture=lec, mod=mod, aspect=aid),
                            xlabel=PLOT.xlabel_cond,
                            ylabel=PLOT.ylabel_increase_rate,
                            out_png=lec_dir / f"increase_rate_{safe_slug(aid)}.png",
                        )

            overall_dir5 = mdir / f"by_modality_{mod}" / "overall_mean_by_cond"
            ensure_dir(overall_dir5)

            for aid in aspect_ids:
                col = f"aspect__{aid}"
                vals_by_cond: Dict[str, List[float]] = {cid: [] for cid in mod_conds}
                for (mm, lec, cid), rec in step5.idx.items():
                    if mm != m or cid not in vals_by_cond:
                        continue
                    v = rec.get(col)
                    if v is not None:
                        vals_by_cond[cid].append(v)

                labels = [cond_meta.label[c] for c in mod_conds]
                vals_mean = [mean(vals_by_cond[cid]) for cid in mod_conds]
                base_flags = [(cid == base_cid) for cid in mod_conds]

                plot_bar_simple_with_baseline(
                    labels=labels,
                    values=vals_mean,
                    baseline_flags=base_flags,
                    title=PLOT.title_step5_mean.format(model=m, mod=mod, aspect=aid),
                    xlabel=PLOT.xlabel_cond,
                    ylabel=PLOT.ylabel_value,
                    out_png=overall_dir5 / f"mean_{safe_slug(aid)}.png",
                )

                if base_cid:
                    base_mean = vals_mean[mod_conds.index(base_cid)] if base_cid in mod_conds else None
                    inc_mean = [_increase_rate(v, base_mean) for v in vals_mean]
                    plot_bar_simple_with_baseline(
                        labels=labels,
                        values=inc_mean,
                        baseline_flags=base_flags,
                        title=PLOT.title_step5_mean_inc.format(model=m, mod=mod, aspect=aid),
                        xlabel=PLOT.xlabel_cond,
                        ylabel=PLOT.ylabel_increase_rate,
                        out_png=overall_dir5 / f"increase_rate_mean_{safe_slug(aid)}.png",
                    )
