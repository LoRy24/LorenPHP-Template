"use strict";

const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) =>
    String(value).replace(
        /[&<>"']/g,
        (char) =>
            ({
                "&": "&amp;",
                "<": "&lt;",
                ">": "&gt;",
                '"': "&quot;",
                "'": "&#39;",
            })[char],
    );
const icon = (name) =>
    `<svg class="icon" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const fragment = new URLSearchParams(location.hash.slice(1));
const tokenKey = `lori-session:${location.origin}`;
let token = fragment.get("token") || sessionStorage.getItem(tokenKey);
if (fragment.has("token")) {
    sessionStorage.setItem(tokenKey, token);
    history.replaceState(null, "", location.pathname);
}
let state = null;
let connected = false;
let submitting = false;
let refreshing = false;
let filter = "all";
let selectedMode = "dev";
let cardSignature = "";
let lastFinishedJob = null;
let toastTimer;
let dialogRequest = 0;
const dialog = $("#detail-dialog");
const actionNames = {
    start: "Avvio",
    stop: "Arresto",
    restart: "Riavvio",
    "stop-all": "Arresto dell'ambiente",
    setup: "Preparazione del progetto",
    configure: "Modifica della porta",
    startup: "Avvio automatico aggiornato",
};
const resourceNames = {
    mysql: "MySQL",
    postgres: "PostgreSQL",
    mongodb: "MongoDB",
    redis: "Redis",
    phpmyadmin: "phpMyAdmin",
    adminer: "Adminer",
    "mongo-express": "Mongo Express",
    redisinsight: "Redis Insight",
    app: "Applicazione PHP",
};
const busy = () => submitting || state?.job?.status === "running";
const unavailable = () =>
    !connected || !state?.configured || !state?.docker.available || busy();
const disabled = (condition) => (condition ? "disabled" : "");
const serviceById = (id) =>
    state?.services.find((service) => service.id === id);

async function api(path, options = {}) {
    const response = await fetch(path, {
        ...options,
        headers: {
            "X-Lori-Token": token || "",
            ...(options.body ? { "Content-Type": "application/json" } : {}),
            ...options.headers,
        },
        cache: "no-store",
    });
    const result = await response.json();
    if (!response.ok)
        throw new Error(result.error || "Operazione non riuscita.");
    return result;
}

function toast(message, error = false) {
    const element = $("#toast");
    clearTimeout(toastTimer);
    element.textContent = message;
    element.classList.toggle("error", error);
    element.hidden = false;
    toastTimer = setTimeout(() => {
        element.hidden = true;
    }, 5000);
}

function statusBadge(service) {
    let status = connected ? service.status : "unknown";
    if (service.health === "unhealthy") status = "unhealthy";
    const labels = {
        running: "Attivo",
        stopped: "Spento",
        exited: "Spento",
        created: "Pronto",
        restarting: "Riavvio",
        paused: "In pausa",
        dead: "Errore",
        unknown: "Da verificare",
        unhealthy: "Da verificare",
    };
    return `<span class="state ${escapeHtml(status)}">${escapeHtml(labels[status] || status)}</span>`;
}

function controls(service, app = false) {
    const running = service.status === "running";
    const blocked = unavailable();
    return `<button class="button primary" data-action="start" data-service="${service.id}" aria-label="Avvia ${escapeHtml(service.name)}" ${disabled(blocked || running)}>${icon("play")}${app ? "Avvia app" : "Avvia"}</button>
        <button class="icon-button" data-action="stop" data-service="${service.id}" title="Ferma ${escapeHtml(service.name)}" aria-label="Ferma ${escapeHtml(service.name)}" ${disabled(blocked || !["running", "restarting", "paused"].includes(service.status))}>${icon("stop")}</button>
        <button class="icon-button" data-action="restart" data-service="${service.id}" title="Riavvia ${escapeHtml(service.name)}" aria-label="Riavvia ${escapeHtml(service.name)}" ${disabled(blocked || !running)}>${icon("restart")}</button>`;
}

function renderApp(service) {
    const running = service.status === "running";
    if (running) selectedMode = service.mode;
    const siteLink =
        running && connected
            ? `<a class="button ghost open-site" href="${escapeHtml(service.url)}" target="_blank" rel="noopener noreferrer">Apri sito ${icon("arrow")}</a>`
            : `<button class="button ghost open-site" disabled>Apri sito ${icon("arrow")}</button>`;
    return `<div class="app-top"><div class="app-identity"><span class="php-icon">php</span><div><h2>Applicazione PHP</h2><p>FrankenPHP · il cuore del progetto</p></div></div>${statusBadge(service)}</div>
        <div class="app-endpoint">${icon("window")}<span>${escapeHtml(service.url)}</span><button class="copy-button" data-copy="${escapeHtml(service.url)}" aria-label="Copia URL dell'app">${icon("copy")}</button><button class="text-button" data-port="app" aria-label="Configura porta dell'app" ${disabled(!connected || !state.configured || busy())}>${icon("settings")}</button><button class="text-button" data-logs="app" ${disabled(unavailable())}>${icon("terminal")} Log</button></div>
        <div class="app-controls"><div class="mode-switch" aria-label="Modalità dell'app"><button data-mode="dev" class="${selectedMode === "dev" ? "selected" : ""}" ${disabled(running || busy())}>DEV</button><button data-mode="run" class="${selectedMode === "run" ? "selected" : ""}" ${disabled(running || busy())}>RUN</button></div>${controls(service, true)}${siteLink}</div>`;
}

function renderService(service) {
    const running = service.status === "running";
    const openLink =
        service.web && running && connected
            ? `<a class="text-button open" href="${escapeHtml(service.url)}" target="_blank" rel="noopener noreferrer">Apri ${icon("arrow")}</a>`
            : "";
    return `<article class="service-card ${running ? "is-running" : ""}"><div class="service-card-top"><span class="service-icon ${service.id}">${icon(service.category === "database" ? "database" : "window")}</span>${statusBadge(service)}</div>
        <h3>${escapeHtml(service.name)}</h3><p class="service-description">${escapeHtml(service.description)}</p>
        <div class="endpoint-row"><code>127.0.0.1:${service.port}</code><button class="copy-button" data-copy="${escapeHtml(service.url)}" aria-label="Copia indirizzo ${escapeHtml(service.name)}">${icon("copy")}</button></div>
        <div class="service-actions">${controls(service)}</div>
        <div class="service-footer"><button class="text-button" data-logs="${service.id}" ${disabled(unavailable())}>${icon("terminal")}Log</button><button class="text-button" data-credentials="${service.id}" ${disabled(!connected || !state.configured || busy())}>${icon("key")}Accessi</button>${openLink}<button class="text-button" data-port="${service.id}" aria-label="Configura porta ${escapeHtml(service.name)}" title="Configura porta" ${disabled(!connected || !state.configured || busy())}>${icon("settings")}</button></div></article>`;
}

function jobLabel(job) {
    return `${actionNames[job.action] || job.action}${job.service ? " · " + resourceNames[job.service] : ""}`;
}

function renderActivity() {
    const jobs = [
        ...(state.job?.status === "running" ? [state.job] : []),
        ...state.history,
    ];
    $("#activity-list").innerHTML = jobs.length
        ? jobs
              .slice(0, 5)
              .map((job) => {
                  const time = new Date(
                      job.startedAt * 1000,
                  ).toLocaleTimeString("it-IT", {
                      hour: "2-digit",
                      minute: "2-digit",
                  });
                  const status =
                      job.status === "running"
                          ? "In corso"
                          : job.status === "success"
                            ? "Completato"
                            : "Non riuscito";
                  const detail =
                      job.status === "running"
                          ? job.messages.at(-1) || "Preparazione…"
                          : `${status} · ${time}`;
                  return `<div class="activity-row ${job.status}">${job.status === "running" ? '<span class="spinner" aria-label="In corso"></span>' : icon(job.status === "success" ? "check" : "close")}<div><p>${escapeHtml(jobLabel(job))}</p><small>${escapeHtml(detail)}</small></div><button class="text-button" data-job="${job.id}">Dettagli ${icon("arrow")}</button></div>`;
              })
              .join("")
        : '<p class="empty-state">Il workspace è pronto. Avvia un servizio per cominciare.</p>';
}

function render() {
    if (!state) return;
    $("#project-name").textContent = state.project;
    $("#project-name").title = state.project;
    $("#session-label").textContent = connected
        ? "Sessione locale attiva"
        : "Sessione disconnessa";
    $("#session-dot").classList.toggle("offline", !connected);
    $("#docker-pill").textContent = state.docker.available
        ? "Docker · disponibile"
        : "Docker · non disponibile";
    $("#docker-pill").title = state.docker.message;
    $("#active-count").textContent =
        connected && state.docker.available
            ? state.services.filter((service) => service.status === "running")
                  .length
            : "—";
    $("#startup-count").textContent = state.startup.length;
    $("#stop-all").disabled =
        unavailable() ||
        !state.services.some((service) =>
            ["running", "restarting", "paused"].includes(service.status),
        );
    $("#startup-nav").disabled = !connected || !state.configured || busy();
    const notice = $("#notice");
    notice.hidden = connected && state.configured && state.docker.available;
    if (!connected)
        notice.textContent =
            "Connessione a Lori interrotta. Se hai chiuso la shell, riaprila e scrivi panel per iniziare una nuova sessione.";
    else if (!state.configured)
        notice.innerHTML = `<span>Prepara questo progetto per iniziare a usare l'ambiente.</span><button class="button primary" data-action="setup" ${disabled(busy())}>Prepara progetto</button>`;
    else if (!state.docker.available)
        notice.textContent =
            state.docker.message +
            ". Avvia Docker: il pannello si aggiorna automaticamente.";
    const signature = JSON.stringify([
        state.services,
        connected,
        unavailable(),
        busy(),
        filter,
        selectedMode,
        state.configured,
    ]);
    if (signature !== cardSignature) {
        cardSignature = signature;
        $("#app-card").innerHTML = renderApp(serviceById("app"));
        $("#service-grid").innerHTML = state.services
            .filter(
                (service) =>
                    service.id !== "app" &&
                    (filter === "all" || service.category === filter),
            )
            .map(renderService)
            .join("");
        $("#quick-links").innerHTML = state.services
            .filter((service) => service.category === "interface")
            .map((service) => {
                const content = `<span>${escapeHtml(service.name)}<small>${service.status === "running" ? ":" + service.port : "Da avviare"}</small></span>${icon("arrow")}`;
                return service.status === "running" && connected
                    ? `<a class="quick-link" href="${escapeHtml(service.url)}" target="_blank" rel="noopener noreferrer">${content}</a>`
                    : `<div class="quick-link disabled" aria-disabled="true">${content}</div>`;
            })
            .join("");
    }
    renderActivity();
    if (dialog.open && dialog.dataset.job) {
        const job = [state.job, ...state.history].find(
            (item) => item?.id === dialog.dataset.job,
        );
        if (job) $("#dialog-content pre").textContent = job.messages.join("\n");
    }
}

