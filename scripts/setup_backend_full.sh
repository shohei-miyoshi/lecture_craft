#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
VENV_DIR="$BACKEND_DIR/.venv"
DETECTRON2_REF="git+https://github.com/facebookresearch/detectron2.git@fd27788985af0f4ca800bca563acdb700bb890e2"
LP_CONFIG_URL="https://huggingface.co/layoutparser/detectron2/resolve/main/PubLayNet/faster_rcnn_R_50_FPN_3x/config.yml"
LP_MODEL_URL="https://huggingface.co/layoutparser/detectron2/resolve/main/PubLayNet/faster_rcnn_R_50_FPN_3x/model_final.pth"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "backend/.venv not found."
  echo "Run: bash scripts/setup_backend.sh"
  exit 1
fi

patch_torch_header_for_macos() {
  local strong_type_path
  strong_type_path="$("$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path
import torch

print(Path(torch.__file__).resolve().parent / "include" / "c10" / "util" / "strong_type.h")
PY
)"

  "$VENV_DIR/bin/python" - "$strong_type_path" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
lines = path.read_text(encoding="utf-8").splitlines()

start = None
for idx, line in enumerate(lines):
    if line.strip() != "template <typename T, typename Tag, typename ... M>":
        continue
    if idx + 1 >= len(lines):
        continue
    if "struct is_arithmetic<::strong::type<T, Tag, M...>>" in lines[idx + 1]:
        start = idx
        break

if start is None:
    print("PyTorch macOS llvm workaround already applied.")
    raise SystemExit(0)

end = start
while end < len(lines) and lines[end].strip() != "};":
    end += 1

if end == len(lines):
    raise SystemExit("Failed to locate the end of the std::is_arithmetic specialization block")

del lines[start : end + 1]
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Patched {path}")
PY
}

install_visual_extra_requirements() {
  local tmp_requirements
  tmp_requirements="$(mktemp)"
  trap 'rm -f "$tmp_requirements"' RETURN
  grep -v '^detectron2[[:space:]]*@' "$BACKEND_DIR/requirements_visual_extra.txt" > "$tmp_requirements"
  "$VENV_DIR/bin/pip" install -r "$tmp_requirements"
}

install_detectron2() {
  "$VENV_DIR/bin/pip" install 'setuptools<81' wheel ninja cloudpickle

  if [ "$(uname -s)" = "Darwin" ]; then
    patch_torch_header_for_macos
    PATH="$VENV_DIR/bin:$PATH" \
      CC=clang \
      CXX=clang++ \
      ARCHFLAGS="-arch $(uname -m)" \
      "$VENV_DIR/bin/pip" install --no-build-isolation --no-deps "$DETECTRON2_REF"
    return
  fi

  PATH="$VENV_DIR/bin:$PATH" "$VENV_DIR/bin/pip" install --no-build-isolation --no-deps "$DETECTRON2_REF"
}

download_layoutparser_assets() {
  mkdir -p "$BACKEND_DIR/models"
  if [ ! -s "$BACKEND_DIR/models/config.yml" ]; then
    curl -L "$LP_CONFIG_URL" -o "$BACKEND_DIR/models/config.yml"
  else
    echo "Using existing backend/models/config.yml"
  fi

  if [ ! -s "$BACKEND_DIR/models/model_final.pth" ]; then
    curl -L "$LP_MODEL_URL" -o "$BACKEND_DIR/models/model_final.pth"
  else
    echo "Using existing backend/models/model_final.pth"
  fi
}

verify_layoutparser_model() {
  cd "$BACKEND_DIR"
  "$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path
import layoutparser as lp

model_dir = Path("models")
model = lp.Detectron2LayoutModel(
    config_path=str(model_dir / "config.yml"),
    model_path=str(model_dir / "model_final.pth"),
    label_map={0: "Text", 1: "Title", 2: "List", 3: "Table", 4: "Figure"},
    extra_config=[
        "MODEL.ROI_HEADS.SCORE_THRESH_TEST", 0.5,
        "MODEL.ROI_HEADS.NMS_THRESH_TEST", 0.5,
        "INPUT.MIN_SIZE_TEST", 800,
        "INPUT.MAX_SIZE_TEST", 1333,
    ],
)
print("LayoutParser model ready:", type(model).__name__)
PY
}

cd "$BACKEND_DIR"
"$VENV_DIR/bin/pip" install -r requirements_min.txt
install_visual_extra_requirements
install_detectron2
download_layoutparser_assets
verify_layoutparser_model

cat <<'EOF'

Backend full visual setup complete.

Next:
  1. Verify ffmpeg is installed
  2. Run:
     bash scripts/dev_backend.sh

EOF
