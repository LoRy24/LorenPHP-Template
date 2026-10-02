<?php

declare(strict_types=1);

header("Content-Type: text/html; charset=utf-8");

// Qui puoi preparare i dati della pagina con normale codice PHP.
// I valori inseriti nell'HTML vanno sempre convertiti in testo sicuro.
$escape = static function (string $value): string {
    return htmlspecialchars($value, ENT_QUOTES, "UTF-8");
};
$phpVersion = $escape(PHP_VERSION);
$environment = $escape(getenv("APP_ENV") ?: "development");

echo <<<HTML
<!doctype html>
<html lang="it">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="theme-color" content="#0b111a">
        <title>Lori · FrankenPHP</title>
        <link rel="icon" type="image/png" href="/favicon.png">
        <link rel="stylesheet" href="/assets/css/app.css">
    </head>
    <body>
        <main class="welcome">
            <p class="eyebrow">Lori / PHP workspace</p>
            <h1>Pronto a creare.</h1>
            <p class="intro">
                Questa è la tua base di partenza. Modifica
                <code>src/index.php</code> per cambiare la pagina e la sua
                logica; usa <code>public/assets/css/app.css</code>
                per personalizzare lo stile.
            </p>

            <ul class="details" aria-label="Ambiente di sviluppo">
                <li>FrankenPHP</li>
                <li>PHP {$phpVersion}</li>
                <li>{$environment}</li>
                <li><a href="/health">/health</a></li>
                <li><a href="/api/hello">/api/hello</a></li>
            </ul>
        </main>
    </body>
</html>
HTML;
