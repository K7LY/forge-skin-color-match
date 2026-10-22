# Validation record

Date: 2026-10-22. Host: Windows, Python 3.10.9.
Source revision: Forge `dfdcbab685e57677014f05a3309b48cc87383167`.

## Executed locally

- **33 tests passed**, zero skips with the downloaded Forge sources present.
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
python tools/evaluate_synthetic.py --output docs/demo
```

The source-backed geometry test exercises 16 mode/inversion combinations with two
output images across two iterations (64 actual corrections). Manual reference
alignment adds all eight full-resolution/resize-mode combinations. Distinct input
images, directory-request reuse, RGBA alpha masks and soft masks are also tested.
The tests assert that processing actually changes editable skin, rather than
passing merely because the adapter safely skipped everything.

## Reproducible synthetic measurements

Default strength **0.7**, radius **48**, inward feather **24**, brightness **0.3**.
These shaded, textured ellipses simulate colour shifts; they are not photos of
actual arms or faces. The labels identify the intended colour-shift scenario.

| Synthetic scenario | Mean-colour Delta E76 before | After | Changed pixels outside edit mask | Strength 0 exact |
| --- | ---: | ---: | ---: | --- |
| Arm patch | 9.36 | 7.13 | 0 | Yes |
| Face patch | 7.68 | 5.66 | 0 | Yes |
| Clothes near patch | 9.20 | 6.92 | 0 | Yes |

Values measure the Euclidean distance between the reference skin's weighted mean
CIELAB and the generated skin's weighted mean CIELAB, before and after the final
RGB composite. They do not measure person identity, semantic correctness, image
quality or corresponding-pixel reconstruction. They need not approach zero because
brightness is deliberately weak and the correction fades to zero at the boundary.
Texture correlation is checked separately; it exceeds 0.98 on the tested patch.

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
