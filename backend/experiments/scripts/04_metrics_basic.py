# experiments/scripts/04_metrics_basic.py
# ============================================================
# Step4: metrics_basic (index-driven, no pandas)
#
# 目的:
#   - Step3(extract) が生成した extracted/index.csv を唯一の入力として
#     各 lecture × cond の台本の機械的指標を計算する。
#
# 入力（唯一の真実）:
#   experiments/runs/<run_id>/extracted/index.csv
#   かつ index.csv が指す script_merged.txt / sentence_table.csv
#
# 出力:
#   experiments/runs/<run_id>/analysis/metrics_basic/metrics_basic.csv
#   experiments/runs/<run_id>/analysis/metrics_basic/metrics_basic_summary.json
#
# ポリシー:
#   - outputs/ など元データは見に行かない（探索禁止）
#   - index.csv で status=ok の行だけ計算する
#   - pandas 不要（標準ライブラリのみ）
#   - baseline差分を lecture単位で計算（animはbaseline_anim, audioはbaseline_audio）
#
# 追加（あなたの要望）:
#   - 取れる指標は「取れるだけ」取る（ただし index-driven は維持）
#   - 欠損/壊れに強く（--allow-partial なら落とさず続行）
# ============================================================

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any


# ----------------------------
# logging
# ----------------------------
def log(msg: str) -> None:
    print(f"[STEP4][metrics_basic] {msg}", flush=True)


def warn(msg: str) -> None:
    print(f"[STEP4][metrics_basic][WARN] {msg}", flush=True)


def fatal(msg: str, code: int = 1) -> None:
    print(f"[STEP4][metrics_basic][FATAL] {msg}", file=sys.stderr, flush=True)
    raise SystemExit(code)


