# Provenance and reference review

Copyright (c) 2026 K7LY. This extension is distributed under **AGPL-3.0-only**;
the full license is in [LICENSE](LICENSE). Algorithm and adapter code were
written for this project. No ComfyUI node source was copied or translated.
The general per-channel mean/standard-deviation transfer equation is implemented
independently with NumPy and OpenCV.

Repositories inspected on 2026-10-22:

| Project | Reviewed revision | License found | Use in this project |
| --- | --- | --- | --- |
| [Stable Diffusion WebUI Forge](https://github.com/lllyasviel/stable-diffusion-webui-forge/tree/dfdcbab685e57677014f05a3309b48cc87383167) | `dfdcbab685e57677014f05a3309b48cc87383167` | AGPL-3.0, `LICENSE.txt` | API, mask coordinates, resize, overlay order; optional tests download and execute selected upstream functions locally. |
| [ComfyUI-AusBoss](https://github.com/ausboss/ComfyUI-AusBoss/tree/e808f4ff51adab183d86552506b16557cdc809f2) | `e808f4ff51adab183d86552506b16557cdc809f2` | MIT, Copyright (c) 2026 ausboss | Studied LAB/RGB mean/std and weighted-mask colour matching; no code incorporated. |
| [ComfyuiSmartColorMatch](https://github.com/kayorlian/ComfyuiSmartColorMatch/tree/413a8cfaaaf7202e83d9cc3a209107b27edbd7f1) | `413a8cfaaaf7202e83d9cc3a209107b27edbd7f1` | No explicit license located at this revision; GitHub reports no license | Inspected masked colour statistics; **no source reuse**. Public availability is not treated as permission to redistribute its code. |
| [ComfyUI-Y7Nodes](https://github.com/yushan777/ComfyUI-Y7Nodes/tree/21241c2ad6bdd2abcb1489acf8ee4272cfc99d14) | `21241c2ad6bdd2abcb1489acf8ee4272cfc99d14` | MIT, Copyright (c) 2025 yushan777 | Studied mask semantics. This extension corrects only editable skin inside the inpaint mask, not the inverse area. No code incorporated. |

The download helper stores Forge source only in ignored `.research/forge/`.
Upstream license and copyright notices remain in those downloaded files where
present; source files are not bundled with this extension. Forge and dependency
licenses continue to apply to their respective projects.
