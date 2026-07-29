import base64
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch

from PIL import Image

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.service import SlideImageInfo, build_reviewed_region_visuals
from auto_lecture.animation_assignment import generate_mapping_for_slide


class ReviewAssignmentVisualTests(unittest.TestCase):
    def test_reviewed_coordinates_drive_llm_visual_inputs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            slide_path = root / "slide.png"
            Image.new("RGB", (200, 100), "white").save(slide_path)
            slide_info = SlideImageInfo(index=0, path=slide_path, width=200, height=100)
            region_map = [
                {
                    "highlight_id": "edited-region",
                    "region": {
                        "id": 0,
                        "type": "Table",
                        "coordinates": [40, 20, 140, 80],
                    },
                }
            ]

            overview_path, region_imgs = build_reviewed_region_visuals(
                slide_info,
                region_map,
                output_dir=root / "visuals",
                slide_str="001",
            )

            self.assertIsNotNone(overview_path)
            self.assertTrue(overview_path.exists())
            self.assertEqual(region_imgs[0]["region_id"], "0")
            self.assertEqual(region_imgs[0]["type"], "Table")
            self.assertTrue(Path(region_imgs[0]["path"]).exists())

            with Image.open(overview_path) as overview:
                self.assertEqual(overview.getpixel((40, 20)), (255, 0, 0))

            with patch(
                "auto_lecture.animation_assignment.call_responses_text",
                return_value=(None, '{"slide":"001","sentences":[]}'),
            ) as llm_call:
                generate_mapping_for_slide(
                    object(),
                    system_msg={"role": "system", "content": "test"},
                    slide_str="001",
                    slide_image_path=slide_path,
                    regions_json=[region_map[0]["region"]],
                    region_imgs=region_imgs,
                    script_full="表を確認します．",
                    sentences=["表を確認します．"],
                    region_overview_path=overview_path,
                )

            messages = llm_call.call_args.kwargs["messages"]
            message = messages[1]
            image_parts = [part for part in message["content"] if part["type"] == "input_image"]
            self.assertEqual(len(image_parts), 3)
            prompt_text = message["content"][0]["text"]
            self.assertIn("編集後の領域一覧画像", prompt_text)
            self.assertIn('"region_id": "0"', prompt_text)

            overview_data = base64.b64decode(image_parts[1]["image_url"].split(",", 1)[1])
            with Image.open(BytesIO(overview_data)).convert("RGB") as transmitted_overview:
                red, green, blue = transmitted_overview.getpixel((40, 20))
                self.assertGreater(red, 150)
                self.assertLess(green, 140)
                self.assertLess(blue, 140)


if __name__ == "__main__":
    unittest.main()
