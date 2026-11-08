"""Package current tracked source plus converted assets, without local backups."""
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    report = json.loads((ROOT / "output/webp-compression.json").read_text(encoding="utf-8"))
    names = set(tracked) | {row["webp"].replace("\\", "/") for row in report}
    names |= {"tools/compress_runtime_assets.py", "tools/package_webp.py", "tools/review_webp.py"}
    target = ROOT / "output/astrbot_plugin_p5x_gacha_sim-v0.3.8-webp.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(names):
            path = ROOT / name
            if name and path.is_file() and not name.startswith(("output/", ".git/")):
                archive.write(path, name)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        assert "main.py" in archive.namelist()
        for row in report:
            assert row["webp"].replace("\\", "/") in archive.namelist()
            assert row["source"] not in archive.namelist()
    print(target, target.stat().st_size)


if __name__ == "__main__":
    main()
