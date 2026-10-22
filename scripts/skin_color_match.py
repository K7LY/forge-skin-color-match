"""Stable Diffusion WebUI Forge adapter. SPDX-License-Identifier: AGPL-3.0-only."""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

import gradio as gr
import numpy as np
from modules import images, processing, scripts, shared
from PIL import Image, ImageOps

# Forge adds extension roots today; retain support for alternate script loaders.
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from skinmatch_core import MatchSettings, SkinRange, mask_array, match_skin  # noqa: E402

logger = logging.getLogger("forge.skin_color_match")
STATE_KEY = "_forge_skin_color_match"


def match_settings(strength, radius, feather, brightness, mode, a_min, a_max, b_min, b_max):
    return MatchSettings(
        float(strength),
        int(radius),
        int(feather),
        float(brightness),
        mode,
        skin_range=SkinRange(float(a_min), float(a_max), float(b_min), float(b_max)),
    )


@dataclass
class RequestState:
    raw_mask: Image.Image
    manual_mask: object
    references: list = field(default_factory=list)
    edit_masks: list = field(default_factory=list)
    manual_masks: list = field(default_factory=list)
    overlay_sizes: list = field(default_factory=list)
    reports: list = field(default_factory=list)
    latent_canvas: bool = False
    skip_reason: str = "not_prepared"
    warned: bool = False


