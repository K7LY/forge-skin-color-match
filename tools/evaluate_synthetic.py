"""Reproducible synthetic comparisons; no real photos or external models.

python tools/evaluate_synthetic.py --output artifacts/synthetic
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from skinmatch_core import MatchSettings, match_skin  # noqa: E402
from test_core import scene, shifted  # noqa: E402


def evaluate(output):
    output.mkdir(parents=True, exist_ok=True)
    settings = MatchSettings()
    rows, metrics = [], {}
    for name, change in (
        ("Arm patch", (24, 7, 1)),
        ("Face patch", (12, -3, -6)),
        ("Clothes near patch", (24, 7, 1)),
    ):
        original, mask = scene()
        if name.startswith("Clothes"):
            original[35:65, 90:160] = (5, 6, 7)
            original[130:160, 90:160] = (20, 90, 170)
        generated = shifted(original, mask, change)
        result, report = match_skin(generated, Image.fromarray(original), mask, settings)
        outside_changed = np.count_nonzero(
            np.any(np.array(result)[mask == 0] != np.array(generated)[mask == 0], axis=-1)
        )
        zero, _ = match_skin(generated, Image.fromarray(original), mask, MatchSettings(strength=0))
        metrics[name] = {
            **asdict(report),
            "outside_changed_pixels": int(outside_changed),
            "strength_zero_exact": zero.tobytes() == generated.tobytes(),
        }
        rows.append((name, [Image.fromarray(original), generated, result]))
    canvas = Image.new("RGB", (256 * 3, 228 * len(rows) + 28), (24, 27, 33))
    draw = ImageDraw.Draw(canvas)
    for index, title in enumerate(("Original reference", "Generated / before", "Skin Color Match / after")):
        draw.text((index * 256 + 8, 8), title, fill="white")
    for row, (name, tiles) in enumerate(rows):
        y = 28 + row * 228
        for index, tile in enumerate(tiles):
            canvas.paste(tile, (index * 256, y))
        delta = metrics[name]["regions"][0]
        draw.text(
            (8, y + 198),
            f"{name}: mean-colour Delta E76 {delta['delta_e_before']:.2f} -> "
            f"{delta['delta_e_after']:.2f}; outside changed = 0",
            fill="white",
        )
    canvas.save(output / "comparison.png")
    payload = {
        "fixture": "Deterministic synthetic skin; not a real-image quality benchmark",
        "settings": asdict(settings),
        "scenarios": metrics,
    }
    (output / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "synthetic")
    evaluate(parser.parse_args().output)
