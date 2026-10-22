"""CPU-only, conservative skin colour transfer. No Forge or Gradio imports.

All colour statistics use OpenCV float CIELAB: L=0..100, signed a/b.
White masks select editable pixels. Input arrays must already share coordinates.
SPDX-License-Identifier: AGPL-3.0-only
"""

from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image


@dataclass(frozen=True)
class MatchSettings:
    strength: float = 0.7
    reference_radius: int = 48
    feather: int = 24
    brightness: float = 0.3
    reference_mode: str = "Auto"
    min_pixels: int = 64

    def validate(self):
        if not (0 <= self.strength <= 1 and 0 <= self.brightness <= 1):
            raise ValueError("Strength and brightness must be finite values in [0, 1]")
        if not (1 <= self.reference_radius <= 512 and 0 <= self.feather <= 256):
            raise ValueError("Radius must be 1..512; feather must be 0..256")
        if self.reference_mode not in ("Auto", "Manual"):
            raise ValueError("Unknown reference mode")
        if not 16 <= self.min_pixels <= 100000:
            raise ValueError("Invalid minimum sample count")


@dataclass
class RegionReport:
    target_pixels: int
    reference_pixels: int
    delta_e_before: float
    delta_e_after: float


@dataclass
class MatchReport:
    reason: str = "no_usable_skin_or_reference"
    regions: list[RegionReport] = field(default_factory=list)


def rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def mask_array(mask, size: tuple[int, int]) -> np.ndarray:
    """Strict shape checking; never silently stretch a mask into another frame."""
    if isinstance(mask, Image.Image):
        if mask.mode == "RGBA" and mask.getextrema()[-1] != (255, 255):
            mask = mask.getchannel("A")
        mask = np.asarray(mask.convert("L"))
    data = np.asarray(mask)
    if data.shape != (size[1], size[0]):
        raise ValueError("Mask and image dimensions differ")
    if data.dtype == np.uint8:
        data = data.astype(np.float32) / 255.0
    elif data.dtype == np.bool_:
        data = data.astype(np.float32)
    else:
        data = data.astype(np.float32)
    if not np.isfinite(data).all() or np.any(data < 0) or np.any(data > 1):
        raise ValueError("Masks must be uint8 0..255 or float 0..1")
    return data


def _ramp(x, low, high):
    t = np.clip((x - low) / (high - low), 0, 1)
    return t * t * (3 - 2 * t)


def skin_confidence(rgb: np.ndarray, lab: np.ndarray | None = None) -> np.ndarray:
    """A colour heuristic, NOT semantic segmentation or person identification.

    Broad warm-skin gates include dark and pale tones; saturated red/yellow,
    neutral clothing, blue/green backgrounds and deep shadows are rejected.
    Skin-coloured fabric/wood may pass. Unusual lighting may be rejected.
    """
    lab = rgb_to_lab(rgb) if lab is None else lab
    ycc = cv2.cvtColor(rgb, cv2.COLOR_RGB2YCrCb).astype(np.float32)
    light, a, b = np.moveaxis(lab, -1, 0)
    cr, cb = ycc[..., 1], ycc[..., 2]
    r, g, blue = np.moveaxis(rgb.astype(np.float32), -1, 0)
    score = np.minimum.reduce(
        [
            _ramp(light, 6, 12) * (1 - _ramp(light, 95, 99)),
            _ramp(a, -1, 3) * (1 - _ramp(a, 31, 42)),
            _ramp(b, 0, 4) * (1 - _ramp(b, 36, 50)),
            _ramp(cr, 129, 134) * (1 - _ramp(cr, 181, 191)),
            _ramp(cb, 75, 85) * (1 - _ramp(cb, 132, 138)),
            _ramp(r - g, -4, 4),
            _ramp(r - blue, 3, 12),
            _ramp(g - blue, -6, 3),
        ]
    )
    score[score < 0.1] = 0
    return score.astype(np.float32)


def inward_feather(support: np.ndarray, radius: int) -> np.ndarray:
    """Distance ramp confined to support, including when it touches the frame."""
    if radius == 0:
        return support.astype(np.float32)
    padded = np.pad(support.astype(np.uint8), 1)
    distance = cv2.distanceTransform(padded, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)[1:-1, 1:-1]
    # Boundary pixel is zero, avoiding a colour step at a hard mask edge.
    return _ramp(distance, 1, radius + 1) * support


def _stats(lab, weights, minimum):
    selected = weights > 0
    if np.count_nonzero(selected) < minimum:
        return None
    values = lab[selected]
    w = weights[selected]
    median = np.median(values, axis=0)
    mad = np.median(np.abs(values - median), axis=0)
    limit = np.maximum(mad * 4.0, [12.0, 6.0, 6.0])
    keep = np.all(np.abs(values - median) <= limit, axis=1)
    values, w = values[keep], w[keep]
    if len(w) < minimum or w.sum() < minimum * 0.5:
        return None
    mean = np.average(values, axis=0, weights=w)
    std = np.sqrt(np.average((values - mean) ** 2, axis=0, weights=w))
    return mean, std, len(w)


def _nearest_reference(candidates, distances, minimum, radius):
    """Use just one connected local skin patch; avoid pooling nearby people."""
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), 8)
    best = None
    # Candidate components must approach the edit, not just fall in a large ring.
    near_limit = min(float(radius), max(3.0, min(12.0, radius / 4.0)))
    for label in range(1, count):
        area = stats[label, cv2.CC_STAT_AREA]
        if area < minimum:
            continue
        component = labels == label
        distance = float(distances[component].min())
        if distance > near_limit:
            continue
        key = (distance, -area)
        if best is None or key < best[0]:
            best = (key, component)
    return None if best is None else best[1]


