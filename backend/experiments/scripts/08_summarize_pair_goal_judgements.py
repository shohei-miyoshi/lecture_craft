# -*- coding: utf-8 -*-
"""
experiments/scripts/08_summarize_pair_goal_judgements.py
============================================================
Step8: Step6（pair_judgements）を Step9 で描きやすい CSV 群に整形する

なぜ作り直す？（今回の不具合の原因）
- Step6 の JSON は modality を 2つの観点に分解して出力する:
    - modality_audio_fitness
    - modality_visual_fitness
  一方で Step6 の pair_judgements.csv の keys 列には "modality" が入ることがある。
  keys をそのまま優先すると、JSON に存在しない "modality" を参照して winner が空欄になり得る。

本Step8の方針（Step6仕様に忠実）
- Step6 JSON の judgements を「そのまま」CSV化（key は JSON 側の実在キーを採用）
- keys 列に modality があれば、2キーに展開して扱う（空欄行を作らない）
- A/B の勝者（winner_raw=A/B/tie）を cond_id に直し（winner_cond）、
  さらに baseline vs 対抗馬（anchor vs other）に正規化（winner_rel=anchor/other/tie/unknown）
  ※ baseline が A でも B でも正しく判定可能

入力
- experiments/runs/<run_id>/analysis/pair_judgements.csv
- experiments/runs/<run_id>/analysis/pair_judgements/<model>/<lecture>/<pair_id>.json
- experiments/runs/<run_id>/config/experiment_config.json（run snapshot）

出力（Step9互換: step8_ready 配下にまとめる）
- experiments/runs/<run_id>/analysis/step8_ready/
    - pair_long_canon.csv
    - experiment_summary_by_key_overall.csv
    - experiment_summary_by_key_model.csv
    - lecture_breakdown_by_experiment.csv
    - model_agreement.csv
    - wins_only_long.csv      # ★見やすい勝敗表（long）
    - wins_only_wide.csv      # ★見やすい勝敗表（wide: モデル列展開）
    - inputs_detected.json

実行
  python experiments/scripts/08_summarize_pair_goal_judgements.py --run-id <run_id>

"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = PROJECT_ROOT / "experiments" / "runs"


# ============================================================
# small utils
# ============================================================
def log(msg: str) -> None:
    print(f"[Step8] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[Step8][WARN] {msg}", flush=True)


def die(msg: str) -> None:
    raise SystemExit(f"[Step8][FATAL] {msg}")


def read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(path: Path, fieldnames: List[str], rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def safe_float(x: Any, default: float = 0.0) -> float:
    try:
        s = str(x).strip()
        if s == "":
            return default
        return float(s)
    except Exception:
        return default


def safe_int(x: Any, default: int = 0) -> int:
    try:
        s = str(x).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default


def norm_lecture_name(name: str) -> str:
    # 文字化けしにくい程度の正規化（最小限）
    t = str(name or "").strip()
    if t.lower().endswith(".pdf"):
        t = t[:-4]
    return t


def split_keys(keys_field: str) -> List[str]:
    out: List[str] = []
    for k in (keys_field or "").split(","):
        kk = k.strip()
        if kk:
            out.append(kk)
    return out


# ============================================================
# Step6 spec alignment: key expansion
# ============================================================
MODALITY_EXPAND = ["modality_audio_fitness", "modality_visual_fitness"]


def expand_requested_keys(keys_csv: List[str]) -> List[str]:
    """
    Step6 CSV keys には 'modality' が入ることがあるが、
    Step6 JSON judgements は modality を 2つのキーに分解している。
    そこで 'modality' は 2キーに展開し、空欄行を作らない。
    """
    out: List[str] = []
    for k in keys_csv:
        if k == "modality":
            out.extend(MODALITY_EXPAND)
        else:
            out.append(k)
    # 重複除去（順序維持）
    seen = set()
    uniq: List[str] = []
    for k in out:
        if k not in seen:
            uniq.append(k)
            seen.add(k)
    return uniq


# ============================================================
# run config reading (for group naming)
# ============================================================
def load_run_config(run_dir: Path) -> Dict[str, Any]:
    cfg = run_dir / "config" / "experiment_config.json"
    if not cfg.exists():
        die(f"run config not found: {cfg}")
    return read_json(cfg)


def infer_experiment_group(pair_id: str, A: str, B: str) -> str:
    """
    ここは「卒論の章立てに直結するラベル」を固定化するため pair_id 優先。
    必要ならあなたの実験設計に合わせて増やしてください。
    """
    pid = str(pair_id or "").strip()

    if pid == "p11":
        return "1-1_baseline_anim_vs_summary_anim"
    if pid == "p12":
        return "1-2_baseline_anim_vs_detail_anim"
    if pid == "p21":
        return "2-1_baseline_anim_vs_intro_anim"
    if pid == "p22":
        return "2-2_baseline_anim_vs_advanced_anim"
    if pid == "p32":
        return "3-2_modality_baseline_anim_vs_baseline_audio"
    if pid == "p33":
        return "3-2_audio_baseline_vs_intro_audio"
    if pid == "p34":
        return "3-2_audio_baseline_vs_summary_audio"

    if pid in ("p41", "p42", "p43", "p44", "p51", "p52", "p53"):
        return f"4_combo_{pid}"

    return "other"


def group_major(group_id: str) -> str:
    if group_id.startswith("1-"):
        return "1"
    if group_id.startswith("2-"):
        return "2"
    if group_id.startswith("3-"):
        return "3"
    if group_id.startswith("4_") or group_id.startswith("4-"):
        return "4"
    return "other"


# ============================================================
# canonicalization: baseline vs opponent
# ============================================================
def build_canonical_axis(A_cond: str, B_cond: str) -> Tuple[str, str, str]:
    """
    anchor_cond / other_cond / comparison_id を決める。
    - baseline_* が入っていればそれを anchor（ベースライン）にする
    - baseline が無い場合は辞書順で anchor を固定（再現性）
    """
    A = str(A_cond or "").strip()
    B = str(B_cond or "").strip()

    def is_baseline(x: str) -> bool:
        return x.startswith("baseline_") or x == "baseline_anim" or x == "baseline_audio"

    if is_baseline(A) and not is_baseline(B):
        anchor, other = A, B
    elif is_baseline(B) and not is_baseline(A):
        anchor, other = B, A
    else:
        # baseline が両方/どちらも無い：安定のため辞書順
        if A <= B:
            anchor, other = A, B
        else:
            anchor, other = B, A

    comparison_id = f"{anchor}__vs__{other}"
    return anchor, other, comparison_id


def winner_ab_to_cond(winner_raw: str, A_cond: str, B_cond: str) -> str:
    w = str(winner_raw or "").strip()
    if w == "A":
        return str(A_cond or "").strip()
    if w == "B":
        return str(B_cond or "").strip()
    if w == "tie":
        return "tie"
    return "unknown"


def winner_cond_to_rel(winner_cond: str, anchor: str, other: str) -> str:
    if winner_cond == "tie":
        return "tie"
    if winner_cond == anchor:
        return "anchor"
    if winner_cond == other:
        return "other"
    return "unknown"


# ============================================================
# Step6 -> pair_long_canon
# ============================================================
PAIR_LONG_FIELDS = [
    "run_id",
    "model",
    "lecture",
    "lecture_norm",
    "pair_id",
    "experiment_group_id",
    "experiment_major",
    "key",
    "A_cond",
    "B_cond",
    "A_mode",
    "B_mode",
    "anchor_cond",
    "other_cond",
    "comparison_id",
    "winner_raw",
    "winner_cond",
    "winner_rel",
    "confidence",
    "reason",
    "ok",
    "error",
    "json_path",
    "timestamp",
]


def load_pair_long_canon(pair_csv: Path, allow_partial: bool) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    return: (pair_long_rows, error_rows)
    pair_long_rows: ok==1 の judgement を 1行ずつ
    error_rows: ok!=1 / json読めない 等を記録
    """
    rows = read_csv(pair_csv)
    if not rows:
        die(f"empty: {pair_csv}")

    out: List[Dict[str, Any]] = []
    errs: List[Dict[str, Any]] = []

    for r in rows:
        ok = str(r.get("ok", "")).strip()
        run_id = str(r.get("run_id", "")).strip()
        model = str(r.get("model", "")).strip()
        lecture = str(r.get("lecture", "")).strip()
        lecture_norm = norm_lecture_name(lecture)
        pair_id = str(r.get("pair_id", "")).strip()
        A_cond = str(r.get("A_cond", "")).strip()
        B_cond = str(r.get("B_cond", "")).strip()
        A_mode = str(r.get("A_mode", "")).strip()
        B_mode = str(r.get("B_mode", "")).strip()
        keys_csv_raw = split_keys(str(r.get("keys", "")).strip())
        keys_csv = expand_requested_keys(keys_csv_raw)
        err = str(r.get("error", "")).strip()
        json_path = str(r.get("json_path", "")).strip()
        timestamp = str(r.get("timestamp", "")).strip()

        group_id = infer_experiment_group(pair_id, A_cond, B_cond)
        major = group_major(group_id)

        # Step6 行が NG
        if ok != "1":
            errs.append({
                "run_id": run_id,
                "model": model,
                "lecture": lecture,
                "pair_id": pair_id,
                "error": err or "NOT_OK",
                "json_path": json_path,
                "timestamp": timestamp,
            })
            continue

        # JSON 読み
        jp = Path(json_path) if json_path else None
        if jp is None or not jp.exists():
            msg = f"JSON_NOT_FOUND:{json_path}"
            if not allow_partial:
                die(msg)
            errs.append({
                "run_id": run_id,
                "model": model,
                "lecture": lecture,
                "pair_id": pair_id,
                "error": msg,
                "json_path": json_path,
                "timestamp": timestamp,
            })
            continue

        try:
            payload = read_json(jp)
        except Exception as e:
            msg = f"JSON_READ_FAILED:{type(e).__name__}"
            if not allow_partial:
                die(f"{msg}: {jp}")
            errs.append({
                "run_id": run_id,
                "model": model,
                "lecture": lecture,
                "pair_id": pair_id,
                "error": msg,
                "json_path": str(jp),
                "timestamp": timestamp,
            })
            continue

        judgements = payload.get("judgements")
        if not isinstance(judgements, dict):
            msg = "JUDGEMENTS_MISSING_OR_NOT_DICT"
            if not allow_partial:
                die(f"{msg}: {jp}")
            errs.append({
                "run_id": run_id,
                "model": model,
                "lecture": lecture,
                "pair_id": pair_id,
                "error": msg,
                "json_path": str(jp),
                "timestamp": timestamp,
            })
            continue

        anchor, other, comparison_id = build_canonical_axis(A_cond, B_cond)

        # 採用するキー集合：
        # 1) keys_csv（ただし modality は 2キーへ展開済み）
        # 2) JSON 側に実在するキー（追加で落とさない）
        # ただし、最終的には JSON に存在するキーだけを出力（空欄行を作らない）
        keys_union: List[str] = []
        seen = set()
        for k in keys_csv + list(judgements.keys()):
            kk = str(k).strip()
            if not kk:
                continue
            if kk not in seen:
                keys_union.append(kk)
                seen.add(kk)

        for k in keys_union:
            if k not in judgements:
                # Step6 JSONに無いキーは出さない（空欄 winner を作らない）
                continue
            j = judgements.get(k, {})
            if not isinstance(j, dict):
                continue

            winner_raw = str(j.get("winner", "")).strip()
            conf = j.get("confidence", "")
            reason = str(j.get("reason", "")).strip()

            winner_cond = winner_ab_to_cond(winner_raw, A_cond, B_cond)
            winner_rel = winner_cond_to_rel(winner_cond, anchor, other)

            out.append({
                "run_id": run_id,
                "model": model,
                "lecture": lecture,
                "lecture_norm": lecture_norm,
                "pair_id": pair_id,
                "experiment_group_id": group_id,
                "experiment_major": major,
                "key": k,
                "A_cond": A_cond,
                "B_cond": B_cond,
                "A_mode": A_mode,
                "B_mode": B_mode,
                "anchor_cond": anchor,
                "other_cond": other,
                "comparison_id": comparison_id,
                "winner_raw": winner_raw,
                "winner_cond": winner_cond,
                "winner_rel": winner_rel,
                "confidence": conf,
                "reason": reason,
                "ok": "1",
                "error": "",
                "json_path": str(jp),
                "timestamp": timestamp,
            })

    return out, errs