async function refresh() {
    if (refreshing || !token) return;
    refreshing = true;
    try {
        const next = await api("/api/state");
        connected = true;
        if (
            next.job &&
            next.job.status !== "running" &&
            next.job.id !== lastFinishedJob
        ) {
            if (
                state?.job?.id === next.job.id &&
                state.job.status === "running"
            )
                toast(
                    next.job.status === "success"
                        ? `${jobLabel(next.job)}: completato.`
                        : next.job.messages.at(-1),
                    next.job.status === "error",
                );
            lastFinishedJob = next.job.id;
        }
        state = next;
    } catch (error) {
        connected = false;
        if (!state) {
            $("#notice").hidden = false;
            $("#notice").textContent = error.message;
            $("#session-label").textContent = "Sessione non disponibile";
        }
    } finally {
        refreshing = false;
        render();
    }
}

async function submit(data) {
    if (busy()) return;
    submitting = true;
    render();
    try {
        const job = await api("/api/actions", {
            method: "POST",
            body: JSON.stringify(data),
        });
        state.job = job;
    } catch (error) {
        toast(error.message, true);
    } finally {
        submitting = false;
        render();
        setTimeout(refresh, 500);
    }
}

function openDialog(title, eyebrow = "WORKSPACE") {
    dialogRequest++;
    delete dialog.dataset.job;
    $("#dialog-title").textContent = title;
    $("#dialog-eyebrow").textContent = eyebrow;
    $("#dialog-content").replaceChildren();
    if (!dialog.open) dialog.showModal();
    return dialogRequest;
}

