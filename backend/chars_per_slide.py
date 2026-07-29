from pathlib import Path
import csv, json

RUN_ID = "exp_10slides_10conds_10pdf_10conds_2026-01-01_214323"
RUN_DIR = Path("experiments/runs") / RUN_ID

INDEX_CSV = RUN_DIR / "extracted" / "index.csv"
OUT_CSV   = RUN_DIR / "analysis" / "metrics_basic" / "chars_per_slide.csv"
OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

def read_text_best_effort(p: Path) -> str:
    for enc in ("utf-8", "utf-8-sig", "cp932"):
        try:
            return p.read_text(encoding=enc)
        except Exception:
            pass
    return p.read_text(errors="ignore")

def read_json_best_effort(p: Path):
    return json.loads(read_text_best_effort(p))

rows_out = []

# ★ 全スライド合計（これを追加）
sum_chars = 0
sum_slides = 0

with INDEX_CSV.open("r", encoding="utf-8") as f:
    for d in csv.DictReader(f):
        if (d.get("status") or "") != "ok":
            continue

        lecture = d.get("lecture_title") or ""
        cond    = d.get("cond_id") or ""

        script_path = RUN_DIR / (d.get("script_merged_txt") or "")
        meta_path   = RUN_DIR / (d.get("meta_json") or "")

        if not script_path.exists() or not meta_path.exists():
            continue

        text = read_text_best_effort(script_path)
        meta = read_json_best_effort(meta_path)

        page_count = meta.get("page_count", 0)
        try:
            page_count = int(page_count)
        except Exception:
            page_count = 0

        total_chars = len(text)  # 改行も含む
        # total_chars = len(text.replace("\n", "").replace("\r", ""))  # 改行なしにしたい場合

        chars_per_slide = (total_chars / page_count) if page_count > 0 else ""

        rows_out.append({
            "run_id": RUN_ID,
            "lecture_title": lecture,
            "cond_id": cond,
            "page_count": page_count,
            "script_char_len": total_chars,
            "script_chars_per_slide": chars_per_slide,
        })

        # ★ 全スライド合計へ加算（page_count==0は除外）
        if page_count > 0:
            sum_chars += total_chars
            sum_slides += page_count

with OUT_CSV.open("w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(
        f,
        fieldnames=list(rows_out[0].keys()) if rows_out else
        ["run_id","lecture_title","cond_id","page_count","script_char_len","script_chars_per_slide"]
    )
    w.writeheader()
    for r in rows_out:
        w.writerow(r)

print("wrote:", OUT_CSV)

# ★ 全スライドの平均を表示（これを追加）
if sum_slides > 0:
    overall_avg = sum_chars / sum_slides
    print(f"ALL SLIDES AVG (chars/slide) = {overall_avg:.2f}  (chars={sum_chars}, slides={sum_slides})")
else:
    print("No valid rows to compute overall average (sum_slides=0).")
