import ast
import unittest
from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageOps

from forge_harness import DEFAULT_ARGS, SOURCE, Host
from test_core import scene, shifted


@unittest.skipUnless(
    all((SOURCE / f"{name}.py").exists() for name in ("processing", "scripts", "images", "masking")),
    "Optional: run python tools/fetch_forge_sources.py first",
)
class ForgeSourceTests(unittest.TestCase):
    def setUp(self):
        self.host = Host(source_backed=True)

    def test_actual_upstream_hook_order(self):
        code = (SOURCE / "processing.py").read_text(encoding="utf-8")
        tree = ast.parse(code)
        function = next(
            n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "process_images_inner"
        )
        calls = [(n.lineno, ast.unparse(n.func)) for n in ast.walk(function) if isinstance(n, ast.Call)]

        def line(suffix):
            return sorted(n for n, name in calls if name.endswith(suffix))

        self.assertLess(line("scripts.process")[0], line("p.init")[0])
        self.assertLess(line("apply_color_correction")[0], line("postprocess_image_after_composite")[0])
        self.assertLess(max(line("apply_overlay")), line("postprocess_image_after_composite")[0])
        self.assertTrue(
            any(n > line("postprocess_image_after_composite")[0] for n in line("images.save_image"))
        )

    def test_real_mask_geometry_all_resize_modes_inversion_and_batches(self):
        original_array, mask = scene()
        original = Image.fromarray(original_array)
        for full_res in (True, False):
            for resize_mode in range(4):
                for invert in (0, 1):
                    with self.subTest(full_res=full_res, resize_mode=resize_mode, invert=invert):
                        raw = Image.fromarray(mask)
                        if invert:
                            raw = ImageOps.invert(raw)
                        p = self.host.request(
                            original, raw, full_res, resize_mode, (200, 224), batch_size=2, invert=invert
                        )
                        self.host.prepare(p, DEFAULT_ARGS)
                        state = getattr(p, self.host.adapter.STATE_KEY)
                        self.assertEqual(state.skip_reason, "ready")
                        expected_size = original.size if full_res else (200, 224)
                        self.assertEqual(state.references[0].size, expected_size)
                        self.assertEqual(state.edit_masks[0].size, expected_size)
                        self.assertEqual(
                            p.mask_for_overlay.size,
                            original.size if full_res or resize_mode == 3 else expected_size,
                        )
                        # Cropped generated image is recomposited by Forge's real function.
                        if full_res:
                            x, y, w, h = p.paste_to
                            target = (
                                state.references[0].crop((x, y, x + w, y + h)).resize((p.width, p.height))
                            )
                        else:
                            target = state.references[0].resize((p.width, p.height))
                        target = Image.fromarray(
                            np.clip(np.array(target).astype(int) + [24, 7, 1], 0, 255).astype(np.uint8)
                        )
                        for iteration in range(2):
                            for batch_index in range(2):
                                p.iteration, p.batch_index = iteration, batch_index
                                generated, _ = self.host.apply_overlay(
                                    target, p.paste_to, p.overlay_images[batch_index]
                                )
                                self.assertEqual(generated.size, expected_size)
                                before = np.array(generated)
                                pp = SimpleNamespace(
                                    image=generated, index=batch_index + iteration * p.batch_size
                                )
                                self.host.script.postprocess_image_after_composite(p, pp, *DEFAULT_ARGS)
                                self.assertIsNot(
                                    pp.image, generated, "Expected actual correction, not merely a safe skip"
                                )
                                actual = np.array(pp.image)
                                edit = np.asarray(state.edit_masks[0]) > 0
                                np.testing.assert_array_equal(actual[~edit], before[~edit])
                                self.assertLess(
                                    state.reports[-1].regions[0].delta_e_after,
                                    state.reports[-1].regions[0].delta_e_before,
                                )

    def test_real_rgba_mask_uses_alpha_and_inverts_once(self):
        original, mask = scene()
        rgba = Image.new("RGBA", (256, 192), (255, 0, 0, 0))
        rgba.putalpha(Image.fromarray(mask))
        for invert in (0, 1):
            p = self.host.request(Image.fromarray(original), rgba, invert=invert)
            self.host.prepare(p, DEFAULT_ARGS)
            state = getattr(p, self.host.adapter.STATE_KEY)
            np.testing.assert_array_equal(np.asarray(state.raw_mask), 255 - mask if invert else mask)

    def test_real_empty_mask_and_blur_outside_user_support_are_safe(self):
        original, mask = scene()
        p = self.host.request(Image.fromarray(original), Image.fromarray(mask))
        self.host.prepare(p, DEFAULT_ARGS)
        self.assertTrue(np.any((np.array(p.mask_for_overlay) > 0) & (mask == 0)))
        source = shifted(original, mask)
        pp = SimpleNamespace(image=source, index=0)
        self.host.script.postprocess_image_after_composite(p, pp, *DEFAULT_ARGS)
        np.testing.assert_array_equal(np.array(pp.image)[mask == 0], np.array(source)[mask == 0])
        p.image_mask = Image.new("L", p.image_mask.size)
        self.host.prepare(p, DEFAULT_ARGS)
        self.assertEqual(getattr(p, self.host.adapter.STATE_KEY).skip_reason, "empty_inpaint_mask")

    def test_multiple_distinct_sources_are_mapped_by_batch_index(self):
        first, mask = scene(tone=(120, 80, 60))
        second, _ = scene(tone=(220, 175, 150))
        p = self.host.request(
            [Image.fromarray(first), Image.fromarray(second)], Image.fromarray(mask), batch_size=2
        )
        self.host.prepare(p, DEFAULT_ARGS)
        state = getattr(p, self.host.adapter.STATE_KEY)
        for iteration in range(2):
            for index in range(2):
                p.batch_index, p.iteration = index, iteration
                generated = shifted(np.array(state.references[index]), mask)
                pp = SimpleNamespace(image=generated, index=index + iteration * 2)
                self.host.script.postprocess_image_after_composite(p, pp, *DEFAULT_ARGS)
                self.assertIsNot(pp.image, generated)
                self.assertLess(
                    state.reports[-1].regions[0].delta_e_after, state.reports[-1].regions[0].delta_e_before
                )

    def test_manual_reference_tracks_all_real_resize_coordinates(self):
        original, mask = scene()
        manual = np.zeros_like(mask)
        manual[70:125, 60:85] = 255
        args = DEFAULT_ARGS.copy()
        args[6:] = ["Manual", Image.fromarray(manual)]
        for full_res in (True, False):
            for resize_mode in range(4):
                with self.subTest(full_res=full_res, resize_mode=resize_mode):
                    p = self.host.request(
                        Image.fromarray(original), Image.fromarray(mask), full_res, resize_mode, (200, 224)
                    )
                    self.host.prepare(p, args)
                    state = getattr(p, self.host.adapter.STATE_KEY)
                    generated = shifted(np.array(state.references[0]), np.asarray(state.edit_masks[0]))
                    pp = SimpleNamespace(image=generated, index=0)
                    self.host.script.postprocess_image_after_composite(p, pp, *args)
                    self.assertIsNot(pp.image, generated)
                    self.assertLess(
                        state.reports[-1].regions[0].delta_e_after,
                        state.reports[-1].regions[0].delta_e_before,
                    )

    def test_real_soft_alpha_mask_and_directory_request_reuse(self):
        import cv2

        original, mask = scene()
        soft = cv2.GaussianBlur(mask, (15, 15), 3)
        rgba = Image.new("RGBA", (256, 192), (255, 0, 0, 0))
        rgba.putalpha(Image.fromarray(soft))
        p = self.host.request(Image.fromarray(original), rgba)
        p.mask_round = False
        self.host.prepare(p, DEFAULT_ARGS)
        state = getattr(p, self.host.adapter.STATE_KEY)
        np.testing.assert_array_equal(np.asarray(state.raw_mask), soft)
        generated = shifted(original, soft)
        pp = SimpleNamespace(image=generated, index=0)
        self.host.script.postprocess_image_after_composite(p, pp, *DEFAULT_ARGS)
        self.assertIsNot(pp.image, generated)
        np.testing.assert_array_equal(np.array(pp.image)[soft == 0], np.array(generated)[soft == 0])
        # Forge's directory batch path reuses p but replaces source and raw mask.
        old = state
        new_source, new_mask = scene(tone=(120, 75, 50))
        p.init_images, p.image_mask = [Image.fromarray(new_source)], Image.fromarray(new_mask)
        self.host.prepare(p, DEFAULT_ARGS)
        self.assertIsNot(old, getattr(p, self.host.adapter.STATE_KEY))
        np.testing.assert_array_equal(
            np.asarray(getattr(p, self.host.adapter.STATE_KEY).references[0]), new_source
        )


if __name__ == "__main__":
    unittest.main()