# ============================================================
# aggregation (for Step9)
# ============================================================
def agg_pair(rows: List[Dict[str, Any]], group_keys: List[str]) -> List[Dict[str, Any]]:
    buckets: Dict[Tuple[str, ...], List[Dict[str, Any]]] = {}
    for r in rows:
        if str(r.get("ok", "")) != "1":
            continue
        key = str(r.get("key", "")).strip()
        if not key:
            continue
        gid = tuple(str(r.get(g, "")).strip() for g in group_keys)
        buckets.setdefault(gid, []).append(r)

    out: List[Dict[str, Any]] = []
    for gid, rs in sorted(buckets.items(), key=lambda x: x[0]):
        n = len(rs)
        anchor_win = sum(1 for r in rs if str(r.get("winner_rel", "")) == "anchor")
        other_win = sum(1 for r in rs if str(r.get("winner_rel", "")) == "other")
        tie = sum(1 for r in rs if str(r.get("winner_rel", "")) == "tie")
        confs = [safe_float(r.get("confidence", ""), 0.0) for r in rs]
        mean_conf = sum(confs) / len(confs) if confs else 0.0

        rec = {group_keys[i]: gid[i] for i in range(len(group_keys))}
        rec.update({
            "n": n,
            "anchor_win": anchor_win,
            "other_win": other_win,
            "tie": tie,
            "anchor_win_rate": round(anchor_win / n, 4) if n else 0.0,
            "other_win_rate": round(other_win / n, 4) if n else 0.0,
            "tie_rate": round(tie / n, 4) if n else 0.0,
            "mean_confidence": round(mean_conf, 4),
        })
        out.append(rec)
    return out


