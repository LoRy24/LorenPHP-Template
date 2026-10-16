"""Build on the target OS/architecture: python tools/release/build.py --help."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from release_common import ARCHIVE_ROOT, MANIFEST, TARGETS, current_target, installer_name, template_name, validate_repository, validate_version


TEMPLATE_FILES = (
    ".dockerignore", ".gitattributes", ".gitignore", ".prettierignore", ".prettierrc.json",
    "Caddyfile", "LICENSE", "README.md", "composer.json", "composer.lock", "package.json", "package-lock.json",
    "lori", "lori.cmd", "tools/lori_entry.py", "tools/lori_cli.py", "tools/lori_web.py",
)
TEMPLATE_DIRECTORIES = ("src", "public", "docker", "tools/panel")


def package_template(root: Path, binary: Path, output: Path, metadata: dict) -> Path:
    """An allowlist prevents local credentials, dependencies and CI files from shipping."""
    paths = [root / name for name in TEMPLATE_FILES]
    tracked = subprocess.check_output(["git", "ls-files", "-z", "--", *TEMPLATE_DIRECTORIES], cwd=root)
    paths.extend(root / name.decode("utf-8") for name in tracked.split(b"\0") if name)
    archive = output / template_name(metadata["version"], metadata["target"])
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(paths):
            if path.is_symlink():
                raise ValueError(f"Il template non può contenere link simbolici: {path}")
            relative = path.relative_to(root).as_posix()
            mode = 0o755 if relative == "lori" else 0o644
            info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/{relative}")
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, path.read_bytes())
        info = zipfile.ZipInfo(f"{ARCHIVE_ROOT}/.lori-bin/{binary.name}")
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | 0o755) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        bundle.writestr(info, binary.read_bytes())
        bundle.writestr(f"{ARCHIVE_ROOT}/{MANIFEST}", json.dumps(metadata, indent=2) + "\n")
    return archive


def build(output: Path, metadata: dict) -> None:
    import certifi

    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lorenphp-build-") as temporary:
        work = Path(temporary)
        settings = work / "installer-release.json"
        settings.write_text(json.dumps(metadata), encoding="utf-8")
        common = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console", "--noupx",
                  "--python-option", "X utf8",
                  "--distpath", str(work / "bin"), "--workpath", str(work / "work"), "--specpath", str(work),
                  "--paths", str(ROOT / "tools")]
        subprocess.run(common + ["--name", "lori", "--add-data", f"{ROOT / 'tools' / 'panel'}:panel", str(ROOT / "tools" / "lori_entry.py")], check=True, cwd=ROOT)
        suffix = ".exe" if metadata["target"].startswith("windows-") else ""
        package_template(ROOT, work / "bin" / f"lori{suffix}", output, metadata)
        name = installer_name(metadata["target"])
        subprocess.run(common + ["--name", name.removesuffix(".exe"),
                                "--add-data", f"{settings}:.", "--add-data", f"{certifi.where()}:.",
                                str(ROOT / "tools" / "create_project.py")], check=True, cwd=ROOT)
        shutil.copy2(work / "bin" / name, output / name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, type=validate_version)
    parser.add_argument("--repository", default="LoRy24/LorenPHP-Template", type=validate_repository)
    parser.add_argument("--target", required=True, choices=TARGETS)
    parser.add_argument("--output", type=Path, default=ROOT / "dist" / "release")
    args = parser.parse_args()
    if args.target != current_target():
        parser.error(f"La build nativa richiede {args.target}; questo host è {current_target()}.")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    build(args.output.resolve(), {"version": args.version, "repository": args.repository, "target": args.target, "commit": commit})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
