"""Exercise native release assets, including Lori's bundled web dashboard."""

import argparse
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from create_project import extract_template
from release_common import installer_name, template_name


def smoke(directory: Path, *, version: str, target: str, repository: str) -> None:
    installer = directory / installer_name(target)
    installer.chmod(0o755)  # Artifact transport may not preserve executable bits.
    help_result = subprocess.run([str(installer), "--help"], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert help_result.returncode == 0, help_result.stderr
    assert version in help_result.stdout, help_result.stdout
    with tempfile.TemporaryDirectory(prefix="lorenphp smoke ") as temporary:
        root = Path(temporary) / "project with spaces"
        root.mkdir()
        extract_template(directory / template_name(version, target), root, version=version, target=target, repository=repository)
        empty_path = Path(temporary) / "empty-path"
        empty_path.mkdir()
        environment = {**os.environ, "PATH": str(empty_path), "NO_COLOR": "1"}
        # No Python, Git or Docker is available through PATH in this process.
        executable = root / ".lori-bin" / ("lori.exe" if target.startswith("windows-") else "lori")
        if os.name == "nt":
            command = [os.environ.get("COMSPEC", r"C:\Windows\System32\cmd.exe"), "/d", "/c", "call", str(root / "lori.cmd")]
        else:
            command = [str(executable)]
        process = subprocess.Popen(command, cwd=temporary, env=environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
        lines = queue.Queue()
        transcript = []

        def read_output():
            for line in process.stdout:
                transcript.append(line)
                lines.put(line)

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        try:
            deadline = time.monotonic() + 30
            origin = None
            while time.monotonic() < deadline and origin is None:
                try:
                    line = lines.get(timeout=.5)
                except queue.Empty:
                    if process.poll() is not None:
                        break
                    continue
                match = re.search(r"http://127\.0\.0\.1:\d+", line)
                if match:
                    origin = match[0]
            assert origin, "Dashboard URL missing: " + "".join(transcript)
            for path in ("/", "/panel.css", "/panel.js", "/favicon.png"):
                with urlopen(origin + path, timeout=5) as response:
                    assert response.status == 200 and response.read(), path
            process.stdin.write("setup-project\nquit\n")
            process.stdin.flush()
            process.wait(timeout=30)
            reader.join(timeout=5)
            assert process.returncode == 0, "".join(transcript)
            config = json.loads((root / ".lori" / "config.json").read_text(encoding="utf-8"))
            assert config["version"] == 1 and config["credentials"]["MYSQL_PASSWORD"]
            assert not (Path(temporary) / ".lori").exists(), "Lori used the working directory instead of the project directory"
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
            process.stdin.close()
            process.stdout.close()
    print(f"Native installer, Lori, project setup and bundled dashboard verified for {target}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--repository", default="LoRy24/LorenPHP-Template")
    arguments = parser.parse_args()
    smoke(arguments.directory.resolve(), version=arguments.version, target=arguments.target, repository=arguments.repository)
