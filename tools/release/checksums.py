"""Validate the complete release asset set and write SHA256SUMS."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from create_project import sha256
from release_common import TARGETS, installer_name, template_name, validate_version


def write_checksums(directory: Path, version: str) -> Path:
    expected = {name for target in TARGETS for name in (template_name(version, target), installer_name(target))}
    actual = {path.name for path in directory.iterdir() if path.name != "SHA256SUMS"}
    if actual != expected:
        raise ValueError(f"Asset release non validi. Mancanti: {sorted(expected - actual)}; inattesi: {sorted(actual - expected)}")
    checksums = directory / "SHA256SUMS"
    checksums.write_text("".join(f"{sha256(directory / name)}  {name}\n" for name in sorted(expected)), encoding="utf-8")
    return checksums


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True, type=validate_version)
    arguments = parser.parse_args()
    write_checksums(arguments.directory, arguments.version)
