"""Convert tracked runtime PNGs without resizing; retain originals in output/."""
import json
import subprocess
from pathlib import Path
from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = subprocess.check_output(["git", "ls-files", "-z", "assets"], cwd=ROOT).decode().split("\0")
    report = []
    for relative in paths:
        path = ROOT / relative
        if path.suffix.lower() != ".png" or not path.is_file():
            continue
        target = path.with_suffix(".webp")
        if target.exists():
            raise RuntimeError(f"Target already exists: {target}")
        with Image.open(path) as source:
            image = source.convert("RGBA")
        # UI/frame textures must remain pixel-exact; character art uses high quality RGB.
        lossless = "prepared" not in path.parts and "portraits" not in path.parts
        image.save(target, "WEBP", quality=95, method=6, lossless=lossless,
                   alpha_quality=100, exact=True)
        with Image.open(target) as decoded:
            decoded = decoded.convert("RGBA")
            assert decoded.size == image.size
            assert ImageChops.difference(image.getchannel("A"), decoded.getchannel("A")).getbbox() is None
            if lossless:
                assert ImageChops.difference(image, decoded).getbbox() is None
        backup = ROOT / "output" / "original-runtime-png" / relative
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise RuntimeError(f"Backup already exists: {backup}")
        report.append({"source": relative, "webp": str(target.relative_to(ROOT)),
                       "before": path.stat().st_size, "after": target.stat().st_size,
                       "lossless": lossless, "size": image.size, "alpha_exact": True})
        path.rename(backup)
        print(relative, flush=True)
    output = ROOT / "output" / "webp-compression.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("files", len(report), "before", sum(r["before"] for r in report),
          "after", sum(r["after"] for r in report))


if __name__ == "__main__":
    main()
