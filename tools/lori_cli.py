"""Interactive command center for the LorenPHP template (Python standard library only)."""

from __future__ import annotations

import difflib
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
import webbrowser


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".lori"
CONFIG = STATE / "config.json"
DATA = ROOT / ".docker-data"
COMPOSE_FILE = ROOT / "docker" / "compose.yaml"
NODE_IMAGE = "node:22-alpine"
PRETTIER_LOCK = ROOT / "package-lock.json"
PRETTIER_STAMP = ROOT / "node_modules" / ".lori-prettier-lock"
RESOURCES = ("mysql", "mongodb", "postgres", "redis", "phpmyadmin", "adminer", "mongo-express", "redisinsight")
SERVICES = ("app-dev", "app-run") + RESOURCES
DATA_SERVICES = ("mysql", "mongodb", "postgres", "redis", "redisinsight")
STARTUP_CHOICES = ("dev", "run") + RESOURCES
RESOURCE_DEPENDENCIES = {
    "phpmyadmin": "mysql",
    "adminer": "postgres",
    "mongo-express": "mongodb",
    "redisinsight": "redis",
}
WEB_SERVICES = {"dev", "run", "phpmyadmin", "adminer", "mongo-express", "redisinsight"}
SCHEMES = {"mysql": "mysql", "mongodb": "mongodb", "postgres": "postgresql", "redis": "redis"}
PORTS = {
    "app": 8080,
    "mysql": 3306,
    "mongodb": 27017,
    "postgres": 5432,
    "redis": 6379,
    "phpmyadmin": 8081,
    "adminer": 8082,
    "mongo-express": 8083,
    "redisinsight": 5540,
}
PORT_ENV = {
    "app": "APP_PORT",
    "mysql": "MYSQL_PORT",
    "mongodb": "MONGODB_PORT",
    "postgres": "POSTGRES_PORT",
    "redis": "REDIS_PORT",
    "phpmyadmin": "PHPMYADMIN_PORT",
    "adminer": "ADMINER_PORT",
    "mongo-express": "MONGO_EXPRESS_PORT",
    "redisinsight": "REDISINSIGHT_PORT",
}
HELP = {
    "help": "Mostra questa guida o help <comando>.",
    "setup-project": "Crea .docker-data e la configurazione locale con credenziali casuali.",
    "configure": "Imposta le porte: configure <servizio> <porta>; configure startup sceglie l'avvio.",
    "startup": "Scegli cosa avviare all'apertura: startup oppure startup set <servizi>.",
    "home": "Mostra di nuovo la schermata principale con gli indirizzi attivi.",
    "panel": "Apre il pannello web locale per gestire app, servizi e accessi.",
    "start": "Avvia un servizio: start <nome> oppure start all.",
    "stop": "Ferma un servizio: stop <nome>, stop app oppure stop all.",
    "restart": "Riavvia un servizio già attivo: restart <nome>.",
    "dev": "Avvia l'app FrankenPHP con il codice montato (modifiche PHP immediate).",
    "run": "Ricostruisce e avvia una copia dell'app senza bind mount.",
    "build-image": "Costruisce l'immagine Docker dell'app.",
    "build-standalone": "Compila l'app in un binario Linux amd64 in dist/.",
    "composer": "Esegue Composer nel container: composer install, composer require ...",
    "php": "Esegue PHP nel container: php -v, php script.php ...",
    "format": "Formatta il progetto con Prettier (4 spazi).",
    "format-check": "Controlla la formattazione senza modificare file.",
    "prettier": "Passa argomenti a Prettier: prettier --write src/index.php.",
    "reset-resource": "Cancella i dati di un servizio: reset-resource <nome> [--yes].",
    "status": "Mostra Docker, app, risorse e porte.",
    "credentials": "Mostra credenziali di sviluppo e indirizzi locali.",
    "logs": "Mostra log: logs <servizio|app> [--follow].",
    "quit": "Chiude lori e ferma i container del progetto.",
}


class UI:
    def __init__(self) -> None:
        self.color = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        if os.name == "nt" and self.color:
            os.system("")  # enable ANSI virtual terminal where supported

    def tint(self, value: str, code: str) -> str:
        return f"\033[{code}m{value}\033[0m" if self.color else value

    def title(self, value: str) -> str:
        return self.tint(value, "1;95")

    def accent(self, value: str) -> str:
        return self.tint(value, "1;96")

    def link(self, value: str) -> str:
        return self.tint(value, "4;96")

    def prompt(self, name: str) -> str:
        top = self.dim("╭─") + self.title(" LORI ") + self.dim("──") + self.accent(f" {name} ")
        bottom = self.dim("╰─") + self.tint("❯ ", "1;92")
        return f"{top}\n{bottom}"

    def good(self, value: str) -> str:
        return self.tint(value, "1;92")

    def warn(self, value: str) -> str:
        return self.tint(value, "1;93")

    def bad(self, value: str) -> str:
        return self.tint(value, "1;91")

    def dim(self, value: str) -> str:
        return self.tint(value, "2")


