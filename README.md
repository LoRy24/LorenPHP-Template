# LorenPHP Template

Un punto di partenza per i progetti PHP che vuoi far crescere senza passare la prima giornata a sistemare l'ambiente. Al centro c'è **FrankenPHP**; intorno c'è **Lori**, una piccola console interattiva che prepara il progetto, avvia l'app e gestisce i servizi Docker scelti da te.

Apri Lori, scrivi i comandi al suo prompt e continua a lavorare. Puoi usare MySQL, MongoDB, PostgreSQL e Redis, insieme alle loro interfacce web, senza installarli sul computer. La schermata iniziale mostra gli indirizzi dei servizi attivi; quando ne avvii uno, Lori mostra anche le credenziali utili. Puoi scegliere quali componenti avviare automaticamente nelle prossime sessioni. Quando esci da Lori, i container del progetto si fermano. I dati dei servizi restano nella cartella locale `.docker-data/`, pronta per la sessione successiva.

## Da dove cominciare

Servono **Python 3.9+** e **Docker con Compose v2**. Su macOS o Linux, dalla cartella del progetto:

```sh
./lori
```

Su Windows, da PowerShell o Prompt dei comandi:

```bat
lori.cmd
```

Se aggiungi la cartella del progetto al `PATH`, puoi richiamare il launcher con `lori`. I comandi seguenti si scrivono **dentro la shell di Lori**, senza anteporre `lori`:

```text
setup-project
start mysql
start phpmyadmin
dev
```

Ora trovi l'app su <http://127.0.0.1:8080> e phpMyAdmin su <http://127.0.0.1:8081>. `setup-project` crea `.docker-data/` e `.lori/config.json` con credenziali casuali. Sono cartelle locali ignorate da Git. Il primo avvio può richiedere qualche minuto per scaricare e costruire le immagini. All'inizio nessun servizio parte automaticamente: sei tu a scegliere quelli da avviare.

## Scegli cosa parte all'apertura

Scrivi `startup` per aprire un elenco numerato: inserisci i numeri dei componenti desiderati, separati da spazi. Se preferisci un comando diretto:

```text
startup set dev mysql phpmyadmin
```

La scelta viene salvata in `.lori/config.json` e vale dalla prossima apertura di Lori **in questa cartella**. `startup show` la riepiloga e `startup clear` la cancella. Puoi scegliere `dev` oppure `run` per l'app; le due modalità usano la stessa porta. Se selezioni un'interfaccia web, Lori include automaticamente il database corrispondente. `configure startup` apre lo stesso elenco numerato.

All'apertura Lori avvia i componenti scelti, stampa i loro URL e le credenziali di accesso, poi mostra la schermata principale con tutti gli indirizzi attivi. `home` la mostra di nuovo quando vuoi. Le password restano nel file locale `.lori/config.json`, ignorato da Git; tieni presente che chi può leggere il terminale le vedrà quando avvii i servizi.

## La giornata tipo

Scrivi `help` nella shell per vedere tutti i comandi, oppure `help dev` per una spiegazione breve. Quelli più utili sono:

| Comando                          | Cosa fa                                                                          |
| -------------------------------- | -------------------------------------------------------------------------------- |
| `setup-project`                  | Prepara cartelle dati e configurazione locale.                                   |
| `configure`                      | Mostra e modifica le porte; per esempio `configure mysql 3307`.                  |
| `startup`                        | Sceglie dall'elenco i componenti da avviare all'apertura.                        |
| `startup set dev mysql`          | Salva una scelta direttamente; `startup clear` la cancella.                      |
| `home`                           | Mostra la schermata iniziale e gli URL dei servizi attivi.                       |
| `start mysql`                    | Avvia una risorsa. Usa `start all` per avviarle tutte.                           |
| `stop mysql`                     | Ferma una risorsa; `stop app` ferma l'app.                                       |
| `restart mysql`                  | Ricrea una risorsa già attiva.                                                   |
| `dev`                            | Avvia l'app con i sorgenti montati: aggiorni il browser e vedi le modifiche PHP. |
| `run`                            | Costruisce e avvia una copia dell'app senza montare i sorgenti.                  |
| `format`                         | Formatta i file supportati con Prettier e indentazione a quattro spazi.          |
| `format-check`                   | Controlla la formattazione senza cambiare i file.                                |
| `prettier --write src/index.php` | Passa argomenti direttamente a Prettier.                                         |
| `composer install` / `php -v`    | Esegue Composer o PHP nel container.                                             |
| `status` / `credentials`         | Mostra indirizzi dei servizi attivi o tutte le credenziali locali.               |
| `logs app --follow`              | Segue i log dell'app; Ctrl+C torna al prompt.                                    |
| `reset-resource mysql`           | Cancella i dati di MySQL; chiede di scrivere `RESET`.                            |
| `quit`                           | Chiude Lori e spegne i container del progetto.                                   |

