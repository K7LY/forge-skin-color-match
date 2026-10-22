import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
from PIL import Image

from forge_harness import DEFAULT_ARGS, Host
from test_core import scene, shifted


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.host = Host()
        original, self.mask = scene()
        self.original = Image.fromarray(original)
        self.generated = shifted(original, self.mask)
        self.p = self.host.request(self.original, Image.fromarray(self.mask))

    def test_extension_import_and_img2img_visibility(self):
        self.assertIs(self.host.script.show(True), self.host.scripts.AlwaysVisible)
        self.assertFalse(self.host.script.show(False))

    def test_ui_builds_with_requested_defaults(self):
        import gradio as gr

        with gr.Blocks():
            controls = self.host.script.ui(True)
        self.assertEqual(len(controls), 12)
        self.assertEqual([x.value for x in controls[:7]], [False, 0.7, 48, 24, 0.3, "LAB", "Auto"])
        self.assertFalse(controls[7].visible)
        self.assertEqual([x.value for x in controls[8:]], [-2, 42, 0, 50])

    def test_ui_skin_ranges_reach_core_and_bad_ranges_skip(self):
        args = DEFAULT_ARGS + [-2, 42, 0, 8]  # exclude this fixture's warm skin
        self.host.prepare(self.p, args)
        pp = SimpleNamespace(image=self.generated, index=0)
        self.host.script.postprocess_image_after_composite(self.p, pp, *args)
        self.assertIs(pp.image, self.generated)
        with self.assertLogs("forge.skin_color_match", level="ERROR"):
            self.host.script.process(self.p, *(DEFAULT_ARGS + [42, -2, 0, 50]))
        self.assertIsNone(getattr(self.p, self.host.adapter.STATE_KEY))

    def test_hook_corrects_and_preserves_prompt_seed_and_source(self):
        self.p.prompt, self.p.seed = "test prompt", 123
        before = self.original.tobytes()
        self.host.prepare(self.p, DEFAULT_ARGS)
        pp = SimpleNamespace(image=self.generated, index=0)
        self.host.script.postprocess_image_after_composite(self.p, pp, *DEFAULT_ARGS)
        self.assertIsNot(pp.image, self.generated)
        self.assertEqual((self.p.prompt, self.p.seed, self.original.tobytes()), ("test prompt", 123, before))
        np.testing.assert_array_equal(
            np.array(pp.image)[self.mask == 0], np.array(self.generated)[self.mask == 0]
        )

    def test_disabled_zero_and_non_inpaint_keep_image_identity(self):
        for enabled, strength, mask in (
            (False, 0.7, self.p.image_mask),
            (True, 0, self.p.image_mask),
            (True, 0.7, None),
        ):
            args = DEFAULT_ARGS.copy()
            args[:2] = [enabled, strength]
            self.p.image_mask = mask
            self.host.script.process(self.p, *args)
            pp = SimpleNamespace(image=self.generated, index=0)
            self.host.script.postprocess_image_after_composite(self.p, pp, *args)
            self.assertIs(pp.image, self.generated)

    def test_error_keeps_generated_result(self):
        self.host.prepare(self.p, DEFAULT_ARGS)
        pp = SimpleNamespace(image=self.generated, index=0)
        with patch.object(
            self.host.adapter, "match_skin", side_effect=RuntimeError("intentional test failure")
        ):
            with self.assertLogs("forge.skin_color_match", level="ERROR"):
                self.host.script.postprocess_image_after_composite(self.p, pp, *DEFAULT_ARGS)
        self.assertIs(pp.image, self.generated)

    def test_existing_forge_correction_skips(self):
        self.host.prepare(self.p, DEFAULT_ARGS)
        self.host.opts.img2img_color_correction = True
        pp = SimpleNamespace(image=self.generated, index=0)
        with self.assertLogs("forge.skin_color_match", level="WARNING"):
            self.host.script.postprocess_image_after_composite(self.p, pp, *DEFAULT_ARGS)
        self.assertIs(pp.image, self.generated)

    def test_changed_canvas_fails_safely(self):
        self.host.prepare(self.p, DEFAULT_ARGS)
        pp = SimpleNamespace(image=self.generated.resize((100, 100)), index=0)
        saved = pp.image
        with self.assertLogs("forge.skin_color_match", level="ERROR"):
            self.host.script.postprocess_image_after_composite(self.p, pp, *DEFAULT_ARGS)
        self.assertIs(pp.image, saved)

    def test_manual_dimensions_checked_and_no_auto_fallback(self):
        args = DEFAULT_ARGS.copy()
        args[6:] = ["Manual", Image.new("L", (10, 10), 255)]
        with self.assertLogs("forge.skin_color_match", level="ERROR"):
            self.host.prepare(self.p, args)
        pp = SimpleNamespace(image=self.generated, index=0)
        self.host.script.postprocess_image_after_composite(self.p, pp, *args)
        self.assertIs(pp.image, self.generated)

    def test_request_states_are_isolated_and_released(self):
        self.host.prepare(self.p, DEFAULT_ARGS)
        first = getattr(self.p, self.host.adapter.STATE_KEY)
        other = self.host.request(self.original, Image.fromarray(self.mask))
        self.host.prepare(other, DEFAULT_ARGS)
        self.assertIsNot(first, getattr(other, self.host.adapter.STATE_KEY))
        self.host.script.postprocess(self.p, None)
        self.assertIsNone(getattr(self.p, self.host.adapter.STATE_KEY))
        self.assertIsNotNone(getattr(other, self.host.adapter.STATE_KEY))


if __name__ == "__main__":
    unittest.main()
