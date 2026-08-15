from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def render_material(material: dict, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1600, 900
    title_font = ImageFont.load_default(size=34)
    heading_font = ImageFont.load_default(size=28)
    body_font = ImageFont.load_default(size=22)
    pages = []
    for index, slide in enumerate(material["slides"], start=1):
        page = Image.new("RGB", (width, height), "white")
        draw = ImageDraw.Draw(page)
        draw.text((70, 55), f"{material['title']}  {index}/{len(material['slides'])}", fill="black", font=title_font)
        draw.text((90, 160), str(slide[0]), fill="black", font=heading_font)
        y = 250
        for bullet in slide[1:]:
            draw.text((120, y), f"- {bullet}", fill="black", font=body_font)
            y += 70
        pages.append(page)
    pages[0].save(destination, "PDF", resolution=150, save_all=True, append_images=pages[1:])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    for material in config["materials"]:
        render_material(material, args.output / f"{material['id']}.pdf")


if __name__ == "__main__":
    main()
