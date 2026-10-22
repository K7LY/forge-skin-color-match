# Validation record

Date: 2026-10-23. Host: Windows, Python 3.10.9.
Source revision: Forge `dfdcbab685e57677014f05a3309b48cc87383167`.

## Executed locally

- **49 tests passed**, zero skips with the downloaded Forge sources present.
- Python compile checks passed for the adapter, core, tests and tools.
- Ruff checks passed using the repository's `pyproject.toml` configuration.
- Actual Gradio **4.40.0** components were constructed in a `gr.Blocks` context;
  defaults and the Manual upload control were checked.
- NumPy **1.26.2**, OpenCV **4.10.0**, Pillow **9.5.0**, Pydantic **2.8.2**.
- A separate existing environment using Gradio **5.38.2**, NumPy **1.26.4** and
  Pillow **10.4.0** also passed the initial 31-test suite. That does not establish
  support for other Forge versions.
- Gradio/FastAPI emitted upstream deprecation warnings; no test failures.

Commands used in the standalone development environment:

```sh
python tools/fetch_forge_sources.py
python -m unittest discover -s tests -v
python -m compileall -q scripts skinmatch_core.py tests tools
python -m ruff check scripts skinmatch_core.py tests tools
python tools/evaluate_synthetic.py --output docs/demo --baseline-ref e77dda6
```

The source-backed geometry test exercises 16 mode/inversion combinations with two
output images across two iterations (64 actual corrections). Manual reference
alignment adds all eight full-resolution/resize-mode combinations. Distinct input
images, directory-request reuse, RGBA alpha masks and soft masks are also tested.
The tests assert that processing actually changes editable skin, rather than
passing merely because the adapter safely skipped everything.

## Reproducible synthetic measurements

Match-priority defaults: strength **1.0**, radius **48**, feather upper limit **24**, brightness **1.0**.
Baseline `e77dda6` uses its shipped defaults: strength **0.7**, brightness **0.3**.
These shaded, textured ellipses simulate colour shifts; they are not photos of
actual arms or faces. The labels identify the intended colour-shift scenario.

| Synthetic scenario | Before | Previous default (`e77dda6`) | Match-priority default | Outside changed | Strength 0 exact |
| --- | ---: | ---: | ---: | ---: | --- |
| Arm patch | 9.64 | 4.58 | 0.39 | 0 | Yes |
| Face patch | 7.53 | 2.41 | 0.39 | 0 | Yes |
| Clothes near patch | 9.64 | 4.66 | 1.57 | 0 | Yes |
| Very pale patch | 20.55 | 13.15 | 0.36 | 0 | Yes |
| Thin patch | 7.54 | 2.09 | 0.00 | 0 | Yes |

For a fair cross-version comparison, this table uses the same untrimmed mean LAB
of the corresponding original masked patch as ground truth for every output.
The source image, generated image and mask are identical. Each version uses its
own defaults to test out-of-the-box behaviour. The JSON additionally records the
previous version at the new 1.0/1.0 controls as `previous_at_current_controls` so
the effect of changing defaults can be distinguished from the algorithm change.
The fixed-original comparison appears under `against_original_patch`.

The selected reference is external to the edit. In the clothes-adjacent fixture
its luminance differs from the original masked patch, so matching that reference
leaves a larger error relative to the original patch. Runtime mean-colour errors
against the actual selected reference are approximately **0.06..0.18** for these five fixtures,
recorded separately under `regions`. All five have `gamut_scale=1.0`.

This is mean-colour Delta E76, not a skin segmentation accuracy or matching rate.
It does not measure semantic correctness or overall visual quality.
Generated-detail measurements use the editable interior, separate from the
boundary transition. Luminance-shift variation is **0.009..0.067 L RMS**;
fine-texture correlation is **0.995..1.000** and its contrast ratio is
**1.004..1.035**. These tolerances include 8-bit RGB conversion/quantization.

