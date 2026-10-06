"""Local web dashboard. Uses the same Console and lock as the interactive shell."""

from __future__ import annotations

from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit

import lori_cli as cli

ASSETS = Path(__file__).resolve().parent / "panel"
CATALOG = {
    "app": ("Applicazione PHP", "FrankenPHP · PHP 8.4", "application"),
    "mysql": ("MySQL", "Database relazionale", "database"),
    "postgres": ("PostgreSQL", "Database relazionale", "database"),
    "mongodb": ("MongoDB", "Database documentale", "database"),
    "redis": ("Redis", "Cache e memoria condivisa", "database"),
    "phpmyadmin": ("phpMyAdmin", "Gestisci MySQL", "interface"),
    "adminer": ("Adminer", "Gestisci PostgreSQL", "interface"),
    "mongo-express": ("Mongo Express", "Esplora MongoDB", "interface"),
    "redisinsight": ("Redis Insight", "Esplora Redis", "interface"),
}
CREDENTIAL_KEYS = {
    "mysql": ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE", "MYSQL_ROOT_PASSWORD"),
    "postgres": ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"),
    "mongodb": ("MONGO_USER", "MONGO_PASSWORD"),
    "phpmyadmin": ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"),
    "adminer": ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"),
    "mongo-express": ("MONGO_EXPRESS_USER", "MONGO_EXPRESS_PASSWORD"),
}