UIX = UI()
OUTPUT = threading.local()


def say(message: str = "") -> None:
    writer = getattr(OUTPUT, "writer", None)
    if writer is not None:
        writer(message)
        return
    try:
        print(message, flush=True)
    except BrokenPipeError:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")


def secret() -> str:
    return secrets.token_urlsafe(24)


def default_config() -> dict:
    return {
        "version": 1,
        "ports": PORTS.copy(),
        "startup": [],
        "credentials": {
            "MYSQL_ROOT_PASSWORD": secret(),
            "MYSQL_DATABASE": "lori_app",
            "MYSQL_USER": "lori",
            "MYSQL_PASSWORD": secret(),
            "MONGO_USER": "lori",
            "MONGO_PASSWORD": secret(),
            "POSTGRES_DB": "lori_app",
            "POSTGRES_USER": "lori",
            "POSTGRES_PASSWORD": secret(),
            "MONGO_EXPRESS_USER": "lori",
            "MONGO_EXPRESS_PASSWORD": secret(),
        },
    }


def save_config(config: dict) -> None:
    STATE.mkdir(exist_ok=True)
    temp = CONFIG.with_suffix(".tmp")
    temp.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    if os.name != "nt":
        os.chmod(temp, 0o600)
    temp.replace(CONFIG)


def load_config() -> dict | None:
    if not CONFIG.exists():
        return None
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        if config.get("version") != 1 or set(config["ports"]) != set(PORTS):
            raise ValueError("formato di configurazione non riconosciuto")
        startup = config.setdefault("startup", [])
        if not isinstance(startup, list) or any(item not in STARTUP_CHOICES for item in startup) or ("dev" in startup and "run" in startup):
            raise ValueError("selezione di avvio automatico non valida")
        return config
    except (OSError, ValueError, KeyError, TypeError) as error:
        say(UIX.bad(f"Configurazione non valida: {error}"))
        return None