async function openDetails(service, kind) {
    const request = openDialog(
        resourceNames[service],
        kind === "logs" ? "LOG DEL SERVIZIO" : "CREDENZIALI E CONNESSIONE",
    );
    $("#dialog-content").innerHTML = '<p class="dialog-note">Caricamento…</p>';
    try {
        const data = await api(
            `/api/${kind}?service=${encodeURIComponent(service)}`,
        );
        if (request !== dialogRequest || !dialog.open) return;
        if (kind === "logs") {
            $("#dialog-content").innerHTML =
                '<p class="dialog-note">Ultime 80 righe. Riapri questa finestra per aggiornarle.</p><pre class="log-output"></pre>';
            $("#dialog-content pre").textContent = data.text;
        } else {
            $("#dialog-content").innerHTML =
                `<p class="dialog-note">${escapeHtml(data.note)}</p>${data.fields.map((field, index) => `<label class="field-label" for="credential-${index}">${escapeHtml(field.name)}</label><div class="field-row"><input id="credential-${index}" readonly type="${field.secret ? "password" : "text"}" value="${escapeHtml(field.value)}" autocomplete="off">${field.secret ? `<button class="button ghost" data-reveal="credential-${index}">Mostra</button>` : ""}<button class="icon-button" data-copy-field="credential-${index}" aria-label="Copia ${escapeHtml(field.name)}">${icon("copy")}</button></div>`).join("")}`;
        }
    } catch (error) {
        if (request === dialogRequest)
            $("#dialog-content").textContent = error.message;
    }
}

