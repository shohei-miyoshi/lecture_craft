# experiments/scripts/05_metrics_gpt_counts.py
# ============================================================
# Step5: LLMによる定量的カウント/スコア（GPT-5固定）  ※評価ステップ
#
# 【仕様（重要）】
# - Step5は GPT-5 のみを使用（run config の judge_models 等は無視）
# - 評価指標(aspects)は全run共通カタログに集約：
#     experiments/config/gpt_aspects.json  ←唯一のソース
# - 実験条件（manifest/dest等）は run-snapshot を参照：
#     experiments/runs/<run_id>/...
#
# - Step5は auto_lecture.gpt_client に依存しない（独自にOpenAI client）
# - APIキーは以下の優先順位で取得（値は表示しない）：
#     1) 環境変数 OPENAI_API_KEY
#     2) apikey.txt（プロジェクトルート既定、または --apikey 指定）
#
# - Step4の出力は参照しない（Step4はStep9専用）
# - outputs/探索はしない：Step2 manifest の dest（output_root）だけ参照
#
# 【入力】
# - runs/<run_id>/config/experiment_config.json
# - runs/<run_id>/generation/manifest_step02.jsonl
# - experiments/config/gpt_aspects.json
# - apikey.txt（任意）
#
# 【出力】
# - runs/<run_id>/analysis/gpt_counts.csv
# - runs/<run_id>/analysis/gpt_counts/gpt-5/<lecture>/<cond>/<aspect>.json
# ============================================================

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI


# ----------------------------
# Paths
# ----------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]               # .../auto_lecture
RUNS_ROOT = PROJECT_ROOT / "experiments" / "runs"
ASPECTS_CATALOG_DEFAULT = PROJECT_ROOT / "experiments" / "config" / "gpt_aspects.json"
APIKEY_DEFAULT = PROJECT_ROOT / "apikey.txt"

# ----------------------------
# Model (fixed)
# ----------------------------
MODEL_FIXED = "gpt-5"


# ----------------------------
# Helpers
# ----------------------------
def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime())


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def read_text_best_effort(path: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            return path.read_text(encoding=enc)
        except Exception:
            continue
    return path.read_text(errors="ignore")


def sanitize_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", s).strip()


def warn_long_text(text: str, lecture_key: str, cond_id: str, threshold_chars: int = 20000) -> Optional[str]:
    if len(text) >= threshold_chars:
        return f"LONG_TEXT_WARN chars={len(text)} lecture={lecture_key} cond={cond_id} threshold={threshold_chars}"
    return None


def extract_first_json_object(s: str) -> Optional[Dict[str, Any]]:
    if not s:
        return None

    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, flags=re.DOTALL | re.IGNORECASE)
    candidates: List[str] = []
    if m:
        candidates.append(m.group(1))

    for m2 in re.finditer(r"(\{.*?\})", s, flags=re.DOTALL):
        candidates.append(m2.group(1))

    for cand in candidates:
        cand = cand.strip()
        try:
            return json.loads(cand)
        except Exception:
            continue
    return None


# ----------------------------
# API Key handling (safe)
# ----------------------------
def load_api_key_from_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"apikey file not found: {path}")
    key = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not key:
        raise RuntimeError(f"apikey file is empty: {path}")
    return key


def get_api_key(apikey_path: Optional[Path]) -> str:
    env = os.environ.get("OPENAI_API_KEY", "").strip()
    if env:
        return env

    path = apikey_path if apikey_path is not None else APIKEY_DEFAULT
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()

    return load_api_key_from_file(path)


def create_step5_client(apikey_path: Optional[Path]) -> OpenAI:
    api_key = get_api_key(apikey_path)
    return OpenAI(api_key=api_key)


# ----------------------------
# Aspects catalog (single source of truth)
# ----------------------------
@dataclass
class CatalogAspect:
    name: str
    type: str          # "count" or "score_1_5" ...
    definition: str