DEFAULT_SETTINGS = MatchSettings()


def match_skin(
    generated: Image.Image,
    original: Image.Image,
    edit_mask,
    settings: MatchSettings = DEFAULT_SETTINGS,
    reference_mask=None,
):
    """Return (PIL image, report). No-op paths return the exact input object.

    Auto works separately on connected editable skin patches. Manual selects
    reference pixels from the original, still excluding edited/non-skin pixels.
    The caller must catch failures and preserve its generated image.
    """
    settings.validate()
    report = MatchReport()
    if settings.strength == 0:
        report.reason = "strength_zero"
        return generated, report
    if generated.mode not in ("RGB", "RGBA") or original.size != generated.size:
        raise ValueError("RGB/RGBA images with identical dimensions are required")
    edit = mask_array(edit_mask, generated.size)
    editable = edit > 0
    if not editable.any():
        report.reason = "empty_mask"
        return generated, report
    manual = None
    if settings.reference_mode == "Manual":
        if reference_mask is None:
            report.reason = "missing_manual_reference"
            return generated, report
        manual = mask_array(reference_mask, generated.size) * (~editable)

    rgb = np.asarray(generated.convert("RGB"))
    ref_rgb = np.asarray(original.convert("RGB"))
    lab, ref_lab = rgb_to_lab(rgb), rgb_to_lab(ref_rgb)
    target_skin = skin_confidence(rgb, lab)
    ref_skin = skin_confidence(ref_rgb, ref_lab)
    support = editable & (target_skin > 0)
    count, labels, regions, _ = cv2.connectedComponentsWithStats(support.astype(np.uint8), 8)
    if count > 257:
        report.reason = "fragmented_skin_mask"
        return generated, report
    # Smooth confidence inward without ever changing a rejected non-skin pixel.
    soft_skin = cv2.GaussianBlur(target_skin, (0, 0), 0.8) * (target_skin > 0)
    base_alpha = inward_feather(editable, settings.feather) * edit * soft_skin
    output = np.array(generated, copy=True)
    manual_stats = _stats(ref_lab, ref_skin * manual, settings.min_pixels) if manual is not None else None
    for label in range(1, count):
        x, y, width, height, area = regions[label]
        if area < settings.min_pixels:
            continue
        margin = settings.reference_radius + 2
        x0, y0 = max(0, x - margin), max(0, y - margin)
        x1, y1 = min(rgb.shape[1], x + width + margin), min(rgb.shape[0], y + height + margin)
        roi = np.s_[y0:y1, x0:x1]
        component = labels[roi] == label
        target_weights = target_skin[roi] * edit[roi] * component
        target_stats = _stats(lab[roi], target_weights, settings.min_pixels)
        if target_stats is None:
            continue
        if manual is None:
            distances = cv2.distanceTransform(
                (~component).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE
            )
            ring = (distances > 0) & (distances <= settings.reference_radius) & (~editable[roi])
            candidates = ring & (ref_skin[roi] > 0)
            reference = _nearest_reference(
                candidates, distances, settings.min_pixels, settings.reference_radius
            )
            if reference is None:
                continue
            weights = ref_skin[roi] * reference / (1 + distances / max(1, settings.reference_radius))
            reference_stats = _stats(ref_lab[roi], weights, settings.min_pixels)
        else:
            reference_stats = manual_stats
        if reference_stats is None:
            continue
        target_mean, target_std, n_target = target_stats
        ref_mean, ref_std, n_reference = reference_stats
        gain = np.clip(ref_std / np.maximum(target_std, 1.0), 0.8, 1.25)
        # Constant patches need a mean shift, never noise amplification.
        gain = np.where(target_std < 1.0, 1.0, gain)
        # Keep luminance contrast especially close to the generated shading.
        gain[0] = np.clip(gain[0], 0.95, 1.05)
        local_lab = lab[roi]
        transferred = (local_lab - target_mean) * gain + ref_mean
        delta = transferred - local_lab
        delta[..., 0] = np.clip(delta[..., 0], -15, 15) * settings.brightness
        chroma = delta[..., 1:]
        length = np.linalg.norm(chroma, axis=-1, keepdims=True)
        delta[..., 1:] = chroma * np.minimum(1.0, 18.0 / np.maximum(length, 1e-6))
        corrected_lab = local_lab + delta * settings.strength
        corrected_lab[..., 0] = np.clip(corrected_lab[..., 0], 0, 100)
        corrected_lab[..., 1:] = np.clip(corrected_lab[..., 1:], -100, 100)
        corrected_rgb = cv2.cvtColor(corrected_lab.astype(np.float32), cv2.COLOR_LAB2RGB) * 255.0
        alpha = base_alpha[roi] * component
        changed = alpha > 0
        if not changed.any():
            continue
        blended = np.rint(rgb[roi] * (1 - alpha[..., None]) + corrected_rgb * alpha[..., None])
        local_output = output[roi]
        local_output[..., :3][changed] = np.clip(blended[changed], 0, 255).astype(np.uint8)
        after_lab = rgb_to_lab(local_output[..., :3].copy())
        after_mean = np.average(after_lab[component], axis=0, weights=target_weights[component])
        before_mean = np.average(local_lab[component], axis=0, weights=target_weights[component])
        report.regions.append(
            RegionReport(
                n_target,
                n_reference,
                float(np.linalg.norm(before_mean - ref_mean)),
                float(np.linalg.norm(after_mean - ref_mean)),
            )
        )
    if not report.regions or np.array_equal(output, np.asarray(generated)):
        if report.regions:
            report.reason = "no_pixel_change"
        return generated, report
    report.reason = "corrected"
    result = Image.fromarray(output, mode=generated.mode)
    result.info.update(generated.info)
    return result, report
