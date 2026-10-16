"""Release packaging and installer checks without network access or Docker."""

from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import stat
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import create_project as installer
from release.build import package_template
from release.checksums import write_checksums
from release_common import ARCHIVE_ROOT, MANIFEST, TARGETS, current_target, installer_name, template_name, validate_version


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "assets"
        self.output.mkdir()
        self.metadata = {"version": "v1.2.3", "target": "linux-x64", "repository": "LoRy24/LorenPHP-Template", "commit": "abc123"}

    def archive(self, **overrides):
        metadata = {**self.metadata, **overrides}
        binary = self.root / ("lori.exe" if metadata["target"].startswith("windows-") else "lori")
        binary.write_bytes(b"native executable fixture")
        return package_template(ROOT, binary, self.output, metadata)

    def download_fixture(self, archive, *, corrupt=False, latest=False):
        def download(url, destination, **kwargs):
            if url.endswith("/releases/latest") and latest:
                destination.write_text(json.dumps({"tag_name": self.metadata["version"]}), encoding="utf-8")
            elif url.endswith("/SHA256SUMS"):
                checksum = "0" * 64 if corrupt else installer.sha256(archive)
                destination.write_text(f"{checksum}  {archive.name}\n", encoding="utf-8")
            elif url.endswith("/" + archive.name):
                shutil.copyfile(archive, destination)
            else:
                self.fail(f"Unexpected URL: {url}")
        return patch.object(installer, "download", side_effect=download)

    def create(self, destination, **overrides):
        with redirect_stdout(io.StringIO()):
            return installer.create_project(destination, **{key: value for key, value in {**self.metadata, **overrides}.items() if key != "commit"})

    def test_platform_detection_and_unsupported_architectures(self):
        cases = (("Linux", "x86_64", "linux-x64"), ("Linux", "aarch64", "linux-arm64"),
                 ("Darwin", "arm64", "macos-arm64"), ("Darwin", "x86_64", "macos-x64"),
                 ("Windows", "AMD64", "windows-x64"))
        for system, architecture, expected in cases:
            with self.subTest(expected=expected), patch("platform.system", return_value=system), patch("platform.machine", return_value=architecture):
                self.assertEqual(current_target(), expected)
        with patch("platform.machine", return_value="riscv64"), self.assertRaisesRegex(ValueError, "non supportata"):
            current_target()

    def test_unsafe_tags_are_rejected(self):
        for value in ("../main", "v1/2", "tag\nname", "$(command)", "", "-v1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_version(value)
        self.assertEqual(validate_version("v1.2.3-rc.1+build"), "v1.2.3-rc.1+build")

    def test_all_platform_templates_install_and_preserve_permissions(self):
        for target in TARGETS:
            with self.subTest(target=target):
                archive = self.archive(target=target)
                destination = self.root / target
                with self.download_fixture(archive):
                    self.assertEqual(self.create(destination, target=target), self.metadata["version"])
                metadata = json.loads((destination / MANIFEST).read_text(encoding="utf-8"))
                self.assertEqual(metadata["target"], target)
                self.assertTrue((destination / "tools" / "panel" / "panel.js").is_file())
                self.assertTrue((destination / "composer.lock").is_file())
                binary = destination / ".lori-bin" / ("lori.exe" if target.startswith("windows-") else "lori")
                self.assertEqual(binary.read_bytes(), b"native executable fixture")
                if os.name != "nt":
                    self.assertTrue(binary.stat().st_mode & stat.S_IXUSR)
                    self.assertTrue((destination / "lori").stat().st_mode & stat.S_IXUSR)
                for excluded in (".git", ".github", ".lori", ".docker-data", ".env", "node_modules", "vendor", "FastTickets.png", "tests"):
                    self.assertFalse((destination / excluded).exists(), excluded)
        self.assertFalse(list(self.root.glob(".lorenphp-*")))

    def test_latest_resolves_once_then_downloads_assets_of_that_tag(self):
        archive = self.archive()
        with self.download_fixture(archive, latest=True) as download:
            self.assertEqual(self.create(self.root / "latest", version="latest"), self.metadata["version"])
        self.assertEqual(download.call_count, 3)
        self.assertIn("/releases/download/v1.2.3/", download.call_args_list[1].args[0])
        self.assertIn("/releases/download/v1.2.3/", download.call_args_list[2].args[0])

    def test_corrupt_download_leaves_no_project_or_temporary_files(self):
        archive = self.archive()
        destination = self.root / "project"
        with self.download_fixture(archive, corrupt=True), self.assertRaisesRegex(ValueError, "SHA-256"):
            self.create(destination)
        self.assertFalse(destination.exists())
        self.assertFalse(list(self.root.glob(".lorenphp-*")))

    def test_existing_directory_file_and_symlink_are_never_overwritten(self):
        directory = self.root / "existing"
        directory.mkdir()
        sentinel = directory / "keep.txt"
        sentinel.write_text("keep", encoding="utf-8")
        paths = [directory, sentinel]
        if os.name != "nt":
            link = self.root / "dangling"
            link.symlink_to(self.root / "missing")
            paths.append(link)
        for destination in paths:
            with self.subTest(destination=destination), patch.object(installer, "download") as download, self.assertRaisesRegex(ValueError, "esiste già"):
                self.create(destination)
            download.assert_not_called()
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_failed_and_interrupted_downloads_are_cleaned_up(self):
        for error in (OSError("offline"), KeyboardInterrupt()):
            with self.subTest(error=type(error)), patch.object(installer, "download", side_effect=error), self.assertRaises(type(error)):
                self.create(self.root / "project")
            self.assertFalse((self.root / "project").exists())
            self.assertFalse(list(self.root.glob(".lorenphp-*")))

    def test_manifest_must_match_platform_version_and_repository(self):
        archive = self.archive()
        for override in ({"target": "macos-arm64"}, {"version": "v9.0.0"}, {"repository": "other/repository"}):
            with self.subTest(override=override), self.assertRaisesRegex(ValueError, "non corrisponde"):
                installer.extract_template(archive, self.root / "extract", **{key: value for key, value in {**self.metadata, **override}.items() if key != "commit"})

    def test_zip_traversal_and_symlinks_are_rejected_before_extraction(self):
        for name, mode in (("../outside", 0), (f"{ARCHIVE_ROOT}/../../outside", 0),
                           ("/absolute", 0), (f"{ARCHIVE_ROOT}/folder\\outside", 0),
                           (f"{ARCHIVE_ROOT}/C:/outside", 0), (f"{ARCHIVE_ROOT}/link", stat.S_IFLNK | 0o777)):
            with self.subTest(name=name):
                archive = self.root / "unsafe.zip"
                with zipfile.ZipFile(archive, "w") as source:
                    info = zipfile.ZipInfo(name)
                    # Preserve malformed archive names even on Windows, where the
                    # constructor normally converts backslashes to forward slashes.
                    info.filename = name
                    info.external_attr = mode << 16
                    source.writestr(info, "outside")
                with self.assertRaisesRegex(ValueError, "non sicuro"):
                    installer.extract_template(archive, self.root / "extract", **{key: value for key, value in self.metadata.items() if key != "commit"})
                self.assertFalse((self.root / "extract").exists())

    def test_missing_and_duplicate_checksums_are_rejected(self):
        sums = self.root / "SHA256SUMS"
        for content in ("", f"{'a' * 64}  template.zip\n{'b' * 64}  template.zip\n"):
            sums.write_text(content, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "mancante o ambiguo"):
                installer.checksum_for(sums, "template.zip")

    def test_checksums_require_every_template_and_installer(self):
        with self.assertRaisesRegex(ValueError, "Mancanti"):
            write_checksums(self.output, "v1.2.3")
        for target in TARGETS:
            for name in (template_name("v1.2.3", target), installer_name(target)):
                (self.output / name).write_bytes(name.encode())
        sums = write_checksums(self.output, "v1.2.3")
        self.assertEqual(len(sums.read_text(encoding="utf-8").splitlines()), 10)
        for target in TARGETS:
            name = template_name("v1.2.3", target)
            self.assertEqual(installer.checksum_for(sums, name), installer.sha256(self.output / name))
        (self.output / "unexpected.zip").touch()
        with self.assertRaisesRegex(ValueError, "inattesi"):
            write_checksums(self.output, "v1.2.3")

    def test_frozen_lori_uses_project_directory_instead_of_bundle_or_cwd(self):
        executable = self.root / "new project" / ".lori-bin" / "lori"
        with patch.object(sys, "frozen", True, create=True), patch.object(sys, "executable", str(executable)):
            module = runpy.run_path(str(ROOT / "tools" / "lori_cli.py"))
        self.assertEqual(module["ROOT"], executable.resolve().parent.parent)

    def test_plain_http_download_is_rejected(self):
        with patch.object(installer, "urlopen") as request, self.assertRaisesRegex(ValueError, "HTTPS"):
            installer.download("http://example.com/template.zip", self.root / "download")
        request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