def load_aspects_catalog(path: Path) -> List[CatalogAspect]:
    if not path.exists():
        raise FileNotFoundError(f"gpt_aspects.json not found: {path}")
    obj = read_json(path)
    raw = obj.get("aspects", [])
    if not isinstance(raw, list):
        raise RuntimeError(f"gpt_aspects.json invalid format (aspects is not list): {path}")

    out: List[CatalogAspect] = []
    for a in raw:
        if not isinstance(a, dict):
            continue
        name = str(a.get("name", "")).strip()
        typ = str(a.get("type", "")).strip()
        definition = str(a.get("definition", "")).strip()
        if not name or not typ:
            continue
        out.append(CatalogAspect(name=name, type=typ, definition=definition))
    return out


def filter_aspects(
    aspects: List[CatalogAspect],
    only_names: List[str],
    only_types: List[str],
) -> List[CatalogAspect]:
    out = aspects
    if only_names:
        s = set(only_names)
        out = [a for a in out if a.name in s]
    if only_types:
        t = set(only_types)
        out = [a for a in out if a.type in t]
    return out


# ----------------------------
# Step2 manifest
# ----------------------------
@dataclass(frozen=True)
class Step2Row:
    index: int
    lecture: str
    cond_id: str
    status: str
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


def load_manifest_jsonl(path: Path) -> List[Step2Row]:
    if not path.exists():
        raise FileNotFoundError(f"manifest not found: {path}")
    rows: List[Step2Row] = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            s = line.strip()
            if not s:
                continue
            obj = json.loads(s)
            if not isinstance(obj, dict):
                raise RuntimeError(f"jsonl line {line_no} is not object")
            rows.append(Step2Row.from_dict(obj))
    return rows


def resolve_dest_path(dest_str: str, run_dir: Path) -> Path:
    p = Path(dest_str)
    if p.is_absolute():
        return p
    cand = (run_dir / p).resolve()
    if cand.exists():
        return cand
    return (Path(".") / p).resolve()


# ----------------------------
# Mode detect & script pick
# ----------------------------
def detect_mode(output_root: Path) -> str:
    lt = output_root / "lecture_outputs" / "lecture_texts"
    if (lt / "all_explanations.txt").exists():
        return "animation"
    if list((output_root / "lecture_outputs" / "add_animation_outputs").glob("slide_*_sent*.mp4")):
        return "animation"
    if (lt / "audio_only").exists():
        return "audio"
    return "unknown"


def pick_script_path(output_root: Path, mode: str) -> Tuple[Optional[Path], str]:
    lt = output_root / "lecture_outputs" / "lecture_texts"

    if mode == "animation":
        p = lt / "all_explanations.txt"
        if p.exists():
            return p, "animation:lecture_texts/all_explanations.txt"

    if mode == "audio":
        ao = lt / "audio_only"
        p1 = ao / "lecture_script_stitched.txt"
        p2 = ao / "lecture_script.txt"
        if p1.exists():
            return p1, "audio:lecture_texts/audio_only/lecture_script_stitched.txt"
        if p2.exists():
            return p2, "audio:lecture_texts/audio_only/lecture_script.txt"

    if lt.exists():
        txts = [p for p in lt.rglob("*.txt") if p.is_file()]
        if txts:
            txts.sort(key=lambda x: x.stat().st_size, reverse=True)
            return txts[0], "fallback:largest_txt_under_lecture_texts"

    return None, "not_found"


# ----------------------------
# Prompt & GPT call
# ----------------------------
def build_prompt(aspect: CatalogAspect, lecture_text: str) -> Tuple[str, str]:
    system = (
        "あなたは講義テキストの分析アシスタントです。\n"
        "指定観点に基づき、講義全文から定量値を算出してJSONで返してください。\n"
        "重要: JSONオブジェクトのみを出力し、余計な文章は一切出力しないでください。\n"
    )

    if aspect.type == "count":
        value_rule = "0以上の整数（回数）"
        value_example = 0
    elif aspect.type == "score_1_5":
        value_rule = "1〜5の整数（スコア）"
        value_example = 3
    else:
        value_rule = "整数（可能なら）"
        value_example = 0

    user = (
        f"【観点名】{aspect.name}\n"
        f"【タイプ】{aspect.type}\n"
        f"【定義】{aspect.definition}\n\n"
        "以下が講義全文です。\n"
        "-----\n"
        f"{lecture_text}\n"
        "-----\n\n"
        "出力形式（厳守）：\n"
        "{\n"
        f'  "aspect_id": "{aspect.name}",\n'
        f'  "type": "{aspect.type}",\n'
        f'  "value": {value_example},\n'
        '  "notes": ""\n'
        "}\n\n"
        f"制約：value は {value_rule}\n"
        "※ JSONのみ出力\n"
    )
    return system, user


