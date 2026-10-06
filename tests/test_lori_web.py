"""Transport and lifecycle checks without Docker: python3 -m unittest discover -s tests."""

import json
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import lori_cli
from lori_web import Dashboard


class FakeConsole:
    def __init__(self):
        self.config = lori_cli.default_config()
        self.operation_lock = threading.RLock()
        self.docker_ok = True
        self.docker_message = "Docker test"
        self.gate = threading.Event()
        self.gate.set()
        self.succeed = True
        self.started = []

    def compose(self, args, **kwargs):
        output = "[]" if args[0] == "ps" else self.config["credentials"]["MYSQL_PASSWORD"]
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    def ready(self):
        return True

    def start_resources(self, items):
        self.gate.wait(3)
        self.started.extend(items)
        lori_cli.say(self.config["credentials"]["MYSQL_PASSWORD"])
        return self.succeed


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.docker = patch.object(lori_cli, "docker_available", return_value=(True, "Docker test"))
        self.docker.start()
        self.console = FakeConsole()
        self.dashboard = Dashboard(self.console, port=0)
        self.dashboard.start()

    def tearDown(self):
        self.console.gate.set()
        self.dashboard.close()
        self.docker.stop()

    def request(self, path, data=None, authenticated=True, headers=None):
        request_headers = {"X-Lori-Token": self.dashboard.token} if authenticated else {}
        if data is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = Request(self.dashboard.origin + path, data=json.dumps(data).encode() if data is not None else None, headers=request_headers)
        try:
            response = urlopen(request, timeout=3)
        except HTTPError as error:
            response = error
        body = response.read()
        return response.status, body, response.headers

    def wait_job(self):
        for _ in range(100):
            state = self.dashboard.state()
            if state["job"] and state["job"]["status"] != "running":
                return state["job"]
            time.sleep(.02)
        self.fail("Job did not complete")

    def test_session_origin_and_host_are_required(self):
        self.assertEqual(self.request("/api/state", authenticated=False)[0], 401)
        self.assertEqual(self.request("/api/state", headers={"Origin": "https://example.org"})[0], 403)
        self.assertEqual(self.request("/api/state", headers={"Host": "example.org"})[0], 403)
        status, body, headers = self.request("/api/state")
        self.assertEqual(status, 200)
        self.assertNotIn(self.dashboard.token.encode(), body)
        self.assertNotIn(self.console.config["credentials"]["MYSQL_PASSWORD"].encode(), body)
        self.assertEqual(headers["Cache-Control"], "no-store")

    def test_only_explicit_assets_are_served(self):
        self.assertEqual(self.request("/", authenticated=False)[0], 200)
        self.assertEqual(self.request("/../.lori/config.json")[0], 404)
        self.assertEqual(self.request("/.lori/config.json")[0], 404)

    def test_invalid_actions_and_arguments_are_rejected(self):
        for data in ({"action": "shell", "command": "echo test"}, {"action": "start", "service": ["redis"]}, {"action": "configure", "service": "redis", "port": True}, {"action": "startup", "services": ["dev", "run"]}):
            self.assertEqual(self.request("/api/actions", data)[0], 400)
        self.assertEqual(self.request("/api/actions", {"action": "start", "service": "redis"}, authenticated=False)[0], 401)

    def test_jobs_are_serial_and_interface_dependencies_start(self):
        self.console.gate.clear()
        self.assertEqual(self.request("/api/actions", {"action": "start", "service": "phpmyadmin"})[0], 202)
        self.assertEqual(self.request("/api/actions", {"action": "start", "service": "redis"})[0], 409)
        self.assertEqual(self.request("/api/state")[0], 200)
        self.console.gate.set()
        job = self.wait_job()
        self.assertEqual(job["status"], "success")
        self.assertEqual(self.console.started, ["mysql", "phpmyadmin"])
        self.assertNotIn(self.console.config["credentials"]["MYSQL_PASSWORD"], "\n".join(job["messages"]))

    def test_errors_are_not_reported_as_success(self):
        self.console.succeed = False
        self.request("/api/actions", {"action": "start", "service": "redis"})
        self.assertEqual(self.wait_job()["status"], "error")

    def test_credentials_are_explicit_and_logs_are_redacted(self):
        status, body, _ = self.request("/api/credentials?service=mysql")
        self.assertEqual(status, 200)
        self.assertIn(self.console.config["credentials"]["MYSQL_PASSWORD"], body.decode())
        status, body, _ = self.request("/api/logs?service=mysql")
        self.assertEqual(status, 200)
        self.assertNotIn(self.console.config["credentials"]["MYSQL_PASSWORD"], body.decode())


if __name__ == "__main__":
    unittest.main()