class Script(scripts.Script):
    def title(self):
        return "Skin Color Match"

    def show(self, is_img2img):
        return scripts.AlwaysVisible if is_img2img else False

    def ui(self, is_img2img):
        with gr.Accordion("Skin Color Match", open=False):
            enabled = gr.Checkbox(label="Enable Skin Color Match", value=False)
            strength = gr.Slider(0, 1, value=0.7, step=0.05, label="Correction Strength")
            radius = gr.Slider(1, 256, value=48, step=1, label="Reference Radius (px)")
            feather = gr.Slider(0, 128, value=24, step=1, label="Mask Feather (px)")
            brightness = gr.Slider(0, 1, value=0.3, step=0.05, label="Brightness Correction")
            space = gr.Dropdown(choices=["LAB"], value="LAB", label="Color Space")
            mode = gr.Radio(choices=["Auto", "Manual"], value="Auto", label="Reference Mode")
            manual = gr.Image(
                label="Manual reference mask (white = reference skin, original image size)",
                type="pil",
                image_mode="RGBA",
                sources=["upload"],
                visible=False,
            )
            mode.change(fn=lambda value: gr.update(visible=value == "Manual"), inputs=mode, outputs=manual)
            with gr.Accordion("Skin Color Range (LAB)", open=False):
                gr.Markdown(
                    "Only colours inside both ranges are sampled and corrected. "
                    "a: green (-) to red (+); b: blue (-) to yellow (+). "
                    "Narrower ranges help exclude nearby clothing colours."
                )
                a_min = gr.Slider(-20, 60, value=-2, step=1, label="Skin a Minimum")
                a_max = gr.Slider(-20, 60, value=42, step=1, label="Skin a Maximum")
                b_min = gr.Slider(-20, 80, value=0, step=1, label="Skin b Minimum")
                b_max = gr.Slider(-20, 80, value=50, step=1, label="Skin b Maximum")
            gr.Markdown(
                "CPU only. Manual: upload a white-on-black mask aligned with the original image. "
                "Disable Forge's img2img color correction; this extension skips when it is active. "
                "Colour heuristics can confuse skin-coloured fabric. See README for limitations. "
                "[Source / AGPL-3.0](https://github.com/K7LY/forge-skin-color-match)"
            )
        return [
            enabled,
            strength,
            radius,
            feather,
            brightness,
            space,
            mode,
            manual,
            a_min,
            a_max,
            b_min,
            b_max,
        ]

    def process(
        self,
        p,
        enabled=False,
        strength=0.7,
        radius=48,
        feather=24,
        brightness=0.3,
        space="LAB",
        mode="Auto",
        manual=None,
        a_min=-2,
        a_max=42,
        b_min=0,
        b_max=50,
    ):
        # Request-local state: no counters/images survive on the shared Script.
        setattr(p, STATE_KEY, None)
        if not enabled or strength == 0 or getattr(p, "image_mask", None) is None:
            return
        if not getattr(p, "init_images", None):
            return
        try:
            if not hasattr(scripts.Script, "postprocess_image_after_composite"):
                raise ValueError("Forge lacks the required after-composite hook")
            if space != "LAB":
                raise ValueError("Only LAB is supported")
            match_settings(strength, radius, feather, brightness, mode, a_min, a_max, b_min, b_max).validate()
            raw = processing.create_binary_mask(p.image_mask, round=getattr(p, "mask_round", True)).copy()
            if getattr(p, "inpainting_mask_invert", 0):
                raw = ImageOps.invert(raw)
            state = RequestState(raw, manual.copy() if manual is not None else None)
            setattr(p, STATE_KEY, state)
        except Exception:
            logger.exception("Skin Color Match setup skipped; generation is unchanged")

    def before_process_init_images(self, p, pp, *args, **kwargs):
        state = getattr(p, STATE_KEY, None)
        if state is None:
            return
        # Forge may reuse p in directory batches: rebuild, do not reuse old maps.
        state.references.clear()
        state.edit_masks.clear()
        state.manual_masks.clear()
        state.overlay_sizes.clear()
        try:
            if pp.get("image_mask") is None:
                state.skip_reason = "empty_inpaint_mask"
                return
            crop = pp.get("crop_region")
            resize_mode = int(getattr(p, "resize_mode", 0))
            state.latent_canvas = crop is None and resize_mode == 3
            for source in p.init_images:
                if source.size != state.raw_mask.size:
                    raise ValueError("Original mask and source dimensions differ")
                reference = images.flatten(source.copy(), shared.opts.img2img_background_color)
                edit = state.raw_mask.copy()
                manual = state.manual_mask
                if manual is not None:
                    if manual.size != source.size:
                        raise ValueError("Manual reference mask must match the original image size")
                    manual = Image.fromarray(np.rint(mask_array(manual, source.size) * 255).astype(np.uint8))
                if crop is None:

                    def resize(mask):
                        return images.resize_image(
                            resize_mode, mask, p.width, p.height, upscaler_name="None"
                        ).convert("L")

                    edit = resize(edit)
                    if manual is not None:
                        manual = resize(manual)
                    if resize_mode == 3:
                        # Forge keeps an original-sized overlay, alpha-composited
                        # at (0, 0) onto a generated width/height canvas. PIL clips
                        # excess overlay pixels rather than resizing that canvas.
                        edit = images.resize_image(
                            resize_mode, edit, *source.size, upscaler_name="None"
                        ).convert("L")
                        if manual is not None:
                            manual = images.resize_image(
                                resize_mode, manual, *source.size, upscaler_name="None"
                            ).convert("L")

                        def output_canvas(image):
                            canvas = Image.new(image.mode, (p.width, p.height))
                            canvas.paste(image, (0, 0))
                            return canvas

                        reference, edit = output_canvas(reference), output_canvas(edit)
                        if manual is not None:
                            manual = output_canvas(manual)
                    else:
                        reference = images.resize_image(
                            resize_mode, reference, p.width, p.height, upscaler_name="None"
                        )
                # Remove Lanczos ringing from binary user masks; do not expand support.
                if getattr(p, "mask_round", True):
                    edit = edit.point(lambda value: 255 if value > 128 else 0)
                state.references.append(reference.convert("RGB"))
                state.edit_masks.append(edit)
                state.manual_masks.append(manual)
                state.overlay_sizes.append(
                    source.size if crop is not None or resize_mode == 3 else reference.size
                )
            state.skip_reason = "ready"
        except Exception:
            state.skip_reason = "coordinate_preparation_failed"
            logger.exception("Skin Color Match coordinate preparation skipped")

    def postprocess_image_after_composite(
        self,
        p,
        pp,
        enabled=False,
        strength=0.7,
        radius=48,
        feather=24,
        brightness=0.3,
        space="LAB",
        mode="Auto",
        manual=None,
        a_min=-2,
        a_max=42,
        b_min=0,
        b_max=50,
    ):
        if not enabled or strength == 0:
            return
        state = getattr(p, STATE_KEY, None)
        if state is None or state.skip_reason != "ready":
            return
        try:
            if getattr(shared.opts, "img2img_color_correction", False) or getattr(
                p, "color_corrections", None
            ):
                if not state.warned:
                    logger.warning(
                        "Skin Color Match skipped: disable Forge img2img color correction to avoid double correction"
                    )
                    state.warned = True
                return
            if not getattr(shared.opts, "overlay_inpaint", True):
                return
            batch_index = getattr(p, "batch_index", getattr(pp, "index", 0) % max(1, p.batch_size))
            index = 0 if len(state.references) == 1 else batch_index
            if not 0 <= index < len(state.references):
                raise ValueError("Cannot map generated image to its source")
            reference, edit = state.references[index], state.edit_masks[index]
            if reference.size != pp.image.size:
                raise ValueError("Another extension changed the output dimensions; skipping")
            overlay = getattr(p, "mask_for_overlay", None)
            overlays = getattr(p, "overlay_images", None)
            if overlay is None or not overlays or batch_index >= len(overlays):
                return
            overlay_image = overlays[batch_index]
            if overlay.size != state.overlay_sizes[index] or overlay_image.size != overlay.size:
                raise ValueError("Unexpected overlay canvas dimensions")
            if state.latent_canvas:

                def output_canvas(image):
                    canvas = Image.new(image.mode, reference.size)
                    canvas.paste(image, (0, 0))
                    return canvas

                overlay, overlay_image = output_canvas(overlay), output_canvas(overlay_image)
            edit_array = mask_array(edit, reference.size)
            # Already inverted/blurred/resized by Forge: NEVER invert overlay again.
            edit_array = np.minimum(edit_array, mask_array(overlay, reference.size))
            # Actual overlay alpha also limits correction to composited pixels.
            if overlay_image.mode != "RGBA" or overlay_image.size != reference.size:
                raise ValueError("Unexpected overlay canvas")
            edit_array = np.minimum(
                edit_array, 1 - np.asarray(overlay_image.getchannel("A"), dtype=np.float32) / 255
            )
            settings = match_settings(strength, radius, feather, brightness, mode, a_min, a_max, b_min, b_max)
            result, report = match_skin(pp.image, reference, edit_array, settings, state.manual_masks[index])
            state.reports.append(report)
            if report.reason == "corrected":
                logger.info(
                    "Skin Color Match: %d region(s), mean-colour Delta E76 %.2f -> %.2f",
                    len(report.regions),
                    np.mean([r.delta_e_before for r in report.regions]),
                    np.mean([r.delta_e_after for r in report.regions]),
                )
            else:
                logger.debug("Skin Color Match skipped: %s", report.reason)
            pp.image = result
        except Exception:
            logger.exception("Skin Color Match failed; keeping the generated image")

    def postprocess(self, p, processed, *args):
        # Release full-sized snapshots promptly after all iterations finish.
        setattr(p, STATE_KEY, None)
