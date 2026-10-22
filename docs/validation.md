# Validation record

Date: 2026-10-22. Host: Windows, Python 3.10.9.
Source revision: Forge `dfdcbab685e57677014f05a3309b48cc87383167`.

## Executed locally

- **42 tests passed**, zero skips with the downloaded Forge sources present.
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
python tools/evaluate_synthetic.py --output docs/demo --baseline-ref e83bb2d
```

The source-backed geometry test exercises 16 mode/inversion combinations with two
output images across two iterations (64 actual corrections). Manual reference
alignment adds all eight full-resolution/resize-mode combinations. Distinct input
images, directory-request reuse, RGBA alpha masks and soft masks are also tested.
The tests assert that processing actually changes editable skin, rather than
passing merely because the adapter safely skipped everything.

## Reproducible synthetic measurements

Default strength **0.7**, radius **48**, feather upper limit **24**, brightness **0.3**.
These shaded, textured ellipses simulate colour shifts; they are not photos of
actual arms or faces. The labels identify the intended colour-shift scenario.

| Synthetic scenario | Before | Previous core (`e83bb2d`) | Current core | Outside changed | Strength 0 exact |
| --- | ---: | ---: | ---: | ---: | --- |
| Arm patch | 9.64 | 7.50 | 4.58 | 0 | Yes |
| Face patch | 7.53 | 5.51 | 2.41 | 0 | Yes |
| Clothes near patch | 9.64 | 7.51 | 4.66 | 0 | Yes |
| Very pale patch | 20.55 | 18.79 | 13.15 | 0 | Yes |
| Thin patch | 7.54 | 7.31 | 2.09 | 0 | Yes |

For a fair cross-version comparison, this table uses the same untrimmed mean LAB
of the corresponding original masked patch as ground truth for every output.
The source image, generated image, mask and strength/brightness/radius/feather
settings are identical. Previously reported diagnostic numbers used each
algorithm's selected reference statistics, which differ as reference selection
changes. Those runtime diagnostics remain in the JSON `regions` entries; the
fixed-reference comparison appears under `against_original_patch`.

This is mean-colour Delta E76, not a skin segmentation accuracy or matching rate.
It does not measure semantic correctness or overall visual quality. Brightness
remains intentionally weak at its default value, so pale patches retain some
luminance mismatch; stronger brightness settings can reduce that component.
Texture correlation is checked separately; it exceeds 0.98 on the tested patch.

## Matching changes

The skin eligibility envelope is explicit and user-adjustable: a in **-2..42**
and b in **0..50** by default, in float CIELAB coordinates. RGB, YCrCb and L
conditions additionally restrict it to plausible warm skin. Colours outside the
envelope are excluded from both statistics and output changes. Confidence weights
statistics rather than reducing correction strength a second time. Low-saturation
pale skin stays eligible while neutral white is excluded.

Reference statistics now favour near-boundary skin with exponential distance
decay. The inward feather width is capped at one fifth of each editable skin
component's inradius so narrow patches retain a full-strength interior.
When the original skin beneath a boundary is compatible with the external
reference, its colour difference guides the blend: a hard pre-existing seam gets
correction at the edge, while already-matching composite pixels retain their colour.
Original non-skin pixels do not guide this boundary adjustment.

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
