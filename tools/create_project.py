"""Download a verified release template without Git or a local Python install."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shlex
import shutil
import ssl
import stat
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen
import zipfile

from release_common import ARCHIVE_ROOT, MANIFEST, current_target, template_name, validate_repository, validate_version


MAX_DOWNLOAD = 512 * 1024 * 1024
MAX_EXTRACTED = 1024 * 1024 * 1024


def installer_defaults() -> dict:
    metadata = Path(__file__).with_name("installer-release.json")
    if getattr(sys, "frozen", False):
        return json.loads(metadata.read_text(encoding="utf-8"))
    return {"repository": "LoRy24/LorenPHP-Template", "version": "latest", "target": current_target()}


def download(url: str, destination: Path, *, limit: int = MAX_DOWNLOAD) -> None:
    if urlsplit(url).scheme != "https":
        raise ValueError("Il download richiede HTTPS.")
    certificates = Path(__file__).with_name("cacert.pem")
    context = ssl.create_default_context(cafile=str(certificates) if certificates.exists() else None)
    request = Request(url, headers={"User-Agent": "LorenPHP-Create", "Accept": "application/vnd.github+json"})
    with urlopen(request, context=context, timeout=60) as response, destination.open("wb") as output:
        if urlsplit(response.url).scheme != "https":
            raise ValueError("Reindirizzamento non sicuro durante il download.")
        total = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("La risorsa supera la dimensione massima consentita.")
            output.write(chunk)


def checksum_for(checksums: Path, name: str) -> str:
    matches = []
    for line in checksums.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-fA-F]{64})  (.+)", line)
        if match and match[2] == name:
            matches.append(match[1].lower())
    if len(matches) != 1:
        raise ValueError(f"Checksum mancante o ambiguo per {name}.")
    return matches[0]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_template(archive: Path, destination: Path, *, version: str, target: str, repository: str) -> None:
    """Extract only regular files inside the expected root, restoring executable bits."""
    with zipfile.ZipFile(archive) as source:
        entries = source.infolist()
        if len(entries) > 10000 or sum(entry.file_size for entry in entries) > MAX_EXTRACTED:
            raise ValueError("Archivio troppo grande.")
        seen = set()
        for entry in entries:
            path = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            if ("\\" in entry.filename or path.is_absolute() or ".." in path.parts
                    or not path.parts or path.parts[0] != ARCHIVE_ROOT
                    or any(":" in part or part.endswith((".", " ")) for part in path.parts)
                    or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR))):
                raise ValueError(f"Percorso non sicuro nell'archivio: {entry.filename}")
            key = path.as_posix().rstrip("/").casefold()
            if key in seen:
                raise ValueError(f"Percorso duplicato nell'archivio: {entry.filename}")
            seen.add(key)
        try:
            manifest = json.loads(source.read(f"{ARCHIVE_ROOT}/{MANIFEST}"))
        except (KeyError, ValueError) as error:
            raise ValueError("Metadati del template mancanti o non validi.") from error
        if not isinstance(manifest, dict):
            raise ValueError("Metadati del template non validi.")
        if any(manifest.get(key) != value for key, value in {"version": version, "target": target, "repository": repository}.items()):
            raise ValueError("Il template non corrisponde alla release o alla piattaforma richiesta.")
        executable = ".lori-bin/lori.exe" if target.startswith("windows-") else ".lori-bin/lori"
        for required in (executable, "lori", "lori.cmd", "composer.json", "docker/compose.yaml", "tools/lori_entry.py"):
            if f"{ARCHIVE_ROOT}/{required}" not in source.namelist():
                raise ValueError(f"Template incompleto: manca {required}.")
        for entry in entries:
            relative = PurePosixPath(entry.filename).relative_to(ARCHIVE_ROOT)
            output = destination.joinpath(*relative.parts)
            if entry.is_dir():
                output.mkdir(parents=True, exist_ok=True)
                continue
            output.parent.mkdir(parents=True, exist_ok=True)
            with source.open(entry) as input_file, output.open("xb") as output_file:
                shutil.copyfileobj(input_file, output_file)
            output.chmod(0o755 if entry.external_attr >> 16 & 0o111 else 0o644)
        if not target.startswith("windows-"):
            (destination / "lori").chmod(0o755)
            (destination / executable).chmod(0o755)


def create_project(destination: Path, *, version: str, target: str, repository: str) -> str:
    validate_repository(repository)
    validate_version(version)
    # Refuse all existing paths, including dangling symlinks, before making requests.
    if os.path.lexists(destination):
        raise ValueError(f"La destinazione esiste già: {destination}. Scegli una nuova cartella.")
    if not destination.parent.is_dir():
        raise ValueError(f"La cartella padre non esiste: {destination.parent}")
    with tempfile.TemporaryDirectory(prefix=".lorenphp-", dir=destination.parent) as temporary:
        staging = Path(temporary)
        if version == "latest":
            release = staging / "release.json"
            download(f"https://api.github.com/repos/{repository}/releases/latest", release, limit=1024 * 1024)
            version = validate_version(json.loads(release.read_text(encoding="utf-8"))["tag_name"])
        name = template_name(version, target)
        base = f"https://github.com/{repository}/releases/download/{quote(version, safe='')}"
        checksums, archive = staging / "SHA256SUMS", staging / name
        print(f"Scarico LorenPHP {version} per {target}…", flush=True)
        download(f"{base}/SHA256SUMS", checksums, limit=1024 * 1024)
        expected = checksum_for(checksums, name)
        download(f"{base}/{name}", archive)
        if sha256(archive) != expected:
            raise ValueError("Checksum SHA-256 non corrispondente: download annullato.")
        project = staging / "project"
        project.mkdir()
        extract_template(archive, project, version=version, target=target, repository=repository)
        # Reserve the final directory so a concurrent process can never be overwritten.
        destination.mkdir()
        try:
            for item in project.iterdir():
                item.rename(destination / item.name)
        except BaseException:
            shutil.rmtree(destination)
            raise
    return version


def main(argv: list[str] | None = None) -> int:
    defaults = installer_defaults()
    parser = argparse.ArgumentParser(description="Crea un progetto LorenPHP scaricando il template della release e Lori.")
    parser.add_argument("destination", type=Path, help="nuova cartella del progetto")
    parser.add_argument("--version", default=defaults["version"], metavar="TAG", help="tag da scaricare, oppure latest (predefinito: %(default)s)")
    args = parser.parse_args(argv)
    destination = Path(os.path.abspath(args.destination.expanduser()))
    try:
        version = create_project(destination, version=args.version, target=defaults["target"], repository=defaults["repository"])
    except HTTPError as error:
        print(f"Download fallito (HTTP {error.code}). Verifica che la release contenga gli asset per {defaults['target']}.", file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError, URLError, zipfile.BadZipFile) as error:
        print(f"Impossibile creare il progetto: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nDownload interrotto.", file=sys.stderr)
        return 130
    print(f"Progetto LorenPHP {version} creato in {destination}.")
    if os.name == "nt":
        print(f'cd "{destination}"\n.\\lori.cmd')
    else:
        print(f"cd {shlex.quote(str(destination))}\n./lori")
    print("Dentro Lori: setup-project, poi dev. Docker con Compose v2 deve essere disponibile; le immagini vengono scaricate al primo uso.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
