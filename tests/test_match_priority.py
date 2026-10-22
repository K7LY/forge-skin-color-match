"""Behaviour thresholds for default matching, shading and final composites."""

import unittest

import cv2
import numpy as np
from PIL import Image

from skinmatch_core import MatchSettings, match_skin, rgb_to_lab, skin_confidence


def lab_rgb(lab):
    return np.rint(cv2.cvtColor(lab.astype(np.float32), cv2.COLOR_LAB2RGB) * 255).astype(np.uint8)


def textured_cast(tone=(62, 14, 20), cast=(18, 8, -4), original_skin=True):
    lab = np.empty((160, 192, 3), np.float32)
    lab[:] = tone
    mask = np.zeros((160, 192), np.uint8)
    mask[48:112, 64:128] = 255
    y, x = np.mgrid[:64, :64]
    shade = 9 * np.sin(2 * np.pi * x / 64) + 3 * np.sin(2 * np.pi * y / 64)
    pores = 0.7 * np.sin(x * 2.1) * np.cos(y * 1.7)
    lab[48:112, 64:128, 0] += shade + pores
    reference = lab_rgb(lab)
    generated = reference.copy()
    target_lab = rgb_to_lab(generated)
    target_lab[mask > 0] += cast
    generated[mask > 0] = lab_rgb(target_lab)[mask > 0]
    if not original_skin:
        reference[mask > 0] = (15, 65, 110)
    return Image.fromarray(reference), Image.fromarray(generated), mask


class MatchPriorityTests(unittest.TestCase):
    def test_default_matches_mean_across_skin_tones_and_casts(self):
        for tone in ((32, 12, 14), (58, 16, 22), (72, 10, 16)):
            for cast in ((15, 6, -4), (-12, -4, 5), (22, 0, 0)):
                with self.subTest(tone=tone, cast=cast):
                    original, generated, mask = textured_cast(tone, cast)
                    output, report = match_skin(generated, original, mask)
                    self.assertEqual(report.reason, "corrected")
                    self.assertEqual(len(report.regions), 1)
                    self.assertLess(report.regions[0].delta_e_after, 0.75)
                    self.assertEqual(report.regions[0].gamut_scale, 1)
                    eligible = (mask > 0) & (skin_confidence(np.array(generated)) > 0)
                    self.assertLess(
                        np.linalg.norm(rgb_to_lab(np.array(output))[eligible].mean(axis=0) - np.array(tone)),
                        0.75,
                    )
                    np.testing.assert_array_equal(np.array(output)[~eligible], np.array(generated)[~eligible])

    def test_shading_and_texture_survive_reference_with_different_contrast(self):
        original, generated, mask = textured_cast()
        output, report = match_skin(generated, original, mask)
        self.assertEqual(report.reason, "corrected")
        before = rgb_to_lab(np.array(generated))[..., 0]
        after = rgb_to_lab(np.array(output))[..., 0]
        core = np.zeros(mask.shape, bool)
        core[60:100, 76:116] = True
        # This compares actual generated detail, independent of reference detail.
        self.assertLess(np.std((after - before)[core]), 0.2)
        self.assertAlmostEqual(float(after[core].std() / before[core].std()), 1, delta=0.01)
        high_before = before - cv2.GaussianBlur(before, (0, 0), 1.0)
        high_after = after - cv2.GaussianBlur(after, (0, 0), 1.0)
        self.assertGreater(np.corrcoef(high_before[core], high_after[core])[0, 1], 0.98)
        self.assertAlmostEqual(float(high_after[core].std() / high_before[core].std()), 1, delta=0.05)

    def test_new_skin_without_original_skin_matches_at_boundary(self):
        original, generated, mask = textured_cast(original_skin=False)
        output, report = match_skin(generated, original, mask)
        self.assertEqual(report.reason, "corrected")
        self.assertLess(report.regions[0].delta_e_after, 0.75)
        # The background under a newly generated limb must not tint it blue.
        self.assertLess(
            np.linalg.norm(rgb_to_lab(np.array(output))[mask > 0].mean(axis=0) - np.array((62, 14, 20))), 0.75
        )
        np.testing.assert_array_equal(np.array(output)[mask == 0], np.array(generated)[mask == 0])

    def test_soft_composite_is_not_attenuated_twice(self):
        original = np.full((128, 160, 3), (175, 125, 100), np.uint8)
        mask = np.zeros((128, 160), np.float32)
        mask[32:96, 48:112] = 0.65
        cast = np.array((20, 8, -4))
        target = lab_rgb(rgb_to_lab(original) + cast)
        generated = np.rint(original * (1 - mask[..., None]) + target * mask[..., None]).astype(np.uint8)
        output, report = match_skin(Image.fromarray(generated), Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        self.assertLess(report.regions[0].delta_e_after, 0.4)
        np.testing.assert_array_equal(np.array(output)[mask == 0], generated[mask == 0])

    def test_partial_strength_is_a_lab_interpolation(self):
        original = np.full((128, 160, 3), (175, 125, 100), np.uint8)
        mask = np.zeros((128, 160), np.uint8)
        mask[32:96, 48:112] = 255
        generated = original.copy()
        generated[mask > 0] = lab_rgb(rgb_to_lab(original) + [18, 8, -4])[mask > 0]
        result, _ = match_skin(
            Image.fromarray(generated), Image.fromarray(original), mask, MatchSettings(strength=0.5)
        )
        ref_mean = rgb_to_lab(original)[mask > 0].mean(axis=0)
        before = rgb_to_lab(generated)[mask > 0].mean(axis=0)
        after = rgb_to_lab(np.array(result))[mask > 0].mean(axis=0)
        self.assertLess(np.linalg.norm(after - (before + ref_mean) * 0.5), 0.5)

    def test_gamut_guard_keeps_extreme_highlights_and_shadow_contrast(self):
        lab = np.full((160, 192, 3), (86, 8, 15), np.float32)
        original = lab_rgb(lab)
        mask = np.zeros(lab.shape[:2], np.uint8)
        mask[48:112, 64:128] = 255
        lab[48:112, 64:128, 0] = np.linspace(20, 82, 64)[None, :]
        generated = original.copy()
        generated[mask > 0] = lab_rgb(lab)[mask > 0]
        output, report = match_skin(Image.fromarray(generated), Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        self.assertGreater(report.regions[0].gamut_scale, 0)
        self.assertLess(report.regions[0].gamut_scale, 0.9)
        before = rgb_to_lab(generated)[60:100, 76:116, 0]
        after = rgb_to_lab(np.array(output))[60:100, 76:116, 0]
        self.assertLess(np.std(after - before), 0.2)
        self.assertAlmostEqual(float(after.std() / before.std()), 1, delta=0.01)


if __name__ == "__main__":
    unittest.main()
