"""Run with python tests/test_install.py; uses uv and the package cache/network."""
import shutil
import subprocess
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix="jev-install-check-") as temporary:
    fixture = Path(temporary)
    shutil.copy2(repo / "install.sh", fixture / "install.sh")
    shutil.copytree(repo / "skills", fixture / "skills",
                    ignore=shutil.ignore_patterns(".venv", "__pycache__"))
    destination = fixture / "installed-skills"
    for _ in range(2):
        subprocess.run(["bash", str(fixture / "install.sh"), str(destination)],
                       check=True, capture_output=True, text=True)
    assert (destination / "jev-decision-support").resolve() == fixture / "skills/jev-decision-support"
    assert len(list(destination.iterdir())) == 1
    occupied = fixture / "occupied"
    (occupied / "jev-decision-support").mkdir(parents=True)
    sentinel = occupied / "jev-decision-support/keep.txt"
    sentinel.write_text("preserve")
    result = subprocess.run(["bash", str(fixture / "install.sh"), str(occupied)],
                            capture_output=True, text=True)
    assert result.returncode != 0 and sentinel.read_text() == "preserve"
print("Installer checks passed: repeated install and preservation of unrelated content.")