function openStartup() {
    if (!state?.configured || busy()) return;
    openDialog("Un avvio tutto tuo.", "AVVIO AUTOMATICO");
    const selected = new Set(state.startup);
    $("#dialog-content").innerHTML =
        `<form id="startup-form"><p class="dialog-note">Scegli cosa accendere alla prossima apertura di Lori. Se selezioni un'interfaccia, aggiungeremo anche il database necessario.</p><label class="field-label" for="startup-mode">Applicazione PHP</label><select id="startup-mode"><option value="">Non avviare automaticamente</option><option value="dev" ${selected.has("dev") ? "selected" : ""}>Modalità sviluppo · dev</option><option value="run" ${selected.has("run") ? "selected" : ""}>Immagine dell'app · run</option></select><div class="checkbox-grid">${state.services
            .filter((service) => service.id !== "app")
            .map(
                (service) =>
                    `<label><input type="checkbox" name="service" value="${service.id}" ${selected.has(service.id) ? "checked" : ""}>${escapeHtml(service.name)}</label>`,
            )
            .join(
                "",
            )}</div><div class="form-footer"><button class="button primary" type="submit">Salva preferenze</button></div></form>`;
}

function openPort(service) {
    const resource = serviceById(service);
    openDialog(resource.name, "CONFIGURA LA PORTA");
    $("#dialog-content").innerHTML =
        `<form id="port-form" data-service="${service}"><p class="dialog-note">Scegli la porta locale di ${escapeHtml(resource.name)}. Se il servizio è attivo, Lori lo riavvia con il nuovo indirizzo.</p><label class="field-label" for="service-port">Porta su 127.0.0.1</label><input class="port-input" id="service-port" type="number" min="1024" max="65535" value="${resource.port}" required><div class="form-footer"><button class="button primary" type="submit">Salva porta</button></div></form>`;
}