def normalize_value(aspect: CatalogAspect, parsed: Dict[str, Any]) -> Tuple[Optional[int], str]:
    if "value" not in parsed:
        return None, "MISSING_VALUE"

    v = parsed.get("value")
    try:
        iv = int(v)
    except Exception:
        return None, "VALUE_NOT_INT"

    if aspect.type == "count":
        if iv < 0:
            return None, "COUNT_NEGATIVE"
        return iv, ""
    if aspect.type == "score_1_5":
        if iv < 1 or iv > 5:
            return None, "SCORE_OUT_OF_RANGE"
        return iv, ""
    return iv, ""


def call_gpt_metric(client: OpenAI, system: str, user: str) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    GPT-5固定：MODEL_FIXED
    """
    t0 = time.time()
    try:
        resp = client.responses.create(
            model=MODEL_FIXED,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system}]},
                {"role": "user", "content": [{"type": "input_text", "text": user}]},
            ],
        )
    except Exception as e:
        return None, {
            "ok": False,
            "error": f"responses.create failed: {type(e).__name__}: {e}",
            "elapsed_sec": round(time.time() - t0, 3),
        }

    raw_text = ""
    try:
        raw_text = resp.output_text  # type: ignore
    except Exception:
        raw_text = ""
    if not raw_text:
        raw_text = str(resp)

    parsed = extract_first_json_object(raw_text)

    meta: Dict[str, Any] = {
        "ok": parsed is not None,
        "elapsed_sec": round(time.time() - t0, 3),
        "raw_len": len(raw_text),
    }
    if parsed is None:
        meta["error"] = "JSON_PARSE_FAILED"
        meta["raw_head"] = raw_text[:800]

    return parsed, meta


# ----------------------------
# Main
# ----------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", required=True)

    ap.add_argument("--sleep", type=float, default=0.0, help="sleep seconds between requests")
    ap.add_argument("--force", action="store_true", help="recreate json even if exists")
    ap.add_argument("--allow-partial", action="store_true", help="do not stop on missing dest/script; record errors to csv")

    ap.add_argument("--manifest", default="", help="override manifest path")
    ap.add_argument("--aspects-json", default="", help="override aspects catalog path")
    ap.add_argument("--apikey", default="", help="override apikey.txt path (default: <project_root>/apikey.txt)")

    ap.add_argument("--aspect", action="append", default=[], help="run only this aspect name (repeatable)")
    ap.add_argument("--type", action="append", default=[], dest="types",
                    help='run only this aspect type (repeatable), e.g. --type count --type score_1_5')

    # デバッグ用：lecture/cond を絞る
    ap.add_argument("--lecture", action="append", default=[],
                    help="run only this lecture (repeatable). must match manifest 'lecture' exactly")
    ap.add_argument("--cond", action="append", default=[],
                    help="run only this cond_id (repeatable). must match manifest 'cond_id' exactly")

    args = ap.parse_args()

    run_dir = RUNS_ROOT / args.run_id
    if not run_dir.exists():
        raise FileNotFoundError(f"run_dir not found: {run_dir}")

    # run config は読むが、モデル選択には使わない（GPT-5固定）
    run_cfg_path = run_dir / "config" / "experiment_config.json"
    if not run_cfg_path.exists():
        raise FileNotFoundError(f"run config not found: {run_cfg_path}")
    _ = read_json(run_cfg_path)

    # aspects catalog
    aspects_path = Path(args.aspects_json) if args.aspects_json else ASPECTS_CATALOG_DEFAULT
    if not aspects_path.is_absolute():
        aspects_path = (Path(".") / aspects_path).resolve()
    catalog = load_aspects_catalog(aspects_path)
    catalog = filter_aspects(catalog, only_names=args.aspect, only_types=args.types)
    if not catalog:
        raise RuntimeError(
            "No aspects to run. Check --aspect/--type filters or aspects catalog:\n"
            f"  {aspects_path}"
        )

    # manifest
    manifest_path = Path(args.manifest) if args.manifest else (run_dir / "generation" / "manifest_step02.jsonl")
    if not manifest_path.is_absolute():
        manifest_path = (Path(".") / manifest_path).resolve()
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest_step02.jsonl not found: {manifest_path}")

    rows = load_manifest_jsonl(manifest_path)

    # filter rows by lecture/cond if provided
    lecture_filter = set(args.lecture) if args.lecture else None
    cond_filter = set(args.cond) if args.cond else None

    if lecture_filter is not None:
        rows = [r for r in rows if r.lecture in lecture_filter]
    if cond_filter is not None:
        rows = [r for r in rows if r.cond_id in cond_filter]

    if not rows:
        raise RuntimeError("No manifest rows after filtering. Check --lecture/--cond values.")

    # client (apikey)
    apikey_path: Optional[Path] = None
    if args.apikey.strip():
        apikey_path = Path(args.apikey.strip())
    client = create_step5_client(apikey_path)

    # outputs
    out_csv = run_dir / "analysis" / "gpt_counts.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "run_id", "model", "lecture_key", "cond_id",
        "aspect_id", "aspect_type",
        "value",
        "mode", "step2_status",
        "script_source", "script_path",
        "ok", "elapsed_sec", "raw_len", "error", "warn",
        "json_path", "timestamp",
    ]

    write_header = not out_csv.exists()
    with out_csv.open("a", encoding="utf-8", newline="") as fcsv:
        writer = csv.DictWriter(fcsv, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()

        total = len(rows) * len(catalog)
        k = 0

        for r in rows:
            lecture_key = (r.lecture or "").strip()
            cond_id = (r.cond_id or "").strip()
            if not lecture_key or not cond_id:
                continue

            if r.status not in ("moved", "skip"):
                for aspect in catalog:
                    k += 1
                    writer.writerow({
                        "run_id": args.run_id,
                        "model": MODEL_FIXED,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "aspect_id": aspect.name,
                        "aspect_type": aspect.type,
                        "value": "",
                        "mode": "",
                        "step2_status": r.status,
                        "script_source": "",
                        "script_path": "",
                        "ok": "0",
                        "elapsed_sec": "0",
                        "raw_len": "0",
                        "error": f"STEP2_STATUS_{r.status}",
                        "warn": "",
                        "json_path": "",
                        "timestamp": now_iso(),
                    })
                continue

            output_root = resolve_dest_path(r.dest, run_dir)
            if not output_root.exists():
                for aspect in catalog:
                    k += 1
                    writer.writerow({
                        "run_id": args.run_id,
                        "model": MODEL_FIXED,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "aspect_id": aspect.name,
                        "aspect_type": aspect.type,
                        "value": "",
                        "mode": "",
                        "step2_status": r.status,
                        "script_source": "",
                        "script_path": str(output_root),
                        "ok": "0",
                        "elapsed_sec": "0",
                        "raw_len": "0",
                        "error": "DEST_NOT_FOUND",
                        "warn": "",
                        "json_path": "",
                        "timestamp": now_iso(),
                    })
                if not args.allow_partial:
                    raise FileNotFoundError(f"dest not found: {output_root}")
                continue

            mode = detect_mode(output_root)
            script_path, script_source = pick_script_path(output_root, mode)

            if script_path is None or (not script_path.exists()):
                for aspect in catalog:
                    k += 1
                    writer.writerow({
                        "run_id": args.run_id,
                        "model": MODEL_FIXED,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "aspect_id": aspect.name,
                        "aspect_type": aspect.type,
                        "value": "",
                        "mode": mode,
                        "step2_status": r.status,
                        "script_source": script_source,
                        "script_path": "",
                        "ok": "0",
                        "elapsed_sec": "0",
                        "raw_len": "0",
                        "error": "SCRIPT_NOT_FOUND",
                        "warn": "",
                        "json_path": "",
                        "timestamp": now_iso(),
                    })
                if not args.allow_partial:
                    raise FileNotFoundError(f"script not found under dest: {output_root}")
                continue

            lecture_text = read_text_best_effort(script_path)
            if not lecture_text.strip():
                for aspect in catalog:
                    k += 1
                    writer.writerow({
                        "run_id": args.run_id,
                        "model": MODEL_FIXED,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "aspect_id": aspect.name,
                        "aspect_type": aspect.type,
                        "value": "",
                        "mode": mode,
                        "step2_status": r.status,
                        "script_source": script_source,
                        "script_path": str(script_path),
                        "ok": "0",
                        "elapsed_sec": "0",
                        "raw_len": "0",
                        "error": "SCRIPT_EMPTY",
                        "warn": "",
                        "json_path": "",
                        "timestamp": now_iso(),
                    })
                if not args.allow_partial:
                    raise RuntimeError(f"script is empty: {script_path}")
                continue

            warn_msg = warn_long_text(lecture_text, lecture_key, cond_id) or ""

            for aspect in catalog:
                k += 1
                print(
                    f"[Step5] ({k}/{total}) lecture={lecture_key} cond={cond_id} model={MODEL_FIXED} "
                    f"aspect={aspect.name} ({aspect.type})",
                    flush=True,
                )

                safe_lecture = sanitize_name(lecture_key)
                safe_cond = sanitize_name(cond_id)
                safe_aspect = sanitize_name(aspect.name)

                out_json = run_dir / "analysis" / "gpt_counts" / MODEL_FIXED / safe_lecture / safe_cond / f"{safe_aspect}.json"

                if out_json.exists() and not args.force:
                    writer.writerow({
                        "run_id": args.run_id,
                        "model": MODEL_FIXED,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "aspect_id": aspect.name,
                        "aspect_type": aspect.type,
                        "value": "",
                        "mode": mode,
                        "step2_status": r.status,
                        "script_source": script_source,
                        "script_path": str(script_path),
                        "ok": "1",
                        "elapsed_sec": "0",
                        "raw_len": "0",
                        "error": "CACHE_HIT",
                        "warn": warn_msg,
                        "json_path": str(out_json),
                        "timestamp": now_iso(),
                    })
                    continue

                system, user = build_prompt(aspect, lecture_text)
                parsed, meta = call_gpt_metric(client, system, user)

                value: Optional[int] = None
                norm_err = ""
                if parsed is not None:
                    value, norm_err = normalize_value(aspect, parsed)

                payload: Dict[str, Any] = {
                    "aspect_id": aspect.name,
                    "type": aspect.type,
                    "definition": aspect.definition,
                    "value": value,
                    "counts": {aspect.name: value} if (aspect.type == "count" and value is not None) else {},
                    "score": value if (aspect.type == "score_1_5" and value is not None) else None,
                    "notes": "" if parsed is None else str(parsed.get("notes", "")),
                    "_meta": {
                        "run_id": args.run_id,
                        "lecture_key": lecture_key,
                        "cond_id": cond_id,
                        "model": MODEL_FIXED,
                        "mode": mode,
                        "script_source": script_source,
                        "script_path": str(script_path),
                        "warn": warn_msg,
                        "llm": meta,
                        "timestamp": now_iso(),
                    },
                }

                if parsed is None:
                    payload["_meta"]["error"] = meta.get("error", "UNKNOWN_ERROR")
                    if "raw_head" in meta:
                        payload["_meta"]["raw_head"] = meta["raw_head"]
                else:
                    payload["_meta"]["parsed_raw"] = parsed
                    if norm_err:
                        payload["_meta"]["normalize_error"] = norm_err

                write_json(out_json, payload)

                ok = (parsed is not None and value is not None and not norm_err)
                writer.writerow({
                    "run_id": args.run_id,
                    "model": MODEL_FIXED,
                    "lecture_key": lecture_key,
                    "cond_id": cond_id,
                    "aspect_id": aspect.name,
                    "aspect_type": aspect.type,
                    "value": "" if value is None else str(value),
                    "mode": mode,
                    "step2_status": r.status,
                    "script_source": script_source,
                    "script_path": str(script_path),
                    "ok": "1" if ok else "0",
                    "elapsed_sec": str(meta.get("elapsed_sec", 0)),
                    "raw_len": str(meta.get("raw_len", 0)),
                    "error": "" if ok else (norm_err or str(meta.get("error", "UNKNOWN_ERROR"))),
                    "warn": warn_msg,
                    "json_path": str(out_json),
                    "timestamp": now_iso(),
                })

                if args.sleep and args.sleep > 0:
                    time.sleep(args.sleep)


if __name__ == "__main__":
    main()