## Matching changes

The skin eligibility envelope is explicit and user-adjustable: a in **-2..42**
and b in **0..50** by default, in float CIELAB coordinates. RGB, YCrCb and L
conditions additionally restrict it to plausible warm skin. Colours outside the
envelope are excluded from both statistics and output changes. Confidence weights
statistics rather than reducing correction strength a second time. Low-saturation
pale skin stays eligible while neutral white is excluded.

The core applies a **constant additive LAB translation**, with unit contrast gain
in every channel. Reference standard-deviation scaling and fixed L/chroma offset
caps have been replaced by direct mean alignment. Thus a flat reference does not
flatten generated skin texture or compress its shadow/highlight differences.

Cast estimation favours fully generated interior pixels. Final translation solves
the mean **after** boundary/soft-mask blending: `offset = desired_mean_change /
weighted_mean(alpha)`. The actual per-pixel shift is `offset * alpha * strength`.
This avoids hiding an attenuation factor in the feather or applying a soft mask
twice. Already-matching boundaries remain protected.

Reference statistics favour near-boundary skin with exponential distance decay.
The inward feather is capped at one fifth of the editable skin inradius. Boundary
weights use trustworthy original skin where available; otherwise normalized
convolution of selected external reference skin supplies nearby colour guidance.
Original non-skin pixels never contribute to this guidance.

A common gamut scale is reduced only if the requested translation would clip
skin colours. OpenCV float LAB/RGB round trips detect gamut loss, using a 0.6 Delta
E76 tolerance for conversion precision. Reducing the shared translation preserves
interior contrast instead of clipping individual highlights or shadows. In an
extreme high-contrast test the mean cannot be fully matched within RGB gamut;
that case explicitly checks `gamut_scale < 1` and retained shading contrast.

The new tests require post-composite mean Delta E76 **<0.75** across nine skin-tone/
colour-cast combinations, including offsets larger than the old L cap, and all
64 actual Forge-source geometry/batch outputs. A textured LAB fixture requires
interior luminance contrast within **1%**, luminance-shift variation **<0.2 L**,
fine-texture correlation **>0.98**, and fine-texture contrast within **5%**.
API calls omitting optional settings also exercise the match-priority defaults.

Additional regression cases cover explicit range exclusion of warm-coloured
fabric, invalid range bounds, pale skin, narrow-mask correction, high-strength
matching, pre-existing hard seams and already-matching boundaries.

The core tests also cover no-reference skips, small/empty/full masks, non-skin
preservation inside the edit, two distinct skin tones, distant-person rejection,
Manual reference exclusions, invalid coordinates, low variance, zero brightness,
alpha/metadata preservation and feathering against image edges.

## Still unverified in a live Forge installation

No live Forge/SDXL runtime was present in this workspace. The tests execute a
bounded part of the upstream source with a simulated host, not a model launch.
The following require a real installation and representative user images:

- Forge extension discovery at startup, the panel's rendered appearance, file
  upload interactions and the complete UI-to-generation-to-save path.
- SDXL inpaint image quality on real arms, partial faces, different skin tones,
  photographs, anime/stylised art and strong colour casts.
- Subjective boundary quality and identity preservation in touching/overlapping
  people, or skin-coloured clothes/hair/backgrounds.
- Directory batches through the actual WebUI, API callers and third-party batch
  modifiers, learned upscalers, ADetailer/ControlNet and nested inpaint workflows.
- Other Forge forks/releases and environments besides the versions above.

For a live smoke test, use one fixed input/mask/prompt/seed and compare enabled vs
disabled output with Only masked and Whole picture. Repeat inversion, resize modes
and two-image batches. Inspect the saved image as well as the gallery, verify
outside-mask pixels against the corresponding disabled composite, and visually
inspect boundary transitions. Do not treat the synthetic results as proof that
every skin tone or skin-like material is classified correctly.
