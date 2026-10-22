"""Fetch only the pinned upstream files needed for optional source-contract tests.

Nothing is installed into Forge; downloads stay in the ignored .research folder.
Run from the repository root: python tools/fetch_forge_sources.py
"""

from pathlib import Path
from urllib.request import urlopen

FORGE_COMMIT = "dfdcbab685e57677014f05a3309b48cc87383167"


if __name__ == "__main__":
    destination = Path(__file__).resolve().parents[1] / ".research" / "forge"
    destination.mkdir(parents=True, exist_ok=True)
    for name in ("processing", "scripts", "images", "masking"):
        url = f"https://raw.githubusercontent.com/lllyasviel/stable-diffusion-webui-forge/{FORGE_COMMIT}/modules/{name}.py"
        (destination / f"{name}.py").write_bytes(urlopen(url, timeout=30).read())
        print(f"Fetched {name}.py @ {FORGE_COMMIT}")