# ----------------------------
# utils
# ----------------------------
def read_text_best_effort(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def safe_relpath(p: Path, base: Path) -> str:
    try:
        return str(p.resolve().relative_to(base.resolve())).replace("/", "\\")
    except Exception:
        return str(p)


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


# ----------------------------
# input row from extracted/index.csv
# ----------------------------
@dataclass(frozen=True)
class IndexRow:
    lecture_title: str
    cond_id: str
    status: str
    script_merged_txt: str
    sentence_table_csv: str
    mapping_normalized_json: str
    meta_json: str


def load_extracted_index(index_csv: Path) -> List[IndexRow]:
    rows: List[IndexRow] = []
    with index_csv.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for d in r:
            rows.append(IndexRow(
                lecture_title=str(d.get("lecture_title") or ""),
                cond_id=str(d.get("cond_id") or ""),
                status=str(d.get("status") or ""),
                script_merged_txt=str(d.get("script_merged_txt") or ""),
                sentence_table_csv=str(d.get("sentence_table_csv") or ""),
                mapping_normalized_json=str(d.get("mapping_normalized_json") or ""),
                meta_json=str(d.get("meta_json") or ""),
            ))
    return rows


# ----------------------------
# math/stat helpers
# ----------------------------
def mean(xs: List[float]) -> float:
    if not xs:
        return 0.0
    return sum(xs) / float(len(xs))


def stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = mean(xs)
    v = sum((x - m) ** 2 for x in xs) / float(len(xs) - 1)
    return math.sqrt(v)


def percentile(xs: List[float], q: float) -> float:
    """q in [0,1]. Simple nearest-rank-like with interpolation."""
    if not xs:
        return 0.0
    ys = sorted(xs)
    if q <= 0:
        return float(ys[0])
    if q >= 1:
        return float(ys[-1])
    pos = (len(ys) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(ys[lo])
    w = pos - lo
    return float(ys[lo]) * (1.0 - w) + float(ys[hi]) * w


def ratio(count: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return float(count) / float(total)


# ----------------------------
# regex sets (char-level)
# ----------------------------
_RE_ALNUM = re.compile(r"[A-Za-z0-9]")
_RE_ALPHA = re.compile(r"[A-Za-z]")
_RE_DIGIT = re.compile(r"[0-9]")
_RE_MATH = re.compile(r"[=+\-*/^<>≤≥≈≠∑∫√αβγδθλμσπ∞→←↔]")
_RE_BRACKET = re.compile(r"[\(\)\[\]{}（）［］｛｝]")
_RE_PUNCT = re.compile(r"[、。,.!?！？؛；:：…]")
_RE_NEWLINE = re.compile(r"\r?\n")

# Japanese scripts (rough but useful)
_RE_HIRAGANA = re.compile(r"[\u3040-\u309F]")
_RE_KATAKANA = re.compile(r"[\u30A0-\u30FF\u31F0-\u31FF]")
_RE_KANJI = re.compile(r"[\u4E00-\u9FFF]")
_RE_FULLWIDTH_ALNUM = re.compile(r"[０-９Ａ-Ｚａ-ｚ]")
_RE_SYMBOL = re.compile(r"[^\w\s\u3040-\u309F\u30A0-\u30FF\u31F0-\u31FF\u4E00-\u9FFF]")

# token-ish split
_RE_WORD = re.compile(r"[A-Za-z0-9]+|[\u3040-\u309F]+|[\u30A0-\u30FF\u31F0-\u31FF]+|[\u4E00-\u9FFF]+")


def tokenize(text: str) -> List[str]:
    return _RE_WORD.findall(text)


def ngrams(tokens: List[str], n: int) -> List[str]:
    if n <= 0 or len(tokens) < n:
        return []
    return [" ".join(tokens[i:i+n]) for i in range(0, len(tokens) - n + 1)]


# ----------------------------
# sentence_table.csv reader
# ----------------------------
def load_sentence_lengths(sentence_table_csv: Path) -> Tuple[List[int], int]:
    """
    sentence_table.csv から char_len を読む。
    戻り値: (lengths, rows_read)
    """
    lengths: List[int] = []
    rows_read = 0
    if not sentence_table_csv.exists():
        return lengths, 0

    with sentence_table_csv.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for d in r:
            rows_read += 1
            s = d.get("char_len")
            if s is None:
                continue
            try:
                lengths.append(int(s))
            except Exception:
                continue
    return lengths, rows_read


def load_sentence_texts(sentence_table_csv: Path) -> List[str]:
    """
    sentence_table.csv から text を読む（無ければ空）
    """
    if not sentence_table_csv.exists():
        return []
    out: List[str] = []
    with sentence_table_csv.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for d in r:
            t = d.get("text")
            if isinstance(t, str) and t.strip():
                out.append(t.strip())
            else:
                out.append("")
    return out


# ----------------------------
# modality + baseline mapping
# ----------------------------
def infer_modality(cond_id: str) -> str:
    return "audio" if cond_id.endswith("_audio") or "_audio" in cond_id else "animation"


def baseline_cond_for(cond_id: str) -> str:
    modality = infer_modality(cond_id)
    return "baseline_audio" if modality == "audio" else "baseline_anim"


# ----------------------------
# metrics (text + sentences)
# ----------------------------
def compute_metrics(
    script_text: str,
    sentence_lengths: List[int],
    sentence_texts: Optional[List[str]] = None,
) -> Dict[str, float]:
    text = script_text
    total_chars = len(text)

    # char counts
    alnum = len(_RE_ALNUM.findall(text))
    alpha = len(_RE_ALPHA.findall(text))
    digit = len(_RE_DIGIT.findall(text))
    mathsym = len(_RE_MATH.findall(text))
    brackets = len(_RE_BRACKET.findall(text))
    punct = len(_RE_PUNCT.findall(text))
    newlines = len(_RE_NEWLINE.findall(text))
    hira = len(_RE_HIRAGANA.findall(text))
    kata = len(_RE_KATAKANA.findall(text))
    kanji = len(_RE_KANJI.findall(text))
    fw_alnum = len(_RE_FULLWIDTH_ALNUM.findall(text))
    symbols = len(_RE_SYMBOL.findall(text))

    # sentence stats (from sentence_table char_len)
    sent_count = len(sentence_lengths)
    avg_sent_len = mean([float(x) for x in sentence_lengths])
    sd_sent_len = stdev([float(x) for x in sentence_lengths])
    p50_sent_len = percentile([float(x) for x in sentence_lengths], 0.50)
    p90_sent_len = percentile([float(x) for x in sentence_lengths], 0.90)
    p95_sent_len = percentile([float(x) for x in sentence_lengths], 0.95)
    max_sent_len = float(max(sentence_lengths) if sentence_lengths else 0)

    # token stats
    toks = tokenize(text)
    token_count = len(toks)
    uniq_tokens = len(set(toks)) if toks else 0

    # TTR variants
    ttr = ratio(uniq_tokens, max(token_count, 1))
    # root TTR (rough normalization)
    rttr = (uniq_tokens / math.sqrt(token_count)) if token_count > 0 else 0.0

    # repetition metrics
    # - duplicate sentence ratio (requires texts; fallback: based on lengths only -> skip)
    dup_sent_ratio = 0.0
    if sentence_texts is not None and sentence_texts:
        norm_sents = [re.sub(r"\s+", " ", s.strip()) for s in sentence_texts if s.strip()]
        if norm_sents:
            dup = len(norm_sents) - len(set(norm_sents))
            dup_sent_ratio = ratio(dup, len(norm_sents))

    # n-gram repetition (token-based)
    rep2 = 0.0
    rep3 = 0.0
    ng2 = ngrams(toks, 2)
    ng3 = ngrams(toks, 3)
    if ng2:
        rep2 = ratio(len(ng2) - len(set(ng2)), len(ng2))
    if ng3:
        rep3 = ratio(len(ng3) - len(set(ng3)), len(ng3))

    # structural-ish markers
    # - list/heading markers density
    #   examples: "1.", "1)", "・", "-", "—", "：" etc.
    line_starts = [ln.strip() for ln in re.split(r"\r?\n", text) if ln.strip()]
    bullet_like = 0
    for ln in line_starts:
        if re.match(r"^([\-–—・•●■]+)\s*", ln):
            bullet_like += 1
        elif re.match(r"^(\d+[\.\)]|\(\d+\)|[①-⑳])\s*", ln):
            bullet_like += 1
    bullet_line_ratio = ratio(bullet_like, len(line_starts)) if line_starts else 0.0

    # long token runs (latin) as "technical-ish" proxy
    long_latin_runs = len(re.findall(r"[A-Za-z]{6,}", text))

    # avoid division by 0
    denom_chars = max(total_chars, 1)

    return {
        # base char/sentence
        "script_char_len": float(total_chars),
        "sentence_count": float(sent_count),
        "avg_sentence_len": float(avg_sent_len),
        "sd_sentence_len": float(sd_sent_len),
        "p50_sentence_len": float(p50_sent_len),
        "p90_sentence_len": float(p90_sent_len),
        "p95_sentence_len": float(p95_sent_len),
        "max_sentence_len": float(max_sent_len),

        # ratios
        "punct_ratio": ratio(punct, denom_chars),
        "bracket_ratio": ratio(brackets, denom_chars),
        "newline_density": ratio(newlines, denom_chars),
        "alnum_ratio": ratio(alnum, denom_chars),
        "alpha_ratio": ratio(alpha, denom_chars),
        "digit_ratio": ratio(digit, denom_chars),
        "math_symbol_ratio": ratio(mathsym, denom_chars),
        "hiragana_ratio": ratio(hira, denom_chars),
        "katakana_ratio": ratio(kata, denom_chars),
        "kanji_ratio": ratio(kanji, denom_chars),
        "fullwidth_alnum_ratio": ratio(fw_alnum, denom_chars),
        "symbol_ratio": ratio(symbols, denom_chars),

        # token stats
        "token_count": float(token_count),
        "unique_token_count": float(uniq_tokens),
        "ttr": float(ttr),
        "rttr": float(rttr),

        # repetition
        "dup_sentence_ratio": float(dup_sent_ratio),
        "ngram2_repeat_ratio": float(rep2),
        "ngram3_repeat_ratio": float(rep3),

        # structure proxies
        "bullet_line_ratio": float(bullet_line_ratio),
        "long_latin_run_count": float(long_latin_runs),
    }


# ----------------------------
# main
# ----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True, help="experiment_run_id")
    ap.add_argument("--runs-root", default=str(Path("experiments") / "runs"), help="experiments/runs root")
    ap.add_argument("--allow-partial", action="store_true", help="some rows may fail but continue")
    ap.add_argument("--force", action="store_true", help="overwrite outputs")
    args = ap.parse_args()

    run_id = args.run_id
    run_dir = Path(args.runs_root) / run_id
    if not run_dir.exists():
        fatal(f"run_dir not found: {run_dir}")

    extracted_dir = run_dir / "extracted"
    index_csv = extracted_dir / "index.csv"
    if not index_csv.exists():
        fatal(f"extracted/index.csv not found: {index_csv} (did Step3 run?)")

    out_dir = run_dir / "analysis" / "metrics_basic"
    out_csv = out_dir / "metrics_basic.csv"
    out_summary = out_dir / "metrics_basic_summary.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    if out_csv.exists() and args.force:
        out_csv.unlink(missing_ok=True)
    if out_summary.exists() and args.force:
        out_summary.unlink(missing_ok=True)

    log(f"run_id={run_id}")
    log(f"extracted_dir={safe_relpath(extracted_dir, run_dir)}")

    idx_rows = load_extracted_index(index_csv)
    total = len(idx_rows)
    if total == 0:
        fatal("index.csv has 0 rows (nothing to compute)")

    # compute per row metrics (status=ok only)
    computed: List[dict] = []
    missing_script = 0
    missing_sentence = 0
    skipped_empty = 0
    error_rows = 0
    ok_rows = 0
    status_skipped = 0

    # store per lecture baselines later
    per_lecture: Dict[str, Dict[str, dict]] = {}  # lecture -> cond -> metrics_row

    for i, r in enumerate(idx_rows, start=1):
        if r.status != "ok":
            status_skipped += 1
            continue

        lecture = r.lecture_title
        cond = r.cond_id

        script_path = run_dir / Path(r.script_merged_txt)
        sent_path = run_dir / Path(r.sentence_table_csv)

        log(f"progress {i}/{total} lecture={lecture} cond={cond}")

        if not script_path.exists():
            missing_script += 1
            msg = f"missing script_merged.txt: {safe_relpath(script_path, run_dir)}"
            if args.allow_partial:
                warn(msg)
                continue
            fatal(msg)

        if not sent_path.exists():
            missing_sentence += 1
            msg = f"missing sentence_table.csv: {safe_relpath(sent_path, run_dir)}"
            if args.allow_partial:
                warn(msg)
                continue
            fatal(msg)

        try:
            text = read_text_best_effort(script_path)
            if len(text.strip()) == 0:
                skipped_empty += 1
                warn(f"empty script text -> skipped: lecture={lecture} cond={cond}")
                continue

            lengths, rows_read = load_sentence_lengths(sent_path)
            if rows_read == 0 or len(lengths) == 0:
                msg = f"sentence_table.csv has 0 rows: lecture={lecture} cond={cond}"
                if args.allow_partial:
                    warn(msg)
                    continue
                fatal(msg)

            # sentence texts are optional; use if present for duplicate sentence ratio
            sent_texts = load_sentence_texts(sent_path)

            m = compute_metrics(text, lengths, sentence_texts=sent_texts)

            row = {
                "run_id": run_id,
                "lecture_title": lecture,
                "cond_id": cond,
                "modality": infer_modality(cond),
                **m,
            }
            computed.append(row)
            ok_rows += 1
            per_lecture.setdefault(lecture, {})[cond] = row

        except Exception as e:
            error_rows += 1
            msg = f"failed compute: lecture={lecture} cond={cond} err={repr(e)}"
            if args.allow_partial:
                warn(msg)
                continue
            fatal(msg)

    # if nothing computed -> write summary then fatal
    if not computed:
        summary = {
            "run_id": run_id,
            "total_index_rows": total,
            "status_skipped_rows": status_skipped,
            "computed_metric_rows": 0,
            "missing_script_merged_txt": missing_script,
            "missing_sentence_table_csv": missing_sentence,
            "skipped_empty_script_text": skipped_empty,
            "error_rows": error_rows,
            "note": "no metrics rows computed (check Step3 outputs: extracted/index.csv and per-cond meta.json)",
            "inputs": {"index_csv": str(index_csv)},
            "outputs": {"metrics_basic_csv": str(out_csv), "metrics_basic_summary_json": str(out_summary)},
        }
        write_json(out_summary, summary)
        fatal("no metrics rows computed (check Step3 outputs)")

    # delta vs baseline
    METRIC_KEYS = [
        "script_char_len",
        "sentence_count",
        "avg_sentence_len",
        "sd_sentence_len",
        "p50_sentence_len",
        "p90_sentence_len",
        "p95_sentence_len",
        "max_sentence_len",
        "punct_ratio",
        "bracket_ratio",
        "newline_density",
        "alnum_ratio",
        "alpha_ratio",
        "digit_ratio",
        "math_symbol_ratio",
        "hiragana_ratio",
        "katakana_ratio",
        "kanji_ratio",
        "fullwidth_alnum_ratio",
        "symbol_ratio",
        "token_count",
        "unique_token_count",
        "ttr",
        "rttr",
        "dup_sentence_ratio",
        "ngram2_repeat_ratio",
        "ngram3_repeat_ratio",
        "bullet_line_ratio",
        "long_latin_run_count",
    ]

    for row in computed:
        lecture = row["lecture_title"]
        cond = row["cond_id"]
        base_cond = baseline_cond_for(cond)
        base = per_lecture.get(lecture, {}).get(base_cond)

        if base is None:
            row["baseline_cond_id"] = ""
            for k in METRIC_KEYS:
                row[f"delta_{k}"] = ""
            continue

        row["baseline_cond_id"] = base_cond
        for k in METRIC_KEYS:
            try:
                row[f"delta_{k}"] = float(row[k]) - float(base[k])
            except Exception:
                row[f"delta_{k}"] = ""

    # write CSV
    fields = [
        "run_id", "lecture_title", "cond_id", "modality", "baseline_cond_id",
        *METRIC_KEYS,
        *[f"delta_{k}" for k in METRIC_KEYS],
    ]

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in computed:
            w.writerow(r)

    summary = {
        "run_id": run_id,
        "total_index_rows": total,
        "status_skipped_rows": status_skipped,
        "computed_metric_rows": len(computed),
        "ok_rows": ok_rows,
        "missing_script_merged_txt": missing_script,
        "missing_sentence_table_csv": missing_sentence,
        "skipped_empty_script_text": skipped_empty,
        "error_rows": error_rows,
        "inputs": {
            "index_csv": str(index_csv),
        },
        "outputs": {
            "metrics_basic_csv": str(out_csv),
            "metrics_basic_summary_json": str(out_summary),
        },
        "policy": {
            "index_driven": True,
            "no_pandas": True,
            "trust_only_extracted": True,
            "fatal_on_error_by_default": (not args.allow_partial),
            "baseline_per_lecture": True,
        },
        "metric_keys": METRIC_KEYS,
    }
    write_json(out_summary, summary)

    log("summary:")
    log(f"  total index rows            = {total}")
    log(f"  status skipped rows         = {status_skipped}")
    log(f"  computed metric rows        = {len(computed)}")
    log(f"  missing script_merged.txt   = {missing_script}")
    log(f"  missing sentence_table.csv  = {missing_sentence}")
    log(f"  skipped empty script text   = {skipped_empty}")
    log(f"  error rows                  = {error_rows}")
    log(f"wrote: {safe_relpath(out_csv, run_dir)}")
    log(f"wrote: {safe_relpath(out_summary, run_dir)}")
    log("OK")


if __name__ == "__main__":
    main()
