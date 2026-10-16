"""Asset naming shared by the release builder and the project installer."""

from __future__ import annotations

import platform
import re


TARGETS = ("linux-x64", "linux-arm64", "macos-x64", "macos-arm64", "windows-x64")
ARCHIVE_ROOT = "LorenPHP-Template"
MANIFEST = ".lorenphp-template.json"


def validate_version(version: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}", version):
        raise ValueError("Tag non valido: usa lettere, numeri, punti, trattini, + o underscore (es. v1.0.0).")
    return version


def validate_repository(repository: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repository non valido: atteso proprietario/nome.")
    return repository


def current_target() -> str:
    system = {"Linux": "linux", "Darwin": "macos", "Windows": "windows"}.get(platform.system())
    architecture = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(platform.machine().lower())
    target = f"{system}-{architecture}"
    if target not in TARGETS:
        raise ValueError(f"Piattaforma non supportata: {platform.system()} {platform.machine()}.")
    return target


def template_name(version: str, target: str) -> str:
    return f"lorenphp-template-{validate_version(version)}-{target}.zip"


def installer_name(target: str) -> str:
    return f"lorenphp-create-{target}" + (".exe" if target.startswith("windows-") else "")