class Dashboard:
    def __init__(self, console, port: int = 8790):
        self.console = console
        self.token = secrets.token_urlsafe(32)
        self.mutex = threading.RLock()
        self.stopping = threading.Event()
        self.job = None
        self.history = []
        self.worker = None
        self.snapshot = self.make_snapshot({}, console.docker_ok, console.docker_message)
        handler = self.make_handler()
        if console.config and port in console.config["ports"].values():
            port = 0
        try:
            self.server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        except OSError:
            if not port:
                raise
            self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.server.daemon_threads = True
        self.origin = f"http://127.0.0.1:{self.server.server_port}"
        self.url = f"{self.origin}/#token={self.token}"
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.monitor_thread = threading.Thread(target=self.monitor, daemon=True)

    def start(self):
        self.server_thread.start()
        self.monitor_thread.start()

    def close(self):
        self.stopping.set()
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join()
        if self.worker:
            self.worker.join()
        self.monitor_thread.join()

    def redact(self, message):
        message = re.sub(r"\x1b\[[0-9;]*m", "", str(message))
        config = self.console.config
        if config:
            for key, value in config["credentials"].items():
                if "PASSWORD" in key and value:
                    message = message.replace(str(value), "••••••••")
        return message.replace(self.token, "[sessione]")

    def make_snapshot(self, containers, docker_ok, docker_message):
        config = self.console.config
        ports = config["ports"] if config else cli.PORTS
        services = []
        for name, (title, description, category) in CATALOG.items():
            mode = "dev"
            if name == "app":
                mode = "run" if containers.get("app-run", {}).get("State") == "running" else "dev"
                container = containers.get("app-" + mode, {})
            else:
                container = containers.get(name, {})
            status = container.get("State", "stopped") if docker_ok else "unknown"
            scheme = "http" if name == "app" or name in cli.WEB_SERVICES else cli.SCHEMES[name]
            services.append({
                "id": name, "name": title, "description": description, "category": category,
                "status": status, "health": container.get("Health", ""), "port": ports[name],
                "url": f"{scheme}://127.0.0.1:{ports[name]}",
                "web": scheme == "http", "mode": mode,
                "dependency": cli.RESOURCE_DEPENDENCIES.get(name),
            })
        return {
            "project": cli.ROOT.name, "configured": config is not None,
            "docker": {"available": docker_ok, "message": docker_message},
            "services": services, "startup": config.get("startup", []) if config else [],
            "updatedAt": time.time(),
        }

    def refresh(self):
        ok, message = cli.docker_available()
        self.console.docker_ok, self.console.docker_message = ok, message
        containers = {}
        if ok and self.console.config:
            result = self.console.compose(["ps", "--all", "--format", "json"], capture=True, timeout=10)
            if result.returncode:
                ok, message = False, self.redact(result.stderr.strip() or "Stato Docker non disponibile")
            elif result.stdout.strip():
                raw = result.stdout.strip()
                rows = json.loads(raw) if raw.startswith("[") else [json.loads(line) for line in raw.splitlines()]
                containers = {row["Service"]: row for row in rows}
        snapshot = self.make_snapshot(containers, ok, message)
        with self.mutex:
            self.snapshot = snapshot

    def monitor(self):
        while not self.stopping.is_set():
            if self.console.operation_lock.acquire(blocking=False):
                try:
                    self.refresh()
                except Exception as error:
                    with self.mutex:
                        self.snapshot["docker"] = {"available": False, "message": self.redact(error)}
                finally:
                    self.console.operation_lock.release()
            self.stopping.wait(3)

    def state(self):
        with self.mutex:
            result = deepcopy(self.snapshot)
            result["job"] = deepcopy(self.job)
            result["history"] = deepcopy(self.history)
            return result

    def validate(self, data):
        if not isinstance(data, dict):
            raise ValueError("Richiesta non valida.")
        action, service = data.get("action"), data.get("service")
        if not isinstance(action, str):
            raise ValueError("Azione non valida.")
        if action in ("start", "stop", "restart", "configure"):
            if not isinstance(service, str) or service not in CATALOG:
                raise ValueError("Servizio non riconosciuto.")
        elif action not in ("setup", "stop-all", "startup"):
            raise ValueError("Azione non riconosciuta.")
        if action == "start" and service == "app" and data.get("mode", "dev") not in ("dev", "run"):
            raise ValueError("Scegli dev oppure run.")
        if action == "configure":
            port = data.get("port")
            if type(port) is not int or not 1024 <= port <= 65535:
                raise ValueError("La porta deve essere un numero tra 1024 e 65535.")
        if action == "startup":
            selected = data.get("services")
            if not isinstance(selected, list) or any(name not in cli.STARTUP_CHOICES for name in selected):
                raise ValueError("Componenti di avvio non validi.")
            if "dev" in selected and "run" in selected:
                raise ValueError("Scegli una sola modalità per l'app.")

    def submit(self, data):
        self.validate(data)
        with self.mutex:
            if self.stopping.is_set():
                raise RuntimeError("Lori si sta chiudendo.")
            if self.job and self.job["status"] == "running":
                raise RuntimeError("C'è già un'operazione in corso. Attendi che termini.")
            self.job = {
                "id": secrets.token_hex(8), "action": data["action"], "service": data.get("service"),
                "status": "running", "startedAt": time.time(), "messages": ["Operazione in coda…"],
            }
            self.worker = threading.Thread(target=self.perform, args=(deepcopy(data),), daemon=True)
            self.worker.start()
            return deepcopy(self.job)

    def record(self, message):
        with self.mutex:
            self.job["messages"].extend(self.redact(message).splitlines())
            self.job["messages"] = self.job["messages"][-80:]

    def perform(self, data):
        success = False
        with self.console.operation_lock:
            cli.OUTPUT.writer = self.record
            try:
                if self.stopping.is_set():
                    raise RuntimeError("Operazione annullata: Lori si sta chiudendo.")
                action, service = data["action"], data.get("service")
                if action == "setup":
                    self.console.setup([])
                    success = self.console.config is not None
                elif action == "startup":
                    if self.console.config is None:
                        raise ValueError("Prepara prima il progetto.")
                    self.console.set_startup(data["services"])
                    success = True
                else:
                    if not self.console.ready():
                        raise RuntimeError("Prepara il progetto e verifica che Docker sia attivo.")
                    if action == "start":
                        if service == "app":
                            success = self.console.app(data.get("mode", "dev"), [])
                        else:
                            dependency = cli.RESOURCE_DEPENDENCIES.get(service)
                            items = [dependency, service] if dependency else [service]
                            success = self.console.start_resources(items)
                    elif action == "stop":
                        success = self.console.stop([service])
                    elif action == "restart":
                        success = self.console.restart([service])
                    elif action == "stop-all":
                        success = self.console.stop(["all"])
                    elif action == "configure":
                        self.console.configure([service, str(data["port"])])
                        success = self.console.config["ports"][service] == data["port"]
                if not success:
                    raise RuntimeError("Operazione non riuscita. Controlla i dettagli e riprova.")
            except Exception as error:
                self.record(str(error))
            finally:
                del cli.OUTPUT.writer
                try:
                    self.refresh()
                except Exception as error:
                    self.record(f"Aggiornamento dello stato non riuscito: {error}")
                with self.mutex:
                    self.job["status"] = "success" if success else "error"
                    self.job["finishedAt"] = time.time()
                    self.history.insert(0, deepcopy(self.job))
                    self.history = self.history[:8]

    def details(self, service, kind):
        if service not in CATALOG:
            raise ValueError("Servizio non riconosciuto.")
        if not self.console.operation_lock.acquire(blocking=False):
            raise RuntimeError("Attendi che termini l'operazione in corso.")
        try:
            config = self.console.config
            if not config:
                raise ValueError("Prepara prima il progetto.")
            if kind == "credentials":
                fields = [{"name": key, "value": config["credentials"][key], "secret": "PASSWORD" in key}
                          for key in CREDENTIAL_KEYS.get(service, ())]
                notes = {
                    "redis": "Redis locale non richiede una password. Host nel container: redis, porta 6379.",
                    "redisinsight": "Aggiungi un database con host redis e porta 6379. Non serve una password.",
                    "adminer": "Scegli PostgreSQL e usa postgres come server.",
                    "phpmyadmin": "Usa le credenziali MySQL riportate qui sotto.",
                    "mongodb": "Per autenticarti usa il database admin (authSource=admin).",
                }
                return {"fields": fields, "note": notes.get(service, "Credenziali locali di sviluppo.")}
            target = service
            if service == "app":
                active = self.console.running()
                target = "app-run" if "app-run" in active else "app-dev"
            result = self.console.compose(["logs", "--no-color", "--tail", "80", target], capture=True, timeout=12)
            if result.returncode:
                raise RuntimeError(self.redact(result.stderr.strip() or "Log non disponibili."))
            return {"text": self.redact(result.stdout) or "Nessun log disponibile. Avvia il servizio per iniziare."}
        finally:
            self.console.operation_lock.release()

    def make_handler(self):
        dashboard = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(5)

            def log_message(self, *_args):
                pass

            def reply(self, status, payload, content_type="application/json; charset=utf-8"):
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                self.end_headers()
                self.wfile.write(body)

            def authorized(self, api=False):
                if self.headers.get("Host") != dashboard.origin.removeprefix("http://"):
                    self.reply(403, {"error": "Host non consentito."})
                    return False
                origin = self.headers.get("Origin")
                if origin and origin != dashboard.origin:
                    self.reply(403, {"error": "Origine non consentita."})
                    return False
                supplied_token = self.headers.get("X-Lori-Token", "")
                if api and (not supplied_token.isascii() or not secrets.compare_digest(supplied_token, dashboard.token)):
                    self.reply(401, {"error": "Sessione non valida. Apri il pannello dalla shell con panel."})
                    return False
                return True

            def do_GET(self):
                parsed = urlsplit(self.path)
                if not self.authorized(parsed.path.startswith("/api/")):
                    return
                try:
                    if parsed.path == "/api/state":
                        self.reply(200, dashboard.state())
                    elif parsed.path in ("/api/logs", "/api/credentials"):
                        service = parse_qs(parsed.query).get("service", [""])[0]
                        self.reply(200, dashboard.details(service, parsed.path.rsplit("/", 1)[1]))
                    else:
                        files = {
                            "/": (ASSETS / "index.html", "text/html; charset=utf-8"),
                            "/panel.css": (ASSETS / "panel.css", "text/css; charset=utf-8"),
                            "/panel.js": (ASSETS / "panel.js", "text/javascript; charset=utf-8"),
                            "/favicon.png": (cli.ROOT / "public" / "favicon.png", "image/png"),
                        }
                        if parsed.path not in files:
                            self.reply(404, {"error": "Pagina non trovata."})
                            return
                        path, content_type = files[parsed.path]
                        self.reply(200, path.read_bytes(), content_type)
                except ValueError as error:
                    self.reply(400, {"error": str(error)})
                except Exception as error:
                    self.reply(409, {"error": dashboard.redact(error)})

            def do_POST(self):
                if not self.authorized(api=True):
                    return
                if self.path != "/api/actions":
                    self.reply(404, {"error": "Azione non trovata."})
                    return
                try:
                    if self.headers.get_content_type() != "application/json":
                        raise ValueError("Invia una richiesta JSON.")
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 8192:
                        raise ValueError("Dimensione della richiesta non valida.")
                    data = json.loads(self.rfile.read(length))
                    self.reply(202, dashboard.submit(data))
                except (ValueError, UnicodeError) as error:
                    self.reply(400, {"error": str(error)})
                except RuntimeError as error:
                    self.reply(409, {"error": str(error)})

        return Handler
