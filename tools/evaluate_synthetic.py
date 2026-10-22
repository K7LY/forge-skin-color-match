"""Reproducible synthetic comparisons; no real photos or external models.

python tools/evaluate_synthetic.py --output artifacts/synthetic
"""

import argparse
import json
import subprocess
import sys
import types
from dataclasses import asdict
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from skinmatch_core import MatchSettings, match_skin, rgb_to_lab  # noqa: E402
from test_core import scene, shifted  # noqa: E402


def mean_colour_error(image, original, selected):
    actual = rgb_to_lab(np.array(image))[selected].mean(axis=0)
    expected = rgb_to_lab(np.array(original))[selected].mean(axis=0)
    return {
        "delta_e": float(np.linalg.norm(actual - expected)),
        "chroma_error": float(np.linalg.norm(actual[1:] - expected[1:])),
    }


def detail_metrics(before, after, mask):
    before_l = rgb_to_lab(np.array(before))[..., 0]
    after_l = rgb_to_lab(np.array(after))[..., 0]
    distance = cv2.distanceTransform((mask > 0).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    core = distance >= min(10, max(2, float(distance.max()) - 1))
    delta = after_l[core] - before_l[core]
    before_high = before_l - cv2.GaussianBlur(before_l, (0, 0), 1.0)
    after_high = after_l - cv2.GaussianBlur(after_l, (0, 0), 1.0)
    return {
        "interior_pixels": int(core.sum()),
        "luminance_shift_variation_rms": float(np.std(delta)),
        "luminance_contrast_ratio": float(after_l[core].std() / max(before_l[core].std(), 1e-6)),
        "fine_texture_correlation": float(np.corrcoef(before_high[core], after_high[core])[0, 1]),
        "fine_texture_contrast_ratio": float(after_high[core].std() / max(before_high[core].std(), 1e-6)),
    }


def load_baseline(ref):
    source = subprocess.run(
        ["git", "show", f"{ref}:skinmatch_core.py"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout
    module = types.ModuleType("_skinmatch_evaluation_baseline")
    sys.modules[module.__name__] = module
    exec(compile(source, f"git:{ref}:skinmatch_core.py", "exec"), module.__dict__)
    return module


def evaluate(output, baseline_ref=None):
    output.mkdir(parents=True, exist_ok=True)
    settings = MatchSettings()
    rows, metrics = [], {}
    baseline = load_baseline(baseline_ref) if baseline_ref else None
    for name, change in (
        ("Arm patch", (24, 7, 1)),
        ("Face patch", (12, -3, -6)),
        ("Clothes near patch", (24, 7, 1)),
        ("Very pale patch", (26, 49, 66)),
        ("Thin patch", (12, -3, -6)),
    ):
        original, mask = scene(tone=(222, 193, 171)) if name.startswith("Very pale") else scene()
        if name.startswith("Thin"):
            mask[:] = 0
            mask[65:130, 118:132] = 255
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
            "generated_detail_preservation": detail_metrics(generated, result, mask),
            "against_original_patch": {
                "before": mean_colour_error(generated, original, mask > 0),
                "current": mean_colour_error(result, original, mask > 0),
            },
        }
        tiles = [Image.fromarray(original), generated]
        if baseline:
            previous, _ = baseline.match_skin(
                generated, Image.fromarray(original), mask, baseline.MatchSettings()
            )
            metrics[name]["against_original_patch"]["previous"] = mean_colour_error(
                previous, original, mask > 0
            )
            previous_equal_controls, _ = baseline.match_skin(
                generated,
                Image.fromarray(original),
                mask,
                baseline.MatchSettings(
                    strength=settings.strength,
                    brightness=settings.brightness,
                    reference_radius=settings.reference_radius,
                    feather=settings.feather,
                ),
            )
            metrics[name]["against_original_patch"]["previous_at_current_controls"] = mean_colour_error(
                previous_equal_controls,
                original,
                mask > 0,
            )
            tiles.append(previous)
        tiles.append(result)
        rows.append((name, tiles))
    columns = ["Original reference", "Generated / before"]
    if baseline:
        columns.append("Previous default")
    columns.append("Match-priority default")
    canvas = Image.new("RGB", (256 * len(columns), 228 * len(rows) + 28), (24, 27, 33))
    draw = ImageDraw.Draw(canvas)
    for index, title in enumerate(columns):
        draw.text((index * 256 + 8, 8), title, fill="white")
    for row, (name, tiles) in enumerate(rows):
        y = 28 + row * 228
        for index, tile in enumerate(tiles):
            canvas.paste(tile, (index * 256, y))
        errors = metrics[name]["against_original_patch"]
        sequence = [errors["before"]["delta_e"]]
        if baseline:
            sequence.append(errors["previous"]["delta_e"])
        sequence.append(errors["current"]["delta_e"])
        draw.text(
            (8, y + 198),
            f"{name}: mean-colour Delta E76 "
            + " -> ".join(f"{value:.2f}" for value in sequence)
            + f"; outside changed = {metrics[name]['outside_changed_pixels']}",
            fill="white",
        )
    canvas.save(output / "comparison.png")
    payload = {
        "fixture": "Deterministic synthetic skin; not a real-image quality benchmark",
        "settings": asdict(settings),
        "baseline_ref": baseline_ref,
        "baseline_default_settings": asdict(baseline.MatchSettings()) if baseline else None,
        "comparison_metric": "Same original masked patch for every version; uniform untrimmed mean LAB",
        "scenarios": metrics,
    }
    (output / "metrics.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "artifacts" / "synthetic")
    parser.add_argument(
        "--baseline-ref", help="Git revision containing the previous core for a fixed-reference comparison"
    )
    args = parser.parse_args()
    evaluate(args.output, args.baseline_ref)
