import unittest

import cv2
import numpy as np
from PIL import Image

from skinmatch_core import MatchSettings, SkinRange, inward_feather, match_skin, rgb_to_lab, skin_confidence


def scene(shape=(192, 256), tone=(176, 124, 98)):
    """Synthetic shaded skin on blue background, with deterministic fine detail."""
    height, width = shape
    y, x = np.mgrid[:height, :width]
    rng = np.random.default_rng(42)
    texture = (7 * np.sin(x / 23) + 3 * np.cos(y / 17) + rng.normal(0, 1.2, shape))[..., None]
    image = np.empty((height, width, 3), np.uint8)
    image[:] = (24, 65, 105)
    body = ((x - width / 2) / (width * 0.38)) ** 2 + ((y - height / 2) / (height * 0.43)) ** 2 < 1
    image[body] = np.clip(np.array(tone) + texture[body], 0, 255).astype(np.uint8)
    mask = np.zeros(shape, np.uint8)
    mask[65:130, 95:155] = 255
    return image, mask


def shifted(original, mask, shift=(24, 7, 1)):
    generated = original.copy()
    generated[mask > 0] = np.clip(generated[mask > 0].astype(float) + shift, 0, 255).astype(np.uint8)
    return Image.fromarray(generated)


class CoreTests(unittest.TestCase):
    def test_arm_improves_colour_and_keeps_outside_exact(self):
        original, mask = scene()
        generated = shifted(original, mask)
        output, report = match_skin(generated, Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        self.assertLess(report.regions[0].delta_e_after, report.regions[0].delta_e_before)
        np.testing.assert_array_equal(np.array(output)[mask == 0], np.array(generated)[mask == 0])
        # Fine detail is retained rather than replaced with flat reference colour.
        before = rgb_to_lab(np.array(generated))[80:115, 110:140, 0]
        after = rgb_to_lab(np.array(output))[80:115, 110:140, 0]
        self.assertGreater(np.corrcoef(before.ravel(), after.ravel())[0, 1], 0.98)

    def test_face_patch_boundary_is_continuous(self):
        original, mask = scene()
        generated = shifted(original, mask, (12, -3, -6))
        output, report = match_skin(generated, Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        delta = np.linalg.norm(np.array(output).astype(float) - np.array(generated), axis=-1)
        self.assertGreater(delta[65, 120], 0)
        before_seam = np.linalg.norm(np.array(generated)[65, 120].astype(float) - original[64, 120])
        after_seam = np.linalg.norm(np.array(output)[65, 120].astype(float) - original[64, 120])
        self.assertLess(after_seam, before_seam * 0.6)
        self.assertLess(report.regions[0].delta_e_after, report.regions[0].delta_e_before)

    def test_clothing_and_hair_are_excluded(self):
        original, mask = scene()
        original[35:65, 90:160] = (5, 6, 7)  # hair near the reference ring
        original[130:160, 90:160] = (20, 90, 170)  # clothes
        generated = np.array(shifted(original, mask))
        generated[80:110, 105:120] = (15, 80, 155)  # non-skin inside the edit
        output, report = match_skin(Image.fromarray(generated), Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(output)[80:110, 105:120], generated[80:110, 105:120])
        self.assertLess(report.regions[0].delta_e_after, report.regions[0].delta_e_before)

    def test_no_skin_reference_skips(self):
        original = np.full((160, 160, 3), (15, 70, 120), np.uint8)
        mask = np.zeros((160, 160), np.uint8)
        mask[50:110, 50:110] = 255
        generated = np.array(original)
        generated[mask > 0] = (210, 150, 125)
        source = Image.fromarray(generated)
        result, report = match_skin(source, Image.fromarray(original), mask)
        self.assertIs(result, source)
        self.assertEqual(report.regions, [])

    def test_distant_person_is_not_a_reference(self):
        original = np.full((160, 160, 3), (15, 70, 120), np.uint8)
        original[20:140, 112:145] = (185, 126, 103)
        mask = np.zeros((160, 160), np.uint8)
        mask[50:110, 50:90] = 255
        generated = np.array(original)
        generated[mask > 0] = (210, 150, 125)
        source = Image.fromarray(generated)
        result, _ = match_skin(source, Image.fromarray(original), mask)
        self.assertIs(result, source)

    def test_two_people_use_separate_local_statistics(self):
        original = np.full((180, 340, 3), (20, 60, 100), np.uint8)
        original[20:160, 15:150] = (118, 76, 53)
        original[20:160, 190:325] = (220, 179, 152)
        mask = np.zeros((180, 340), np.uint8)
        mask[65:115, 60:110] = 255
        mask[65:115, 235:285] = 255
        generated = shifted(original, mask)
        result, report = match_skin(generated, Image.fromarray(original), mask)
        self.assertEqual(len(report.regions), 2)
        self.assertTrue(all(r.delta_e_after < r.delta_e_before for r in report.regions))
        self.assertLess(np.array(result)[90, 80, 0], 160)
        self.assertGreater(np.array(result)[90, 260, 0], 210)

    def test_zero_strength_is_exact_including_metadata_alpha(self):
        original, mask = scene()
        generated = shifted(original, mask).convert("RGBA")
        generated.info["test"] = "preserve"
        result, report = match_skin(generated, Image.fromarray(original), mask, MatchSettings(strength=0))
        self.assertIs(result, generated)
        self.assertEqual(report.reason, "strength_zero")

    def test_alpha_and_metadata_survive_correction(self):
        original, mask = scene()
        data = np.array(shifted(original, mask).convert("RGBA"))
        data[..., 3] = np.arange(data.shape[1], dtype=np.uint8)
        source = Image.fromarray(data)
        source.info["parameters"] = "original metadata"
        result, report = match_skin(source, Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(result)[..., 3], data[..., 3])
        self.assertEqual(result.info, source.info)

    def test_empty_full_and_tiny_masks_skip(self):
        original, mask = scene()
        generated = shifted(original, mask)
        for test_mask in (
            np.zeros_like(mask),
            np.full_like(mask, 255),
            np.eye(*mask.shape, dtype=np.uint8) * 255,
        ):
            result, _ = match_skin(generated, Image.fromarray(original), test_mask)
            self.assertIs(result, generated)

    def test_manual_mask_uses_original_and_cannot_edit_outside(self):
        original, mask = scene()
        manual = np.zeros_like(mask)
        manual[70:125, 60:85] = 255
        generated = shifted(original, mask)
        result, report = match_skin(
            generated, Image.fromarray(original), mask, MatchSettings(reference_mode="Manual"), manual
        )
        self.assertEqual(report.reason, "corrected")
        self.assertLess(report.regions[0].delta_e_after, report.regions[0].delta_e_before)
        np.testing.assert_array_equal(np.array(result)[mask == 0], np.array(generated)[mask == 0])

    def test_missing_empty_overlapping_or_non_skin_manual_skips(self):
        original, mask = scene()
        generated = shifted(original, mask)
        non_skin = np.zeros_like(mask)
        non_skin[:12] = 255
        for manual in (None, np.zeros_like(mask), mask, non_skin):
            result, _ = match_skin(
                generated, Image.fromarray(original), mask, MatchSettings(reference_mode="Manual"), manual
            )
            self.assertIs(result, generated)

    def test_dark_pale_and_red_skin_gate_and_clothing_rejection(self):
        colours = np.array(
            [
                [
                    (65, 40, 28),
                    (110, 72, 50),
                    (235, 209, 190),
                    (205, 130, 110),
                    (0, 20, 90),
                    (50, 50, 50),
                    (240, 20, 20),
                    (240, 220, 0),
                ]
            ],
            dtype=np.uint8,
        )
        scores = skin_confidence(colours)[0]
        self.assertTrue(np.all(scores[:4] > 0))
        self.assertTrue(np.all(scores[4:] == 0))

    def test_low_variance_stays_finite_and_bounded(self):
        original = np.full((120, 120, 3), (170, 110, 80), np.uint8)
        mask = np.zeros((120, 120), np.uint8)
        mask[30:90, 30:90] = 255
        generated = shifted(original, mask, (50, 30, 25))
        result, report = match_skin(
            generated, Image.fromarray(original), mask, MatchSettings(strength=1, feather=0)
        )
        self.assertEqual(report.reason, "corrected")
        delta = rgb_to_lab(np.array(result)) - rgb_to_lab(np.array(generated))
        self.assertLess(np.abs(delta[..., 0]).max(), 5.0)
        self.assertLess(np.linalg.norm(delta[..., 1:], axis=-1).max(), 19.0)

    def test_brightness_zero_preserves_lightness_within_quantization(self):
        original, mask = scene()
        generated = shifted(original, mask)
        result, _ = match_skin(generated, Image.fromarray(original), mask, MatchSettings(brightness=0))
        diff = np.abs(rgb_to_lab(np.array(result))[..., 0] - rgb_to_lab(np.array(generated))[..., 0])
        self.assertLess(diff.max(), 0.5)

    def test_bad_dimensions_nonfinite_and_invalid_settings_rejected(self):
        original, mask = scene()
        source = Image.fromarray(original)
        for bad_mask in (mask[:10], np.full(mask.shape, np.nan), np.full(mask.shape, -1.0)):
            with self.assertRaises(ValueError):
                match_skin(source, source, bad_mask)
        with self.assertRaises(ValueError):
            match_skin(source, source.resize((20, 20)), mask)
        for settings in (
            MatchSettings(strength=float("nan")),
            MatchSettings(brightness=2),
            MatchSettings(feather=-1),
            MatchSettings(reference_mode="bad"),
        ):
            with self.assertRaises(ValueError):
                match_skin(source, source, mask, settings)

    def test_inward_feather_never_leaks_and_handles_frame_edges(self):
        support = np.zeros((40, 50), bool)
        support[:30, :30] = True
        for radius in (0, 1, 24, 128):
            alpha = inward_feather(support, radius)
            self.assertTrue(np.all(alpha[~support] == 0))
            self.assertTrue(np.all((alpha >= 0) & (alpha <= 1)))
            if radius:
                self.assertTrue(np.all(alpha[0] == 0))

    def test_soft_mask_cannot_leak(self):
        original, mask = scene()
        soft = cv2.GaussianBlur(mask, (15, 15), 3)
        generated = shifted(original, mask)
        result, report = match_skin(generated, Image.fromarray(original), soft)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(result)[soft == 0], np.array(generated)[soft == 0])

    def test_range_limits_exclude_skin_like_orange_clothing(self):
        original, mask = scene()
        generated = np.array(shifted(original, mask))
        # Warm fabric can fall inside the broad default skin envelope. The
        # user can explicitly exclude its higher b while keeping this skin.
        generated[80:110, 110:125] = (210, 145, 80)
        colour = rgb_to_lab(generated[80:81, 110:111])[0, 0]
        self.assertGreater(colour[2], 40)
        self.assertGreater(skin_confidence(generated)[85, 115], 0)
        settings = MatchSettings(skin_range=SkinRange(b_max=32))
        result, report = match_skin(Image.fromarray(generated), Image.fromarray(original), mask, settings)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(result)[80:110, 110:125], generated[80:110, 110:125])
        accepted = skin_confidence(generated, skin_range=settings.skin_range) > 0
        np.testing.assert_array_equal(np.array(result)[~accepted], generated[~accepted])

    def test_skin_range_rejects_invalid_bounds(self):
        for envelope in (
            SkinRange(a_min=43, a_max=42),
            SkinRange(b_min=50, b_max=50),
            SkinRange(a_max=float("nan")),
            SkinRange(b_min=-129),
        ):
            with self.assertRaises(ValueError):
                MatchSettings(skin_range=envelope).validate()

    def test_very_pale_skin_remains_eligible_but_neutral_white_is_excluded(self):
        colours = np.array([[(250, 247, 242), (244, 240, 232), (245, 245, 245)]], dtype=np.uint8)
        scores = skin_confidence(colours)[0]
        self.assertTrue(np.all(scores[:2] >= 0.5))
        self.assertEqual(scores[2], 0)

    def test_adaptive_feather_keeps_a_full_strength_interior_on_thin_masks(self):
        mask = np.zeros((100, 100), bool)
        mask[30:70, 43:57] = True
        fixed = inward_feather(mask, 24)
        adaptive = inward_feather(mask, 24, adaptive=True)
        self.assertLess(fixed.max(), 0.2)
        self.assertEqual(adaptive.max(), 1)
        self.assertTrue(np.all(adaptive[~mask] == 0))
        self.assertTrue(np.all(adaptive[30, :] == 0))

    def test_full_strength_matches_uniform_reference(self):
        original = np.full((120, 160, 3), (180, 130, 105), np.uint8)
        mask = np.zeros((120, 160), np.uint8)
        mask[30:90, 40:120] = 255
        generated = shifted(original, mask, (20, 5, 0))
        output, report = match_skin(
            generated, Image.fromarray(original), mask, MatchSettings(strength=1, brightness=1, feather=0)
        )
        self.assertEqual(report.reason, "corrected")
        expected = rgb_to_lab(original)[mask > 0].mean(axis=0)
        actual = rgb_to_lab(np.array(output))[mask > 0].mean(axis=0)
        self.assertLess(np.linalg.norm(actual - expected), 0.5)

    def test_default_matching_removes_most_chroma_error_on_small_patch(self):
        original, mask = scene()
        generated = shifted(original, mask, (12, -3, -6))
        output, _ = match_skin(generated, Image.fromarray(original), mask)
        ref = rgb_to_lab(original)[mask > 0].mean(axis=0)
        before = rgb_to_lab(np.array(generated))[mask > 0].mean(axis=0)
        after = rgb_to_lab(np.array(output))[mask > 0].mean(axis=0)
        self.assertLess(np.linalg.norm(after[1:] - ref[1:]), 0.45 * np.linalg.norm(before[1:] - ref[1:]))

    def test_already_matching_composite_boundary_is_preserved(self):
        original, mask = scene()
        generated = np.array(shifted(original, mask))
        generated[65:68, 95:155] = original[65:68, 95:155]
        source = Image.fromarray(generated)
        output, report = match_skin(source, Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(output)[65:68, 95:155], generated[65:68, 95:155])

    def test_original_background_does_not_guide_skin_boundary(self):
        original, mask = scene()
        generated = shifted(original, mask)
        original[mask > 0] = (10, 50, 100)
        output, report = match_skin(generated, Image.fromarray(original), mask)
        self.assertEqual(report.reason, "corrected")
        np.testing.assert_array_equal(np.array(output)[65, 95:155], np.array(generated)[65, 95:155])


if __name__ == "__main__":
    unittest.main()
