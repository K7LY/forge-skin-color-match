"""Small host doubles plus optional execution of pinned upstream geometry code.

The source-backed harness executes Forge's real mask/overlay preparation before
the torch latent stage. It does not start Forge, load models or run diffusion.
"""

import ast
import importlib.util
import logging
import os
import sys
import types
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from PIL import Image, ImageOps

os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
import gradio  # noqa: E402,F401 -- import once, outside temporary sys.modules patches

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("FORGE_SOURCE_DIR", ROOT / ".research" / "forge"))


def simple_resize(mode, image, width, height, upscaler_name=None):
    if mode == 0:
        return image.resize((width, height), Image.Resampling.LANCZOS)
    if mode == 1:
        return ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)
    return ImageOps.pad(image, (width, height), Image.Resampling.LANCZOS)


def binary_mask(image, round=True):
    if image.mode == "RGBA" and image.getextrema()[-1] != (255, 255):
        image = image.getchannel("A")
        if round:
            image = image.point(lambda x: 255 if x > 128 else 0)
    return image.convert("L")


class Host:
    def __init__(self, source_backed=False):
        self.opts = types.SimpleNamespace(
            img2img_background_color="#ffffff",
            img2img_color_correction=False,
            overlay_inpaint=True,
            upscaler_for_img2img="None",
            save_init_img=False,
        )
        self.images = types.ModuleType("modules.images")
        self.images.resize_image = simple_resize
        self.images.flatten = lambda image, colour: Image.alpha_composite(
            Image.new("RGBA", image.size, colour), image.convert("RGBA")
        ).convert("RGB")
        self.processing = types.ModuleType("modules.processing")
        self.processing.create_binary_mask = binary_mask
        self.scripts = types.ModuleType("modules.scripts")
        self.scripts.Script = type("Script", (), {"postprocess_image_after_composite": lambda *a: None})
        self.scripts.AlwaysVisible = object()
        self.shared = types.ModuleType("modules.shared")
        self.shared.opts = self.opts
        if source_backed:
            self._load_sources()
        package = types.ModuleType("modules")
        package.images, package.processing = self.images, self.processing
        package.scripts, package.shared = self.scripts, self.shared
        modules = {
            "modules": package,
            "modules.images": self.images,
            "modules.processing": self.processing,
            "modules.scripts": self.scripts,
            "modules.shared": self.shared,
        }
        spec = importlib.util.spec_from_file_location(
            "_skinmatch_adapter_test", ROOT / "scripts" / "skin_color_match.py"
        )
        self.adapter = importlib.util.module_from_spec(spec)
        # dataclass resolves its module while defining RequestState.
        with patch.dict(sys.modules, {**modules, spec.name: self.adapter}):
            spec.loader.exec_module(self.adapter)
        self.script = self.adapter.Script()

    def _load_sources(self):
        env = {
            "Image": Image,
            "ImageOps": ImageOps,
            "np": np,
            "cv2": cv2,
            "opts": self.opts,
            "LANCZOS": Image.Resampling.LANCZOS,
            "shared": self.shared,
            "images": self.images,
            "logging": logging,
        }
        names = {
            "images": {"resize_image", "flatten"},
            "masking": {"get_crop_region_v2", "expand_crop_region"},
            "processing": {"create_binary_mask", "uncrop", "apply_overlay"},
        }
        trees = {}
        for file, wanted in names.items():
            tree = ast.parse((SOURCE / f"{file}.py").read_text(encoding="utf-8"))
            trees[file] = tree
            selected = [
                node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in wanted
            ]
            exec(compile(ast.Module(body=selected, type_ignores=[]), f"upstream/{file}.py", "exec"), env)
        self.images.resize_image, self.images.flatten = env["resize_image"], env["flatten"]
        self.processing.create_binary_mask = env["create_binary_mask"]
        env["masking"] = types.SimpleNamespace(
            get_crop_region_v2=env["get_crop_region_v2"], expand_crop_region=env["expand_crop_region"]
        )
        env["sd_samplers"] = types.SimpleNamespace(create_sampler=lambda *args: None)
        klass = next(
            n
            for n in trees["processing"].body
            if isinstance(n, ast.ClassDef) and n.name == "StableDiffusionProcessingImg2Img"
        )
        function = next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == "init")
        # Execute real upstream preparation through batch/overlay duplication,
        # stopping exactly where CPU image arrays enter torch latent encoding.
        cutoff = next(
            i
            for i, n in enumerate(function.body)
            if isinstance(n, ast.Assign) and ast.unparse(n.value) == "torch.from_numpy(batch_images)"
        )
        function.body = function.body[:cutoff]
        exec(compile(ast.Module(body=[function], type_ignores=[]), "upstream/processing.init", "exec"), env)
        self.upstream_init = env["init"]
        self.apply_overlay = env["apply_overlay"]

    def request(self, original, mask, full_res=True, resize_mode=0, size=(256, 192), batch_size=1, invert=0):
        originals = original if isinstance(original, list) else [original]
        return types.SimpleNamespace(
            image_mask=mask,
            init_images=originals,
            batch_size=batch_size,
            inpaint_full_res=full_res,
            resize_mode=resize_mode,
            width=size[0],
            height=size[1],
            mask_round=True,
            inpainting_mask_invert=invert,
            mask_blur_x=4,
            mask_blur_y=4,
            mask_blur=4,
            inpaint_full_res_padding=16,
            inpainting_fill=1,
            latent_mask=None,
            paste_to=None,
            overlay_images=None,
            color_corrections=None,
            batch_index=0,
            iteration=0,
            sd_model=types.SimpleNamespace(comments=[]),
            sampler_name="test",
            denoising_strength=0.75,
            extra_generation_params={},
        )

    def prepare(self, p, args):
        self.script.process(p, *args)
        if hasattr(self, "upstream_init"):
            p.scripts = types.SimpleNamespace(
                before_process_init_images=lambda p, pp: self.script.before_process_init_images(p, pp, *args)
            )
            self.upstream_init(p, [], [], [])
        else:
            p.mask_for_overlay = p.image_mask.copy()
            self.script.before_process_init_images(
                p,
                {
                    "crop_region": (0, 0, *p.init_images[0].size) if p.inpaint_full_res else None,
                    "image_mask": p.image_mask,
                },
                *args,
            )
            p.overlay_images = []
            for source in p.init_images:
                if not p.inpaint_full_res:
                    source = self.images.resize_image(p.resize_mode, source, p.width, p.height)
                overlay = source.convert("RGBA")
                overlay.putalpha(ImageOps.invert(p.mask_for_overlay))
                p.overlay_images.append(overlay)
            if len(p.init_images) == 1:
                p.overlay_images *= p.batch_size


DEFAULT_ARGS = [True, 0.7, 48, 24, 0.3, "LAB", "Auto", None]
