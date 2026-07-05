import os
import subprocess


def test_readme_exists():
    assert os.path.isfile("README.md")


def test_gitignore_exists():
    assert os.path.isfile(".gitignore")


def test_baseline_png_not_tracked():
    result = subprocess.run(
        ["git", "ls-files", "data/sample_baseline.png"],
        capture_output=True, text=True
    )
    assert result.stdout.strip() == "", f"Binary still tracked: {result.stdout.strip()}"