def docker_available() -> tuple[bool, str]:
    if not shutil.which("docker"):
        return False, "Docker non è installato o non è nel PATH"
    try:
        result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Docker non risponde"
    if result.returncode:
        return False, "Docker è installato, ma il daemon non è disponibile"
    try:
        compose = subprocess.run(["docker", "compose", "version", "--short"], capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return False, "Docker Compose non risponde"
    if compose.returncode:
        return False, "Docker Compose v2 non è disponibile"
    return True, f"Docker {result.stdout.strip()} · Compose {compose.stdout.strip()}"


def project_name() -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", ROOT.name.lower()).strip("-")[:24] or "lori"
    digest = hashlib.sha256(str(ROOT).encode()).hexdigest()[:8]
    return f"{slug}-{digest}"


def compact_run(command: list[str], *, cwd: Path, env: dict | None = None) -> subprocess.CompletedProcess:
    """Keep long Docker builds readable while retaining recent output for failures."""
    recent: deque[str] = deque(maxlen=35)
    shown: set[str] = set()
    finished = threading.Event()
    report = getattr(OUTPUT, "writer", say)

    def heartbeat() -> None:
        while not finished.wait(30):
            report("  Operazione Docker in corso…")

    process = subprocess.Popen(command, cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", bufsize=1)
    threading.Thread(target=heartbeat, daemon=True).start()
    try:
        assert process.stdout is not None
        for raw in process.stdout:
            line = raw.strip()
            for token_name in ("GITHUB_TOKEN", "GH_TOKEN"):
                token = os.environ.get(token_name)
                if token:
                    line = line.replace(token, "[segreto]")
            if not line:
                continue
            recent.append(line)
            stage = re.match(r"^#\d+ \[([^]]+)\] (.+)$", line)
            if stage and stage.group(1) != "internal" and stage.group(1) not in shown:
                shown.add(stage.group(1))
                say(UIX.dim(f"  {stage.group(1)} · {stage.group(2)[:72]}"))
            elif line.startswith(("Container ", "Image ", "Network ")) and any(word in line for word in ("Started", "Created", "Built", "Pulled")):
                say(UIX.dim("  " + line))
        code = process.wait()
    except KeyboardInterrupt:
        process.send_signal(signal.SIGINT if os.name != "nt" else signal.SIGTERM)
        process.wait()
        raise
    finally:
        finished.set()
    if code:
        say(UIX.bad("Docker ha restituito un errore. Ultime righe:"))
        for line in recent:
            say(line)
    return subprocess.CompletedProcess(command, code, stdout="\n".join(recent))


class Console:
    def __init__(self) -> None:
        self.config = load_config()
        self.docker_ok, self.docker_message = docker_available()
        self.managed = False
        self.operation_lock = threading.RLock()
        self.dashboard = None

    def ready(self) -> bool:
        if self.config is None:
            say(UIX.warn("Prima esegui setup-project."))
            return False
        if not self.docker_ok:
            self.docker_ok, self.docker_message = docker_available()
        if not self.docker_ok:
            say(UIX.bad(self.docker_message))
            return False
        return True

    def env(self) -> dict:
        assert self.config is not None
        values = os.environ.copy()
        values["LORI_ROOT"] = str(ROOT)
        values["COMPOSE_PROGRESS"] = "plain"
        values["COMPOSE_ANSI"] = "never"
        values["BUILDKIT_PROGRESS"] = "plain"
        for name, port in self.config["ports"].items():
            values[PORT_ENV[name]] = str(port)
        values.update(self.config["credentials"])
        return values

    def compose(self, args: list[str], *, capture: bool = False, compact: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess:
        command = ["docker", "compose", "-p", project_name(), "-f", str(COMPOSE_FILE), "--profile", "app"] + args
        if compact:
            return compact_run(command, cwd=ROOT, env=self.env())
        if not capture and getattr(OUTPUT, "writer", None) is not None:
            result = subprocess.run(command, cwd=ROOT, env=self.env(), text=True, capture_output=True)
            if result.stdout:
                say(result.stdout.strip())
            if result.stderr:
                say(result.stderr.strip())
            return result
        return subprocess.run(command, cwd=ROOT, env=self.env(), text=True, capture_output=capture, timeout=timeout)

    def start_panel(self) -> None:
        if self.dashboard is None:
            from lori_web import Dashboard

            try:
                self.dashboard = Dashboard(self)
                self.dashboard.start()
            except OSError as error:
                self.dashboard = None
                say(UIX.warn(f"Pannello web non disponibile: {error}"))

    def panel(self, args: list[str]) -> None:
        if args:
            say("Uso: panel")
            return
        self.start_panel()
        if self.dashboard is not None:
            say(UIX.link(self.dashboard.url))
            webbrowser.open(self.dashboard.url)

    def running(self) -> set[str]:
        if not self.ready():
            return set()
        result = self.compose(["ps", "--status", "running", "--services"], capture=True)
        if result.returncode:
            say(UIX.bad(result.stderr.strip() or "Impossibile leggere lo stato Docker."))
            return set()
        return set(result.stdout.split())

    def setup(self, args: list[str]) -> None:
        if args:
            say("Uso: setup-project")
            return
        if self.config is None and CONFIG.exists():
            say(UIX.bad("Correggi o rimuovi .lori/config.json prima di continuare."))
            return
        for service in DATA_SERVICES:
            (DATA / service).mkdir(parents=True, exist_ok=True)
        if self.config is None:
            self.config = default_config()
            save_config(self.config)
            say(UIX.good("Progetto preparato: .docker-data e .lori/config.json creati."))
        else:
            say(UIX.good("Cartelle dati verificate. La configurazione esistente è stata conservata."))
        say("Suggerimento: startup per scegliere l'avvio automatico · start mysql → dev")

    def endpoint(self, service: str) -> str:
        assert self.config is not None
        name = "app" if service in ("dev", "run", "app-dev", "app-run") else service
        scheme = "http" if name == "app" or service in WEB_SERVICES else SCHEMES[name]
        return f"{scheme}://127.0.0.1:{self.config['ports'][name]}"

    def show_access(self, services: list[str]) -> None:
        assert self.config is not None
        credentials = self.config["credentials"]
        details = {
            "mysql": ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE", "MYSQL_ROOT_PASSWORD"),
            "mongodb": ("MONGO_USER", "MONGO_PASSWORD"),
            "postgres": ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"),
            "phpmyadmin": ("MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"),
            "adminer": ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"),
            "mongo-express": ("MONGO_EXPRESS_USER", "MONGO_EXPRESS_PASSWORD"),
        }
        for service in services:
            say(f"  {UIX.good('●')} {UIX.accent(f'{service:<16}')} {UIX.link(self.endpoint(service))}")
            for key in details.get(service, ()):
                say(f"      {UIX.dim(f'{key:<24}')} {UIX.warn(str(credentials[key]))}")
            if service == "redis":
                say(UIX.dim("      Nessuna password configurata per Redis locale."))
            if service == "redisinsight":
                say(UIX.dim("      Aggiungi una connessione con host redis e porta 6379."))

    def home(self, args: list[str]) -> None:
        if args:
            say("Uso: home")
            return
        say(UIX.title("\n  ╭────────────────────────────────────────────────────╮"))
        say(UIX.accent("  │  LORI  ✦  il tuo spazio PHP, pronto quando vuoi    │"))
        say(UIX.title("  ╰────────────────────────────────────────────────────╯"))
        docker_state = UIX.good("● " + self.docker_message) if self.docker_ok else UIX.warn("○ " + self.docker_message)
        say(f"  {docker_state}")
        if self.dashboard is not None:
            say("  " + UIX.dim("Pannello web: ") + UIX.link(self.dashboard.url))
            say("  " + UIX.dim("Scrivi panel per aprirlo nel browser."))
        if self.config is None:
            say("  " + UIX.warn("Progetto da preparare") + UIX.dim("  ·  scrivi setup-project"))
            return
        selected = self.config.get("startup", [])
        say("  " + UIX.dim("Avvio automatico: ") + (UIX.accent(", ".join(selected)) if selected else UIX.dim("nessuno · usa startup per scegliere")))
        say()
        say(UIX.title("  SERVIZI ATTIVI"))
        active = self.running() if self.docker_ok else set()
        listed = [service for service in SERVICES if service in active]
        if listed:
            self.show_active_endpoints(listed)
        else:
            say("  " + UIX.dim("Nessun servizio attivo. Prova start mysql oppure dev."))
        say()
        say("  " + UIX.dim("help comandi  ·  status stato  ·  credentials accessi  ·  quit chiude tutto"))

    def show_active_endpoints(self, services: list[str]) -> None:
        for service in services:
            label = service.replace("app-", "app ") if service.startswith("app-") else service
            say(f"  {UIX.good('●')} {UIX.accent(f'{label:<16}')} {UIX.link(self.endpoint(service))}")

    def startup(self, args: list[str]) -> None:
        if self.config is None:
            say(UIX.warn("Prima esegui setup-project."))
            return
        if not args:
            selected = set(self.config.get("startup", []))
            say(UIX.title("\n  AVVIO AUTOMATICO"))
            say(UIX.dim("  Scegli i numeri dei componenti, separati da spazi. Invio conserva la scelta."))
            for number, name in enumerate(STARTUP_CHOICES, 1):
                mark = UIX.good("●") if name in selected else UIX.dim("○")
                say(f"  {mark} {number:>2}  {UIX.accent(name)}")
            try:
                answer = input(UIX.prompt("selezione")).strip()
            except (EOFError, KeyboardInterrupt):
                say()
                return
            if not answer:
                return
            try:
                numbers = [int(part) for part in re.split(r"[\s,]+", answer)]
                if any(number < 1 or number > len(STARTUP_CHOICES) for number in numbers):
                    raise ValueError
            except ValueError:
                say(UIX.bad("Inserisci i numeri mostrati, separati da spazi o virgole."))
                return
            self.set_startup([STARTUP_CHOICES[number - 1] for number in numbers])
            return
        if args == ["show"]:
            selected = self.config.get("startup", [])
            say("Avvio automatico: " + (", ".join(selected) if selected else "nessuno"))
        elif args == ["clear"]:
            self.set_startup([])
        elif args[0] == "set" and len(args) > 1:
            self.set_startup(args[1:])
        else:
            say("Uso: startup [show|clear|set <dev|run|mysql|mongodb|postgres|redis|phpmyadmin|adminer|mongo-express|redisinsight> ...]")

    def set_startup(self, choices: list[str]) -> None:
        if any(choice not in STARTUP_CHOICES for choice in choices):
            say(UIX.bad("Selezione non valida. Scrivi startup per vedere i componenti disponibili."))
            return
        if "dev" in choices and "run" in choices:
            say(UIX.bad("Scegli dev oppure run: usano la stessa porta."))
            return
        selected = set(choices)
        for service, dependency in RESOURCE_DEPENDENCIES.items():
            if service in selected:
                selected.add(dependency)
        ordered = [service for service in STARTUP_CHOICES if service in selected]
        assert self.config is not None
        self.config["startup"] = ordered
        save_config(self.config)
        say(UIX.good("Avvio automatico salvato: " + (", ".join(ordered) if ordered else "nessuno")))
        say(UIX.dim("La scelta vale dalla prossima apertura di Lori in questa cartella."))

    def start_selected(self) -> None:
        if self.config is None or not self.config.get("startup"):
            return
        if not self.ready():
            return
        selected = self.config["startup"]
        say(UIX.title("\n  AVVIO DEI COMPONENTI SELEZIONATI"))
        resources = [service for service in RESOURCES if service in selected]
        if resources:
            if not self.start_resources(resources):
                return
        if "dev" in selected or "run" in selected:
            self.app("dev" if "dev" in selected else "run", [])

    def status(self, args: list[str]) -> None:
        if args:
            say("Uso: status")
            return
        self.docker_ok, self.docker_message = docker_available()
        say(f"Docker: {UIX.good(self.docker_message) if self.docker_ok else UIX.bad(self.docker_message)}")
        if self.config is None:
            say("Progetto: da preparare con setup-project")
            return
        if not self.docker_ok:
            say(UIX.warn("Stato dei servizi non disponibile finché Docker non risponde."))
            return
        running = self.running()
        active = [service for service in SERVICES if service in running]
        if active:
            say(UIX.title("Servizi attivi"))
            self.show_active_endpoints(active)
        else:
            say(UIX.dim("Nessun servizio attivo."))
        inactive = [service for service in SERVICES if service not in running]
        say(UIX.dim("Spenti: " + ", ".join(inactive)))

    def configure(self, args: list[str]) -> None:
        if self.config is None:
            say(UIX.warn("Prima esegui setup-project."))
            return
        if args == ["startup"]:
            self.startup([])
            return
        if not args:
            say(UIX.title("Porte locali"))
            for name, port in self.config["ports"].items():
                say(f"  {UIX.accent(f'{name:<15}')} {UIX.warn(str(port))}")
            say(UIX.dim("Invio = termina · formato: <servizio> <nuova porta>"))
            while True:
                try:
                    line = input(UIX.title("configure › ")).strip()
                except (EOFError, KeyboardInterrupt):
                    say()
                    return
                if not line:
                    return
                try:
                    parts = shlex.split(line)
                except ValueError as error:
                    say(UIX.bad(str(error)))
                    continue
                self.configure(parts)
            return
        if len(args) != 2 or args[0] not in PORTS:
            say("Uso: configure <app|mysql|mongodb|postgres|redis|phpmyadmin|adminer|mongo-express|redisinsight> <porta>")
            return
        service, raw = args
        try:
            port = int(raw)
        except ValueError:
            say(UIX.bad("La porta deve essere un numero."))
            return
        if port < 1024 or port > 65535:
            say(UIX.bad("Scegli una porta tra 1024 e 65535."))
            return
        for other, used in self.config["ports"].items():
            if other != service and used == port:
                say(UIX.bad(f"La porta {port} è già assegnata a {other}."))
                return
        old = self.config["ports"][service]
        if old == port:
            say("La porta è già impostata così.")
            return
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.bind(("127.0.0.1", port))
        except OSError:
            say(UIX.bad(f"La porta {port} è già occupata sul computer."))
            return
        targets = ("app-dev", "app-run") if service == "app" else (service,)
        active = [item for item in targets if item in self.running()] if self.docker_ok else []
        self.config["ports"][service] = port
        save_config(self.config)
        say(UIX.good(f"{service}: {old} → {port}"))
        failed = False
        for item in active:
            say(f"Riconfiguro {item}, che era già attivo…")
            result = self.compose(["up", "-d", "--no-deps", "--force-recreate", item])
            if result.returncode:
                failed = True
                say(UIX.bad(f"Riavvio di {item} non riuscito."))
            else:
                self.managed = True
                self.show_access([item])
        if failed:
            self.config["ports"][service] = old
            save_config(self.config)
            say(UIX.warn(f"Ripristino la porta precedente {old}."))
            for item in active:
                self.compose(["up", "-d", "--no-deps", "--force-recreate", item])

    def start_resources(self, items: list[str]) -> bool:
        for item in items:
            if item in DATA_SERVICES:
                (DATA / item).mkdir(parents=True, exist_ok=True)
        say(UIX.accent(f"Avvio: {', '.join(items)}"))
        result = self.compose(["up", "-d", "--no-deps"] + items, compact=True)
        if result.returncode == 0:
            self.managed = True
            self.show_access(items)
            return True
        say(UIX.bad("Avvio non riuscito. Controlla le porte e i log Docker."))
        return False

    def start(self, args: list[str]) -> None:
        if len(args) != 1 or args[0] not in (*RESOURCES, "all"):
            say("Uso: start <mysql|mongodb|postgres|redis|phpmyadmin|adminer|mongo-express|redisinsight|all>")
            return
        if not self.ready():
            return
        items = list(RESOURCES) if args[0] == "all" else [args[0]]
        self.start_resources(items)

    def stop(self, args: list[str]) -> bool:
        if len(args) != 1 or args[0] not in (*RESOURCES, "app", "all"):
            say("Uso: stop <servizio|app|all>")
            return False
        if not self.ready():
            return False
        if args[0] == "all":
            items = list(SERVICES)
        elif args[0] == "app":
            items = ["app-dev", "app-run"]
        else:
            items = [args[0]]
        result = self.compose(["stop"] + items)
        if result.returncode == 0:
            say(UIX.good(f"Fermati: {', '.join(items)}"))
        return result.returncode == 0

    def restart(self, args: list[str]) -> bool:
        if len(args) != 1 or args[0] not in (*RESOURCES, "app"):
            say("Uso: restart <servizio|app>")
            return False
        if not self.ready():
            return False
        running = self.running()
        items = [s for s in ("app-dev", "app-run") if s in running] if args[0] == "app" else [args[0]]
        if not items or any(s not in running for s in items):
            say(UIX.warn("Il servizio non è attivo. Usa start, dev o run."))
            return False
        success = True
        for item in items:
            result = self.compose(["up", "-d", "--no-deps", "--force-recreate", item])
            if result.returncode == 0:
                self.managed = True
                self.show_access([item])
            else:
                success = False
        return success

    def app(self, mode: str, args: list[str]) -> bool:
        if args:
            say(f"Uso: {mode}")
            return False
        if not self.ready():
            return False
        target = "app-dev" if mode == "dev" else "app-run"
        other = "app-run" if mode == "dev" else "app-dev"
        if other in self.running():
            if self.compose(["stop", other]).returncode:
                return False
        command = ["up", "-d", "--no-deps", "--build"]
        command.append(target)
        say("Avvio FrankenPHP…" if mode == "dev" else "Compilo l'immagine e avvio FrankenPHP…")
        result = self.compose(command, compact=True)
        if result.returncode == 0:
            self.managed = True
            self.show_access([mode])
            say(UIX.dim("Il server rimane attivo mentre la shell lori è aperta."))
        else:
            say(UIX.bad("Avvio dell'app non riuscito."))
        return result.returncode == 0

    def build_image(self, args: list[str]) -> None:
        if args:
            say("Uso: build-image")
            return
        if not self.ready():
            return
        result = self.compose(["build", "app-run"], compact=True)
        if result.returncode == 0:
            say(UIX.good("Immagine dell'app pronta."))

    def build_standalone(self, args: list[str]) -> None:
        if args:
            say("Uso: build-standalone")
            return
        if not self.ready():
            return
        image = f"{project_name()}-standalone"
        output = ROOT / "dist" / "lori-app-linux-amd64"
        output.parent.mkdir(exist_ok=True)
        say("Compilo il binario Linux amd64. Il primo build può richiedere diversi minuti…")
        command = ["docker", "build", "--progress=plain", "--platform", "linux/amd64"]
        token_name = "GITHUB_TOKEN" if os.environ.get("GITHUB_TOKEN") else "GH_TOKEN" if os.environ.get("GH_TOKEN") else None
        if token_name:
            command += ["--secret", f"id=github_token,env={token_name}"]
        command += ["-f", str(ROOT / "docker" / "standalone.Dockerfile"), "-t", image, str(ROOT)]
        result = compact_run(command, cwd=ROOT)
        if result.returncode:
            if "rate limit exceeded" in (result.stdout or "").lower():
                say(UIX.warn("Limite GitHub raggiunto. Imposta GITHUB_TOKEN nell'ambiente prima di avviare lori e riprova."))
            say(UIX.bad("Compilazione standalone non riuscita."))
            return
        created = subprocess.run(["docker", "create", "--platform", "linux/amd64", image], capture_output=True, text=True)
        if created.returncode:
            say(UIX.bad(created.stderr.strip() or "Impossibile estrarre il binario."))
            return
        container = created.stdout.strip()
        try:
            copied = subprocess.run(["docker", "cp", f"{container}:/go/src/app/dist/frankenphp-linux-x86_64", str(output)])
            if copied.returncode == 0:
                if os.name != "nt":
                    output.chmod(output.stat().st_mode | 0o111)
                say(UIX.good(f"Binario pronto: {output}"))
                say("Su Linux: ./dist/lori-app-linux-amd64 php-server")
            else:
                say(UIX.bad("Il binario compilato non è stato trovato nell'immagine."))
        finally:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True)

    def code_tool(self, tool: str, args: list[str]) -> None:
        if not args:
            say(f"Uso: {tool} <argomenti>")
            return
        if not self.ready():
            return
        if self.compose(["build", "app-dev"], compact=True).returncode:
            say(UIX.bad("Impossibile preparare l'immagine PHP."))
            return
        result = self.compose(["run", "--rm", "--no-deps", "app-dev", tool] + args)
        if result.returncode:
            say(UIX.bad(f"{tool} è terminato con codice {result.returncode}."))

    def node_command(self, args: list[str]) -> subprocess.CompletedProcess:
        command = ["docker", "run", "--rm", "--mount", f"type=bind,source={ROOT},target=/workspace", "--workdir", "/workspace"]
        if os.name != "nt" and hasattr(os, "getuid"):
            command += ["--user", f"{os.getuid()}:{os.getgid()}"]
        command += ["--env", "npm_config_cache=/tmp/npm-cache", NODE_IMAGE] + args
        return subprocess.run(command, cwd=ROOT)

    def prepare_prettier(self) -> bool:
        if not self.docker_ok:
            self.docker_ok, self.docker_message = docker_available()
        if not self.docker_ok:
            say(UIX.bad(self.docker_message))
            return False
        if not PRETTIER_LOCK.exists():
            say(UIX.bad("Manca package-lock.json: ripristina il file dal template."))
            return False
        lock_hash = hashlib.sha256(PRETTIER_LOCK.read_bytes()).hexdigest()
        executable = ROOT / "node_modules" / "prettier" / "bin" / "prettier.cjs"
        if executable.exists() and PRETTIER_STAMP.exists() and PRETTIER_STAMP.read_text(encoding="utf-8") == lock_hash:
            return True
        say("Preparo Prettier nel container Node…")
        if self.node_command(["npm", "ci", "--no-audit", "--no-fund"]).returncode:
            say(UIX.bad("Installazione di Prettier non riuscita."))
            return False
        PRETTIER_STAMP.write_text(lock_hash, encoding="utf-8")
        return True

    def prettier(self, args: list[str], *, mode: str = "custom") -> None:
        if mode != "custom" and args:
            say(f"Uso: {mode}")
            return
        if mode == "custom" and not args:
            say("Uso: prettier <argomenti> (es. prettier --write src/index.php)")
            return
        if not self.prepare_prettier():
            return
        prettier_args = args if mode == "custom" else (["--write", "."] if mode == "format" else ["--check", "."])
        result = self.node_command(["node", "./node_modules/prettier/bin/prettier.cjs"] + prettier_args)
        if result.returncode:
            say(UIX.bad(f"Prettier è terminato con codice {result.returncode}."))
        elif mode == "format-check":
            say(UIX.good("Formattazione corretta."))
        elif mode == "format":
            say(UIX.good("File formattati."))

    def reset_resource(self, args: list[str]) -> None:
        if not args or args[0] not in DATA_SERVICES or len(args) > 2 or (len(args) == 2 and args[1] != "--yes"):
            say("Uso: reset-resource <mysql|mongodb|postgres|redis|redisinsight> [--yes]")
            return
        if not self.ready():
            return
        service = args[0]
        if "--yes" not in args:
            try:
                answer = input(UIX.warn(f"Eliminerò tutti i dati di {service}. Scrivi RESET per continuare: "))
            except (EOFError, KeyboardInterrupt):
                say()
                return
            if answer != "RESET":
                say("Operazione annullata.")
                return
        was_running = service in self.running()
        if self.compose(["stop", service]).returncode:
            return
        if self.compose(["rm", "-f", "-s", service]).returncode:
            return
        folder = DATA / service
        try:
            if folder.exists():
                shutil.rmtree(folder)
        except OSError:
            # Linux bind mounts can contain files owned by the container's root user.
            cleanup = subprocess.run([
                "docker", "run", "--rm", "--mount", f"type=bind,source={folder},target=/lori-data",
                "alpine:3.21", "sh", "-c", "find /lori-data -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +",
            ])
            if cleanup.returncode:
                say(UIX.bad(f"Non riesco a svuotare {folder}."))
                return
        folder.mkdir(parents=True, exist_ok=True)
        say(UIX.good(f"Dati di {service} eliminati."))
        if was_running:
            say(f"Riavvio {service}…")
            if self.compose(["up", "-d", "--no-deps", service]).returncode == 0:
                self.managed = True
                self.show_access([service])

    def credentials(self, args: list[str]) -> None:
        if args:
            say("Uso: credentials")
            return
        if self.config is None:
            say(UIX.warn("Prima esegui setup-project."))
            return
        say(UIX.title("Credenziali locali di sviluppo"))
        for key, value in self.config["credentials"].items():
            say(f"  {UIX.accent(f'{key:<27}')} {UIX.warn(str(value))}")
        say(UIX.dim("Dal container app usa i nomi mysql, mongodb, postgres e redis; dal computer 127.0.0.1 e le porte di configure."))

    def logs(self, args: list[str]) -> None:
        if not args or args[0] not in (*RESOURCES, "app") or len(args) > 2 or (len(args) == 2 and args[1] != "--follow"):
            say("Uso: logs <servizio|app> [--follow]")
            return
        if not self.ready():
            return
        if args[0] == "app":
            running = self.running()
            service = "app-dev" if "app-dev" in running else "app-run"
        else:
            service = args[0]
        command = ["logs", "--tail", "80"]
        if "--follow" in args:
            command.append("--follow")
        try:
            self.compose(command + [service])
        except KeyboardInterrupt:
            say()

    def show_help(self, args: list[str]) -> None:
        if args:
            command = args[0]
            if command in HELP:
                say(f"{UIX.title(command)}  {HELP[command]}")
            else:
                say(UIX.bad(f"Comando sconosciuto: {command}"))
            return
        say(UIX.title("LORI  /  guida rapida"))
        say(UIX.dim("Scrivi i comandi nella shell lori. All'apertura partono solo i componenti scelti con startup."))
        for command, description in HELP.items():
            say(f"  {UIX.title(f'{command:<19}')} {description}")
        say()
        say("Primo avvio: setup-project → startup → dev")
        say("Risorse: mysql, mongodb, postgres, redis, phpmyadmin, adminer, mongo-express, redisinsight")
        say("Ctrl+C interrompe il comando corrente; quit chiude la shell.")

    def execute(self, line: str) -> bool:
        try:
            args = shlex.split(line)
        except ValueError as error:
            say(UIX.bad(f"Sintassi: {error}"))
            return True
        if not args:
            return True
        command, rest = args[0].lower(), args[1:]
        if command in ("quit", "exit", "q"):
            return False
        actions = {
            "help": self.show_help,
            "setup-project": self.setup,
            "configure": self.configure,
            "startup": self.startup,
            "home": self.home,
            "panel": self.panel,
            "start": self.start,
            "stop": self.stop,
            "restart": self.restart,
            "dev": lambda values: self.app("dev", values),
            "run": lambda values: self.app("run", values),
            "build-image": self.build_image,
            "build-standalone": self.build_standalone,
            "composer": lambda values: self.code_tool("composer", values),
            "php": lambda values: self.code_tool("php", values),
            "format": lambda values: self.prettier(values, mode="format"),
            "format-check": lambda values: self.prettier(values, mode="format-check"),
            "prettier": self.prettier,
            "reset-resource": self.reset_resource,
            "status": self.status,
            "credentials": self.credentials,
            "logs": self.logs,
        }
        action = actions.get(command)
        if action is None:
            matches = difflib.get_close_matches(command, list(actions) + ["quit"], n=1, cutoff=0.5)
            hint = f" Intendevi {matches[0]}?" if matches else " Scrivi help."
            say(UIX.bad(f"Comando sconosciuto: {command}.{hint}"))
            return True
        with self.operation_lock:
            action(rest)
        return True

    def close(self) -> None:
        if self.dashboard is not None:
            say(UIX.dim("Chiudo il pannello e attendo eventuali operazioni in corso…"))
            self.dashboard.close()
            self.dashboard = None
        if self.config is None:
            return
        self.docker_ok, _ = docker_available()
        if self.docker_ok:
            say(UIX.dim("Fermo i container del progetto…"))
            result = self.compose(["down", "--remove-orphans"], capture=True)
            if result.returncode:
                say(UIX.bad(result.stderr.strip() or "Docker non ha fermato tutti i container."))
            else:
                say(UIX.good("Ambiente fermato. I dati restano in .docker-data."))
        else:
            say(UIX.warn("Docker non è disponibile: verifica manualmente eventuali container rimasti attivi."))

    def loop(self) -> int:
        try:
            self.start_panel()
            try:
                with self.operation_lock:
                    self.start_selected()
            except KeyboardInterrupt:
                say(UIX.warn("\nAvvio interrotto. Controlla i servizi con status."))
            self.home([])
            try:
                import readline  # type: ignore

                commands = list(HELP) + ["exit", "q"]

                def complete(text: str, state: int) -> str | None:
                    matches = [c for c in commands if c.startswith(text)]
                    return matches[state] if state < len(matches) else None

                readline.set_completer(complete)
                readline.parse_and_bind("tab: complete")
            except ImportError:
                pass
            while True:
                try:
                    line = input(UIX.prompt(ROOT.name))
                    if not self.execute(line):
                        break
                except KeyboardInterrupt:
                    say("\nScrivi quit per chiudere lori.")
                except EOFError:
                    say()
                    break
        finally:
            self.close()
        return 0


def main() -> int:
    if len(sys.argv) > 1:
        say("Lori è una shell interattiva: esegui semplicemente lori (o ./lori).")
        return 2
    def terminate(_number: int, _frame: object) -> None:
        raise SystemExit(143)

    for name in ("SIGTERM", "SIGHUP"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), terminate)
    return Console().loop()