async function copy(value) {
    try {
        await navigator.clipboard.writeText(value);
        toast("Copiato negli appunti.");
    } catch {
        toast(
            "Copia non disponibile. Puoi selezionare e copiare il testo.",
            true,
        );
    }
}

document.addEventListener("click", (event) => {
    const target = event.target.closest("button, a");
    if (!target || target.disabled) return;
    const data = target.dataset;
    if (data.action)
        submit({
            action: data.action,
            ...(data.service ? { service: data.service } : {}),
            ...(data.service === "app" ? { mode: selectedMode } : {}),
        });
    if (data.mode) {
        selectedMode = data.mode;
        cardSignature = "";
        render();
    }
    if (data.filter) {
        filter = data.filter;
        document
            .querySelectorAll("[data-filter]")
            .forEach((button) =>
                button.classList.toggle("selected", button === target),
            );
        render();
    }
    if (data.copy) copy(data.copy);
    if (data.copyField) copy(document.getElementById(data.copyField).value);
    if (data.reveal) {
        const field = document.getElementById(data.reveal);
        field.type = field.type === "password" ? "text" : "password";
        target.textContent = field.type === "password" ? "Mostra" : "Nascondi";
    }
    if (data.logs) openDetails(data.logs, "logs");
    if (data.credentials) openDetails(data.credentials, "credentials");
    if (data.port) openPort(data.port);
    if (data.job) {
        const job = [state.job, ...state.history].find(
            (item) => item?.id === data.job,
        );
        if (job) {
            openDialog(jobLabel(job), "DETTAGLI OPERAZIONE");
            dialog.dataset.job = job.id;
            $("#dialog-content").innerHTML = '<pre class="log-output"></pre>';
            $("#dialog-content pre").textContent = job.messages.join("\n");
        }
    }
    if (target.matches("a.nav-link"))
        document
            .querySelectorAll("a.nav-link")
            .forEach((link) =>
                link.classList.toggle("active", link === target),
            );
});

document.addEventListener("submit", (event) => {
    if (event.target.id === "startup-form") {
        event.preventDefault();
        const services = [
            ...event.target.querySelectorAll('input[name="service"]:checked'),
        ].map((input) => input.value);
        const mode = $("#startup-mode").value;
        if (mode) services.push(mode);
        dialog.close();
        submit({ action: "startup", services });
    } else if (event.target.id === "port-form") {
        event.preventDefault();
        const data = {
            action: "configure",
            service: event.target.dataset.service,
            port: Number($("#service-port").value),
        };
        dialog.close();
        submit(data);
    }
});

$("#startup-nav").addEventListener("click", openStartup);
$("#stop-all").addEventListener("click", () => submit({ action: "stop-all" }));
$("#close-dialog").addEventListener("click", () => dialog.close());
dialog.addEventListener("close", () => {
    dialogRequest++;
    $("#dialog-content").replaceChildren();
    delete dialog.dataset.job;
});
if (!token) {
    $("#notice").hidden = false;
    $("#notice").textContent =
        "Apri questo pannello dalla shell Lori con il comando panel per collegare la sessione.";
    $("#session-label").textContent = "Sessione da collegare";
    $("#stop-all").disabled = true;
    $("#startup-nav").disabled = true;
} else {
    refresh();
    setInterval(refresh, 2500);
}
