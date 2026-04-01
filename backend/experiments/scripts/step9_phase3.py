# -*- coding: utf-8 -*-
"""
experiments/scripts/step9_phase3.py
============================================================
Phase3: trait win-rate + ties memo
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import step9_phase1 as common


def compute_trait_winrate(rows: List[Dict[str, str]], restrict_model: Optional[str] = None) -> List[Dict[str, Any]]:
    bucket: Dict[Tuple[str, str, str], Dict[str, int]] = {}

    for r in rows:
        if (r.get("ok") or "").strip() not in {"1", "true", "True"}:
            continue

        model = (r.get("model") or "").strip()
        if restrict_model is not None and model != restrict_model:
            continue

        g = (r.get("experiment_group_id") or "").strip()
        k = (r.get("key") or "").strip()
        if not (g and k and model):
            continue

        anchor = (r.get("anchor_cond") or "").strip()
        other = (r.get("other_cond") or "").strip()
        wrel = (r.get("winner_rel") or "").strip()

        side = common.which_side_has_trait(k, anchor, other)
        if side in {"unknown", "none", "both"}:
            continue

        trait_side = side
        non_side = "other" if trait_side == "anchor" else "anchor"

        key3 = (g, k, model)
        b = bucket.setdefault(key3, {"trait_win": 0, "non_trait_win": 0, "tie": 0})

        if wrel == "tie":
            b["tie"] += 1
        elif wrel == trait_side:
            b["trait_win"] += 1
        elif wrel == non_side:
            b["non_trait_win"] += 1

    out: List[Dict[str, Any]] = []
    for (g, k, m), b in bucket.items():
        n_decided = b["trait_win"] + b["non_trait_win"]  # tie除外
        rate = (b["trait_win"] / n_decided) if n_decided > 0 else ""
        out.append({
            "experiment_group_id": g,
            "key": k,
            "model": m,
            "trait_win": b["trait_win"],
            "non_trait_win": b["non_trait_win"],
            "tie": b["tie"],
            "n_decided": n_decided,
            "trait_win_rate": rate,
        })

    out.sort(key=lambda r: (r["model"], r["experiment_group_id"], r["key"]))
    return out


def plot_trait_winrate_figure(rows: List[Dict[str, Any]], out_png: common.Path, title: str) -> None:
    if not rows:
        common._log(f"[WARN] no winrate rows for: {title}")
        return
    groups = sorted({r["experiment_group_id"] for r in rows if r.get("experiment_group_id")})
    keys = sorted({r["key"] for r in rows if r.get("key")})

    series: Dict[str, List[Optional[float]]] = {k: [] for k in keys}
    for g in groups:
        for k in keys:
            hit = next((r for r in rows if r.get("experiment_group_id") == g and r.get("key") == k), None)
            series[k].append(common.safe_float(hit.get("trait_win_rate")) if hit else None)

    common.plot_grouped_bars(
        x_labels=groups,
        series=series,
        title=title,
        xlabel=common.PLOT.xlabel_group,
        ylabel=common.PLOT.ylabel_trait_win_rate,
        out_png=out_png,
    )


def plot_trait_winrate_figure_combined(rows_all: List[Dict[str, Any]], out_png: common.Path) -> None:
    if not rows_all:
        common._log("[WARN] no combined winrate rows")
        return

    models = sorted({r["model"] for r in rows_all if r.get("model")})
    groups = sorted({r["experiment_group_id"] for r in rows_all if r.get("experiment_group_id")})

    series: Dict[str, List[Optional[float]]] = {m: [] for m in models}
    for g in groups:
        for m in models:
            vals = [
                common.safe_float(r.get("trait_win_rate"))
                for r in rows_all
                if r.get("experiment_group_id") == g and r.get("model") == m
            ]
            vals2 = [v for v in vals if v is not None]
            series[m].append(common.mean(vals2) if vals2 else None)

    common.plot_grouped_bars(
        x_labels=groups,
        series=series,
        title=common.PLOT.title_trait_winrate_all_models,
        xlabel=common.PLOT.xlabel_group,
        ylabel=common.PLOT.ylabel_trait_win_rate,
        out_png=out_png,
    )


def phase3_trait_winrate(pair_rows: List[Dict[str, str]], out_root: common.Path, models: List[str]) -> None:
    p3 = out_root / "phase3_trait_winrate"
    common.ensure_dir(p3)
    common.ensure_dir(p3 / "tables")
    common.ensure_dir(p3 / "figs")

    ties = [
        {
            "experiment_group_id": (r.get("experiment_group_id") or "").strip(),
            "comparison_id": (r.get("comparison_id") or "").strip(),
            "model": (r.get("model") or "").strip(),
            "lecture_norm": common.normalize_lecture_name(r.get("lecture_norm") or r.get("lecture") or ""),
            "pair_id": (r.get("pair_id") or "").strip(),
            "key": (r.get("key") or "").strip(),
            "anchor_cond": (r.get("anchor_cond") or "").strip(),
            "other_cond": (r.get("other_cond") or "").strip(),
            "winner_rel": (r.get("winner_rel") or "").strip(),
        }
        for r in pair_rows
        if (r.get("ok") or "").strip() in {"1", "true", "True"} and (r.get("winner_rel") or "").strip() == "tie"
    ]
    common.write_csv(
        p3 / "tables" / "ties_long.csv",
        ties,
        fieldnames=["experiment_group_id", "comparison_id", "model", "lecture_norm", "pair_id", "key", "anchor_cond", "other_cond", "winner_rel"],
    )

    for m in models:
        rows_m = compute_trait_winrate(pair_rows, restrict_model=m)
        common.write_csv(
            p3 / "tables" / f"trait_winrate_{common.safe_slug(m)}.csv",
            rows_m,
            fieldnames=["experiment_group_id", "key", "model", "trait_win", "non_trait_win", "tie", "n_decided", "trait_win_rate"],
        )
        plot_trait_winrate_figure(
            rows_m,
            p3 / "figs" / f"trait_winrate_{common.safe_slug(m)}.png",
            title=common.PLOT.title_trait_winrate_model.format(model=m),
        )

    rows_all = compute_trait_winrate(pair_rows, restrict_model=None)
    common.write_csv(
        p3 / "tables" / "trait_winrate_all_models.csv",
        rows_all,
        fieldnames=["experiment_group_id", "key", "model", "trait_win", "non_trait_win", "tie", "n_decided", "trait_win_rate"],
    )
    plot_trait_winrate_figure_combined(rows_all, p3 / "figs" / "trait_winrate_all_models.png")
