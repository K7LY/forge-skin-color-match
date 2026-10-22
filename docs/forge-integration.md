# Forge integration audit

Reviewed upstream commit: `dfdcbab685e57677014f05a3309b48cc87383167`.
This document describes that revision, not every Forge fork or future revision.

## Verified call order

From [`modules/processing.py`](https://github.com/lllyasviel/stable-diffusion-webui-forge/blob/dfdcbab685e57677014f05a3309b48cc87383167/modules/processing.py):

1. `p.scripts.process(p)` runs before `p.init(...)`.
2. Img2Img `init` takes `p.image_mask`, runs `create_binary_mask`, applies inversion once, then Gaussian blur.
3. It sets crop/overlay masks and calls `before_process_init_images` before cropping/filling input image pixels.
4. It prepares original-image overlays, then encodes the model input.
5. After sampling, restoration and `postprocess_image`, Forge chooses per-image overlays.
6. `postprocess_maskoverlay`, built-in colour correction and `apply_overlay` run.
7. `postprocess_image_after_composite` sees the composited image, before gallery/sample saving.

The extension snapshots the raw mask in `process`, prepares original reference coordinates in
`before_process_init_images`, and only replaces `pp.image` in the final hook. The Script object holds no
request images or counters; state lives on `p` and is released in `postprocess`.

## Coordinate and polarity map

| Value | Coordinates and meaning |
| --- | --- |
| `p.init_images` | Original PIL images; not replaced with the model's cropped/filled arrays by `init`. One input is repeated across a batch; multiple inputs use the corresponding batch index each iteration. |
| `p.image_mask` | Original mask, not the latent tensor. White selects editing before inversion. RGBA masks with non-opaque alpha use alpha; fully opaque masks use luminance. |
| `p.mask` / `p.nmask` | Latent tensors. They are deliberately not used by this extension. |
| `p.mask_for_overlay` | White selects generated/composited pixels; inversion is already applied. It can include blurred pixels outside the user's raw mask. Never invert it again. |
| `pp.image` | Composite output. Normally original-sized for Only masked and generation-sized for Whole picture; latent upscale has special clipping behavior below. |
| `p.batch_index` | Index within the current output batch, set immediately before the image hooks. |
| `pp.index` | Global output index (`i + iteration * batch_size`); only used as a fallback. |

The actual support is the minimum of the aligned raw edit mask, processed overlay mask and
`1 - overlay.alpha`. Raw masks are captured before Forge blur. Binary masks use a `>128` threshold
after resizing to suppress Lanczos ringing. With `mask_round=False`, soft weights are kept.

## Resizing

See [`modules/images.py:resize_image`](https://github.com/lllyasviel/stable-diffusion-webui-forge/blob/dfdcbab685e57677014f05a3309b48cc87383167/modules/images.py).
The adapter invokes Forge's own geometry function with `upscaler_name="None"`; reference alignment never
loads an upscaling model. Reference colour statistics therefore use ordinary resampling even if the host
uses a learned img2img upscaler for model input preparation.

- **Only masked:** `mask_for_overlay` stays in original coordinates. The sampling crop is resized to
  model dimensions and placed back using `p.paste_to`. The extension never uses the crop as its original
  reference image or scales the original mask to sampling resolution.
- **Whole picture, mode 0:** direct resize to generation dimensions.
- **Whole picture, mode 1:** aspect-preserving resize followed by centered crop.
- **Whole picture, mode 2:** aspect-preserving fit and Forge's edge filling.
- **Whole picture, mode 3 (latent upscale):** Forge keeps original-sized input overlays but produces a
  generation-sized canvas. `PIL.Image.alpha_composite` places the overlay at `(0, 0)`, clipping overflow.
  The raw mask follows the same two mask transforms (to generation size, then back to source size).
  Reference/edit/manual masks are then pasted at `(0, 0)` into an output-sized canvas, with no reference
  or correction allowed outside the original coverage. This preserves this upstream behavior rather than
  silently stretching the reference or assuming the output is original-sized.

All arrays are checked for exact matching dimensions before colour processing. Unknown canvas changes
skip correction. `overlay_inpaint=False` is intentionally a skip: the required composite is absent.

## Executable verification and limits

The optional source tests download the pinned upstream files, select specific functions through Python
AST, and run the actual resize, mask preparation, input overlay preparation and recompositing functions.
The real `StableDiffusionProcessingImg2Img.init` body runs up to (excluding) the torch tensor/latent stage.
This tests both coordinate transforms and output pixels without copying Forge code into this repository.
AST call-order assertions also check the after-composite hook precedes normal sample saving.

This harness replaces model/sampler objects and the script host. It is not a live Forge launch,
extension discovery test, diffusion test or proof of interoperability with other extensions.
Custom `postprocess_maskoverlay` changes made by other extensions may differ from `p.mask_for_overlay`
and `p.overlay_images`; those combinations require actual host testing. Images added/reordered by other
batch scripts can defeat source mapping even if sizes match; such behavior is not guaranteed compatible.
