# copy_project_sources_flat_by_time.py
from __future__ import annotations

from pathlib import Path
import shutil
from datetime import datetime


def main():
    project_root = Path(__file__).resolve().parent

    # ============================================================
    # 出力先: collected_source/<timestamp>/
    # ============================================================
    collected_root = project_root / "collected_source"
    collected_root.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = collected_root / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[collect] output_dir = {out_dir}")

    # ============================================================
    # 収集対象
    #   - src/auto_lecture/**/*.py
    #   - scripts/**/*.py
    #   - requirements_min.txt
    #   - .gitignore
    # ============================================================
    src_auto = project_root / "src" / "auto_lecture"
    scripts_dir = project_root / "scripts"
    req = project_root / "requirements_min.txt"
    gitignore = project_root / ".gitignore"

    py_list: list[Path] = []

    if src_auto.exists():
        py_list += sorted(src_auto.rglob("*.py"))
    else:
        print(f"⚠ src/auto_lecture not found: {src_auto}")

    if scripts_dir.exists():
        py_list += sorted(scripts_dir.rglob("*.py"))
    else:
        print(f"⚠ scripts not found: {scripts_dir}")

    # ============================================================
    # フラットコピー（階層は作らない）
    # ※同名が同一バッチ内にあったら連番で回避
    # ============================================================
    used_names = {}
    for p in py_list:
        name = p.name
        if name in used_names:
            used_names[name] += 1
            stem = Path(name).stem
            ext = Path(name).suffix
            name = f"{stem}__dup{used_names[p.name]}{ext}"
        else:
            used_names[name] = 1

        dst = out_dir / name
        shutil.copy2(p, dst)
        print(f"Copied: {p} -> {dst.name}")

    # ============================================================
    # requirements_min.txt
    # ============================================================
    if req.exists():
        dst = out_dir / req.name
        shutil.copy2(req, dst)
        print(f"Copied: {req} -> {dst.name}")
    else:
        print(f"⚠ requirements_min.txt not found: {req}")

    # ============================================================
    # .gitignore
    # ============================================================
    if gitignore.exists():
        dst = out_dir / gitignore.name
        shutil.copy2(gitignore, dst)
        print(f"Copied: {gitignore} -> {dst.name}")
    else:
        print(f"⚠ .gitignore not found: {gitignore}")

    print("\n🎉 Done! Files copied flat into:")
    print(f"   collected_source/{ts}/")
    print("   (past batches are preserved)\n")


if __name__ == "__main__":
    main()
