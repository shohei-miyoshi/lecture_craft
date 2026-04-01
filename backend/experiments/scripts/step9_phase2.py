# -*- coding: utf-8 -*-
"""
experiments/scripts/step9_phase2.py
============================================================
Phase2: thesis metrics（trait deltas）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import step9_phase1 as common


def build_trait_delta_rows_step4(
    pair_rows: List[Dict[str, str]],
    step4: common.Step4Index,
    cols: List[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in pair_rows:
        if (r.get("ok") or "").strip() not in {"1", "true", "True"}:
            continue

        key = (r.get("key") or "").strip()
        anchor = (r.get("anchor_cond") or "").strip()
        other = (r.get("other_cond") or "").strip()
        lec = common.normalize_lecture_name(r.get("lecture_norm") or r.get("lecture") or "")
        if not (key and anchor and other and lec):
            continue

        side = common.which_side_has_trait(key, anchor, other)
        if side in {"unknown", "none", "both"}:
            continue

        trait_cond = anchor if side == "anchor" else other
        non_cond = other if side == "anchor" else anchor

        rec_t = step4.idx.get((lec, trait_cond), {})
        rec_n = step4.idx.get((lec, non_cond), {})

        row: Dict[str, Any] = {
            "experiment_group_id": (r.get("experiment_group_id") or "").strip(),
            "comparison_id": (r.get("comparison_id") or "").strip(),
            "key": key,
            "judge_model": (r.get("model") or "").strip(),
            "lecture": lec,
            "trait_cond": trait_cond,
            "non_trait_cond": non_cond,
        }

        for c in cols:
            vt = rec_t.get(c)
            vn = rec_n.get(c)
            row[f"delta__{c}"] = "" if (vt is None or vn is None) else (vt - vn)

        out.append(row)
    return out


def build_trait_delta_rows_step5(
    pair_rows: List[Dict[str, str]],
    step5: common.Step5Index,
    aspect_ids: List[str],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not step5.primary_models:
        return out

    use_model = step5.primary_models[0]  # Step5仕様: 多くの場合gpt-5のみ

    for r in pair_rows:
        if (r.get("ok") or "").strip() not in {"1", "true", "True"}:
            continue

        key = (r.get("key") or "").strip()
        anchor = (r.get("anchor_cond") or "").strip()
        other = (r.get("other_cond") or "").strip()
        lec = common.normalize_lecture_name(r.get("lecture_norm") or r.get("lecture") or "")
        if not (key and anchor and other and lec):
            continue

        side = common.which_side_has_trait(key, anchor, other)
        if side in {"unknown", "none", "both"}:
            continue

        trait_cond = anchor if side == "anchor" else other
        non_cond = other if side == "anchor" else anchor

        rec_t = step5.idx.get((use_model, lec, trait_cond), {})
        rec_n = step5.idx.get((use_model, lec, non_cond), {})

        row: Dict[str, Any] = {
            "experiment_group_id": (r.get("experiment_group_id") or "").strip(),
            "comparison_id": (r.get("comparison_id") or "").strip(),
            "key": key,
            "judge_model": (r.get("model") or "").strip(),
            "gpt_count_model": use_model,
            "lecture": lec,
            "trait_cond": trait_cond,
            "non_trait_cond": non_cond,
        }

        for aid in aspect_ids:
            col = f"aspect__{aid}"
            vt = rec_t.get(col)
            vn = rec_n.get(col)
            row[f"delta__{aid}"] = "" if (vt is None or vn is None) else (vt - vn)

        out.append(row)

    return out


def group_mean_delta(
    rows: List[Dict[str, Any]],
    group_keys: List[str],
    delta_cols: List[str],
) -> List[Dict[str, Any]]:
    bucket: Dict[Tuple[str, ...], Dict[str, List[float]]] = {}
    for r in rows:
        g = tuple((r.get(k) or "").strip() for k in group_keys)
        b = bucket.setdefault(g, {})
        for c in delta_cols:
            v = common.safe_float(r.get(c))
            if v is None:
                continue
            b.setdefault(c, []).append(v)

    out: List[Dict[str, Any]] = []
    for g, b in bucket.items():
        row: Dict[str, Any] = {k: g[i] for i, k in enumerate(group_keys)}
        for c in delta_cols:
            row[c] = common.mean(b.get(c, [])) if b.get(c) else ""
        row["n"] = max((len(b.get(delta_cols[0], [])) if delta_cols else 0), 0)
        out.append(row)

    out.sort(key=lambda r: tuple(str(r.get(k, "")) for k in group_keys))
    return out


def phase2_thesis_metrics(
    pair_rows: List[Dict[str, str]],
    step4: common.Step4Index,
    step5: common.Step5Index,
    out_root: common.Path,
) -> None:
    p2 = out_root / "phase2_thesis_metrics"
    common.ensure_dir(p2)

    # ---- Step4 deltas ----
    step4_focus = [c for c in ["script_char_len", "token_count", "sentence_count"] if c in step4.numeric_cols]
    if not step4_focus:
        step4_focus = step4.numeric_cols[:5]

    delta4 = build_trait_delta_rows_step4(pair_rows, step4, step4_focus)
    delta4_cols = [f"delta__{c}" for c in step4_focus]

    common.write_csv(
        p2 / "step4_trait_deltas_long.csv",
        delta4,
        fieldnames=[
            "experiment_group_id", "comparison_id", "key", "judge_model", "lecture",
            "trait_cond", "non_trait_cond"
        ] + delta4_cols,
    )

    agg4 = group_mean_delta(delta4, ["experiment_group_id", "key"], delta4_cols)
    common.write_csv(
        p2 / "step4_trait_deltas_mean_by_group_key.csv",
        agg4,
        fieldnames=["experiment_group_id", "key", "n"] + delta4_cols,
    )

    fig4 = p2 / "fig_step4_deltas"
    common.ensure_dir(fig4)

    for dc in delta4_cols:
        groups = sorted({r["experiment_group_id"] for r in agg4 if r.get("experiment_group_id")})
        keys = sorted({r["key"] for r in agg4 if r.get("key")})
        series: Dict[str, List[Optional[float]]] = {k: [] for k in keys}
        for g in groups:
            for k in keys:
                hit = next((r for r in agg4 if r.get("experiment_group_id") == g and r.get("key") == k), None)
                series[k].append(common.safe_float(hit.get(dc)) if hit else None)

        common.plot_grouped_bars(
            x_labels=groups,
            series=series,
            title=common.PLOT.title_step4_delta_grouped.format(delta_col=dc),
            xlabel=common.PLOT.xlabel_group,
            ylabel=dc,
            out_png=fig4 / f"mean_{dc}.png",
        )

    # ---- Step5 deltas ----
    if not step5.primary_models or not step5.aspect_ids:
        common._log("[WARN] Step5: no aspects/models -> skip Step5 thesis deltas.")
        return

    aspect_ids = step5.aspect_ids
    delta5 = build_trait_delta_rows_step5(pair_rows, step5, aspect_ids)
    delta5_cols = [f"delta__{aid}" for aid in aspect_ids]

    common.write_csv(
        p2 / "step5_trait_deltas_long.csv",
        delta5,
        fieldnames=[
            "experiment_group_id", "comparison_id", "key", "judge_model", "gpt_count_model",
            "lecture", "trait_cond", "non_trait_cond"
        ] + delta5_cols,
    )

    agg5 = group_mean_delta(delta5, ["experiment_group_id", "key", "gpt_count_model"], delta5_cols)
    common.write_csv(
        p2 / "step5_trait_deltas_mean_by_group_key_model.csv",
        agg5,
        fieldnames=["experiment_group_id", "key", "gpt_count_model", "n"] + delta5_cols,
    )

    # 図は上位だけ（見やすさ）
    fig5 = p2 / "fig_step5_deltas_top_aspects"
    common.ensure_dir(fig5)

    rep_model = step5.primary_models[0]
    rep_rows = [r for r in agg5 if (r.get("gpt_count_model") or "") == rep_model]

    scores: List[Tuple[str, float]] = []
    for aid in aspect_ids:
        c = f"delta__{aid}"
        vals = [common.safe_float(r.get(c)) for r in rep_rows]
        vals2 = [v for v in vals if v is not None]
        if not vals2:
            continue
        scores.append((aid, abs(sum(vals2) / len(vals2))))
    scores.sort(key=lambda x: x[1], reverse=True)
    top_aspects = [aid for (aid, _s) in scores[:common.PLOT.step5_top_aspects_in_phase2]]

    if not top_aspects:
        common._log("[WARN] Step5: no aspects to plot (all missing?)")
        return

    groups = sorted({r["experiment_group_id"] for r in rep_rows if r.get("experiment_group_id")})
    keys = sorted({r["key"] for r in rep_rows if r.get("key")})

    for aid in top_aspects:
        col = f"delta__{aid}"
        series2: Dict[str, List[Optional[float]]] = {k: [] for k in keys}
        for g in groups:
            for k in keys:
                hit = next((r for r in rep_rows if r.get("experiment_group_id") == g and r.get("key") == k), None)
                series2[k].append(common.safe_float(hit.get(col)) if hit else None)

        common.plot_grouped_bars(
            x_labels=groups,
            series=series2,
            title=common.PLOT.title_step5_delta_grouped.format(count_model=rep_model, aspect=aid),
            xlabel=common.PLOT.xlabel_group,
            ylabel="delta",
            out_png=fig5 / f"mean_{common.safe_slug(aid)}.png",
        )