def model_agreement(pair_long: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    idx: Dict[Tuple[str, str, str, str], Dict[str, str]] = {}
    models_set = set()

    for r in pair_long:
        if str(r.get("ok", "")) != "1":
            continue
        lec = str(r.get("lecture_norm", "")).strip()
        pair_id = str(r.get("pair_id", "")).strip()
        key = str(r.get("key", "")).strip()
        comp = str(r.get("comparison_id", "")).strip()
        model = str(r.get("model", "")).strip()
        wrel = str(r.get("winner_rel", "")).strip()
        if not (lec and pair_id and key and comp and model and wrel):
            continue
        models_set.add(model)
        idx.setdefault((lec, pair_id, key, comp), {})[model] = wrel

    models = sorted(models_set)
    if len(models) < 2:
        return [{
            "model_A": models[0] if models else "",
            "model_B": "",
            "n_compared": 0,
            "n_agree": 0,
            "agreement_rate": 0.0,
        }]

    out: List[Dict[str, Any]] = []
    for i in range(len(models)):
        for j in range(i + 1, len(models)):
            mA, mB = models[i], models[j]
            n_comp = 0
            n_agree = 0
            for _, m2w in idx.items():
                if mA in m2w and mB in m2w:
                    n_comp += 1
                    if m2w[mA] == m2w[mB]:
                        n_agree += 1
            out.append({
                "model_A": mA,
                "model_B": mB,
                "n_compared": n_comp,
                "n_agree": n_agree,
                "agreement_rate": round(n_agree / n_comp, 4) if n_comp else 0.0,
            })
    return out


# ============================================================
# wins-only tables (readability)
# ============================================================
WINS_LONG_FIELDS = [
    # 見やすさ優先：ID類は後ろに寄せる
    "lecture_norm",
    "experiment_group_id",
    "key",
    "baseline_cond",
    "opponent_cond",
    "model",
    "winner_rel",
    # 補助（必要なら見る）
    "confidence",
    "pair_id",
    "comparison_id",
]


def build_wins_only_long(pair_long: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in pair_long:
        if str(r.get("ok", "")) != "1":
            continue
        out.append({
            "lecture_norm": str(r.get("lecture_norm", "")).strip(),
            "experiment_group_id": str(r.get("experiment_group_id", "")).strip(),
            "key": str(r.get("key", "")).strip(),
            "baseline_cond": str(r.get("anchor_cond", "")).strip(),
            "opponent_cond": str(r.get("other_cond", "")).strip(),
            "model": str(r.get("model", "")).strip(),
            "winner_rel": str(r.get("winner_rel", "")).strip(),
            "confidence": r.get("confidence", ""),
            "pair_id": str(r.get("pair_id", "")).strip(),
            "comparison_id": str(r.get("comparison_id", "")).strip(),
        })
    # stable sort
    out.sort(key=lambda x: (
        x.get("experiment_group_id", ""),
        x.get("lecture_norm", ""),
        x.get("key", ""),
        x.get("baseline_cond", ""),
        x.get("opponent_cond", ""),
        x.get("model", ""),
    ))
    return out


def build_wins_only_wide(wins_long: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    同一(lecture, group, key, baseline, opponent)に対して model 列を横持ち
    """
    models = sorted({str(r.get("model", "")).strip() for r in wins_long if str(r.get("model", "")).strip()})
    idx: Dict[Tuple[str, str, str, str, str], Dict[str, Any]] = {}

    for r in wins_long:
        lec = str(r.get("lecture_norm", "")).strip()
        g = str(r.get("experiment_group_id", "")).strip()
        key = str(r.get("key", "")).strip()
        base = str(r.get("baseline_cond", "")).strip()
        opp = str(r.get("opponent_cond", "")).strip()
        m = str(r.get("model", "")).strip()
        w = str(r.get("winner_rel", "")).strip()
        if not (lec and g and key and base and opp and m):
            continue

        k = (lec, g, key, base, opp)
        rec = idx.setdefault(k, {
            "lecture_norm": lec,
            "experiment_group_id": g,
            "key": key,
            "baseline_cond": base,
            "opponent_cond": opp,
        })
        rec[m] = w

    # majority
    out: List[Dict[str, Any]] = []
    for k, rec in sorted(idx.items(), key=lambda x: x[0]):
        votes = [str(rec.get(m, "")).strip() for m in models]
        votes = [v for v in votes if v in ("anchor", "other", "tie")]
        maj = "unknown"
        if votes:
            c_anchor = votes.count("anchor")
            c_other = votes.count("other")
            c_tie = votes.count("tie")
            mx = max(c_anchor, c_other, c_tie)
            cands = []
            if c_anchor == mx:
                cands.append("anchor")
            if c_other == mx:
                cands.append("other")
            if c_tie == mx:
                cands.append("tie")
            maj = cands[0] if len(cands) == 1 else "tie"  # 同率は tie 扱いに寄せる
        rec["majority"] = maj
        out.append(rec)

    fieldnames = ["lecture_norm", "experiment_group_id", "key", "baseline_cond", "opponent_cond"] + models + ["majority"]
    return out, fieldnames


# ============================================================
# main
# ============================================================
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--allow-partial", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    run_dir = RUNS_ROOT / args.run_id
    if not run_dir.exists():
        die(f"run_dir not found: {run_dir}")

    # inputs
    step6_csv = run_dir / "analysis" / "pair_judgements.csv"
    if not step6_csv.exists():
        die(f"input not found: {step6_csv}")

    # output dir (Step9 expects this)
    out_dir = run_dir / "analysis" / "step8_ready"
    out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------
    # Step6 -> long canon
    # ---------------------------------------------------------
    pair_long, err_rows = load_pair_long_canon(step6_csv, allow_partial=args.allow_partial)

    # Save pair_long_canon
    p_pair_long = out_dir / "pair_long_canon.csv"
    write_csv(p_pair_long, PAIR_LONG_FIELDS, pair_long)
    log(f"write: {p_pair_long} rows={len(pair_long)}")

    # Save errors (optional but useful)
    p_err = out_dir / "errors_step6_json.csv"
    if err_rows:
        err_fields = sorted({k for r in err_rows for k in r.keys()})
        write_csv(p_err, err_fields, err_rows)
        warn(f"write: {p_err} rows={len(err_rows)}")
    else:
        # 空でも header だけ出しておく
        write_csv(p_err, ["run_id", "model", "lecture", "pair_id", "error", "json_path", "timestamp"], [])
        log(f"write: {p_err} rows=0")

    # ---------------------------------------------------------
    # Aggregations for Step9
    # ---------------------------------------------------------
    exp_overall = agg_pair(pair_long, ["experiment_group_id", "key", "comparison_id", "anchor_cond", "other_cond"])
    p_exp_overall = out_dir / "experiment_summary_by_key_overall.csv"
    write_csv(p_exp_overall, list(exp_overall[0].keys()) if exp_overall else ["experiment_group_id", "key", "comparison_id", "anchor_cond", "other_cond", "n", "anchor_win", "other_win", "tie", "anchor_win_rate", "other_win_rate", "tie_rate", "mean_confidence"], exp_overall)
    log(f"write: {p_exp_overall} rows={len(exp_overall)}")

    exp_model = agg_pair(pair_long, ["experiment_group_id", "model", "key", "comparison_id", "anchor_cond", "other_cond"])
    p_exp_model = out_dir / "experiment_summary_by_key_model.csv"
    write_csv(p_exp_model, list(exp_model[0].keys()) if exp_model else ["experiment_group_id", "model", "key", "comparison_id", "anchor_cond", "other_cond", "n", "anchor_win", "other_win", "tie", "anchor_win_rate", "other_win_rate", "tie_rate", "mean_confidence"], exp_model)
    log(f"write: {p_exp_model} rows={len(exp_model)}")

    lecture_break = agg_pair(pair_long, ["experiment_group_id", "lecture_norm", "key", "comparison_id", "anchor_cond", "other_cond"])
    p_lecture = out_dir / "lecture_breakdown_by_experiment.csv"
    write_csv(p_lecture, list(lecture_break[0].keys()) if lecture_break else ["experiment_group_id", "lecture_norm", "key", "comparison_id", "anchor_cond", "other_cond", "n", "anchor_win", "other_win", "tie", "anchor_win_rate", "other_win_rate", "tie_rate", "mean_confidence"], lecture_break)
    log(f"write: {p_lecture} rows={len(lecture_break)}")

    agree = model_agreement(pair_long)
    p_agree = out_dir / "model_agreement.csv"
    write_csv(p_agree, list(agree[0].keys()) if agree else ["model_A", "model_B", "n_compared", "n_agree", "agreement_rate"], agree)
    log(f"write: {p_agree} rows={len(agree)}")

    # ---------------------------------------------------------
    # Readability tables (wins-only)
    # ---------------------------------------------------------
    wins_long = build_wins_only_long(pair_long)
    p_wins_long = out_dir / "wins_only_long.csv"
    write_csv(p_wins_long, WINS_LONG_FIELDS, wins_long)
    log(f"write: {p_wins_long} rows={len(wins_long)}")

    wins_wide, wins_wide_fields = build_wins_only_wide(wins_long)
    p_wins_wide = out_dir / "wins_only_wide.csv"
    write_csv(p_wins_wide, wins_wide_fields, wins_wide)
    log(f"write: {p_wins_wide} rows={len(wins_wide)}")

    # ---------------------------------------------------------
    # inputs_detected.json (for debugging / provenance)
    # ---------------------------------------------------------
    try:
        cfg = load_run_config(run_dir)
        condition_specs = cfg.get("condition_specs", {})
    except Exception as e:
        condition_specs = {"_error": str(e)}

    inputs = {
        "run_id": args.run_id,
        "step6_pair_judgements_csv": str(step6_csv),
        "step8_outputs": {
            "pair_long_canon": str(p_pair_long),
            "experiment_summary_by_key_overall": str(p_exp_overall),
            "experiment_summary_by_key_model": str(p_exp_model),
            "lecture_breakdown_by_experiment": str(p_lecture),
            "model_agreement": str(p_agree),
            "wins_only_long": str(p_wins_long),
            "wins_only_wide": str(p_wins_wide),
            "errors_step6_json": str(p_err),
        },
        "notes": {
            "modality_key_expansion": MODALITY_EXPAND,
            "winner_mapping": "winner_raw(A/B/tie)->winner_cond(cond_id)->winner_rel(anchor/other/tie)",
            "canonical_axis": "anchor=baseline if present else lexicographic stable",
        },
        "condition_specs_snapshot": condition_specs,
    }
    write_json(out_dir / "inputs_detected.json", inputs)
    log("write: inputs_detected.json")

    log("done.")


if __name__ == "__main__":
    main()