Anche `exit` e la chiusura dello standard input terminano la shell. I container vengono rimossi, mentre i dati in `.docker-data/` restano. `reset-resource <nome> --yes` salta la conferma: usalo solo se vuoi davvero eliminare i dati di quella risorsa. Se era accesa, Lori la riavvia dopo il reset.

Quando cambi la porta di un servizio già attivo, Lori lo ricrea con la nuova porta. Una risorsa spenta resta spenta. Per controllare le porte prima di avviare qualcosa, usa `configure` o `status`.

## Database e interfacce

Tutte le porte sono esposte soltanto su `127.0.0.1`. Le interfacce di amministrazione sono servizi separati: avvia prima il database corrispondente.

| Servizio   | Porta iniziale | Interfaccia web                            |
| ---------- | -------------: | ------------------------------------------ |
| App        |           8080 | <http://127.0.0.1:8080>                    |
| MySQL      |           3306 | phpMyAdmin, porta 8081, tema scuro BooDark |
| MongoDB    |          27017 | mongo-express, porta 8083                  |
| PostgreSQL |           5432 | Adminer, porta 8082                        |
| Redis      |           6379 | Redis Insight, porta 5540                  |

Dal container dell'app, gli host dei servizi sono `mysql`, `mongodb`, `postgres` e `redis`. Le variabili `MYSQL_*`, `POSTGRES_*`, `MONGODB_URI` e `REDIS_HOST` sono già disponibili in PHP. Dal computer, usa `127.0.0.1` e le porte mostrate da `status`. Per Adminer scegli PostgreSQL e usa il server `postgres`; per Redis Insight aggiungi una connessione a `redis:6379`. Le password sono mostrate da `credentials`.

Se modifichi una password in `.lori/config.json` dopo la prima inizializzazione del database, esegui `reset-resource` per inizializzarlo con la nuova credenziale.

## Pagine e routing

Il routing segue i file in `src/`. Non devi registrare ogni pagina in uno `switch`: crei un file PHP e il suo percorso diventa l'URL, senza l'estensione `.php`.

| File                | URL                              |
| ------------------- | -------------------------------- |
| `src/index.php`     | `/` (pagina iniziale)            |
| `src/health.php`    | `/health`                        |
| `src/api/index.php` | `/api`                           |
| `src/api/hello.php` | `/api/hello`                     |
| `src/contatti.php`  | `/contatti`, se aggiungi il file |

La pagina iniziale è in `src/index.php`, come tutte le altre pagine: lì puoi preparare i dati con PHP e stampare l'HTML. L'esempio include una piccola funzione per rendere sicuri i valori dinamici inseriti nella pagina. Per un'altra pagina o un endpoint API, aggiungi un file in `src/` o in una sua sottocartella. Usa nomi di percorso minuscoli, con lettere, numeri, trattini o underscore. Un file `index.php` rappresenta l'URL della sua cartella. I percorsi sconosciuti restituiscono 404.

`public/index.php` è il piccolo punto d'ingresso che trova il file richiesto. Lo stile resta in `public/assets/css/app.css`, e `public/favicon.png` è già collegata alla pagina. Con `dev` attivo, aggiungi o modifichi un file in `src/` e aggiorni il browser per vedere il risultato.

Prettier usa quattro spazi, tramite `.prettierrc.json`, e formatta PHP, CSS, Markdown e gli altri formati supportati. Lori lo esegue in un container Node: **non serve installare Node sul computer**. La prima esecuzione scarica le dipendenze definite in `package-lock.json` e crea `node_modules/`, ignorata da Git.

## Build e distribuzione

`dev` legge i file montati a ogni richiesta. `run` costruisce un'immagine con una copia del codice. `build-image` prepara soltanto l'immagine Docker dell'app.

`build-standalone` usa il [builder statico di FrankenPHP](https://frankenphp.dev/docs/embed/) per creare `dist/lori-app-linux-amd64`: un binario **Linux amd64** con app e web server inclusi. Su Linux si avvia così:

```sh
./dist/lori-app-linux-amd64 php-server
```

La porta predefinita del binario è `8080` ed è definita nel `Caddyfile` alla radice. Le estensioni incluse sono elencate in `docker/standalone.Dockerfile`. La build può essere lunga e richiede accesso a GitHub; se incontri un errore `403 rate limit exceeded`, imposta `GITHUB_TOKEN` nell'ambiente prima di aprire Lori e riprova. Il token viene passato a BuildKit come segreto temporaneo.

## Mappa del progetto

```text
lori, lori.cmd          launcher per macOS/Linux e Windows
tools/lori_cli.py       shell interattiva
src/index.php           logica e HTML della pagina iniziale
src/health.php          endpoint /health
src/api/                esempio di cartella con URL /api e /api/hello
public/                 file serviti dal web server, inclusi CSS e favicon
docker/                 Compose e immagini Docker
Caddyfile               configurazione del binario standalone
.docker-data/           dati locali dei servizi, creati da setup-project
.lori/                  porte e credenziali locali, create da setup-project
node_modules/           strumenti Prettier locali, creati al primo uso
dist/                   risultato delle build standalone
```
