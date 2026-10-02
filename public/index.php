<?php

declare(strict_types=1);

$sourceDirectory = realpath(dirname(__DIR__) . "/src");
if ($sourceDirectory === false) {
    throw new RuntimeException("La cartella src non è disponibile.");
}

$autoload = dirname(__DIR__) . "/vendor/autoload.php";
if (is_file($autoload)) {
    require $autoload;
}

$path = parse_url($_SERVER["REQUEST_URI"] ?? "/", PHP_URL_PATH);
$path = is_string($path) ? rawurldecode($path) : "";

// URL puliti: /api/hello cerca src/api/hello.php.
// Ogni cartella può avere index.php: / cerca src/index.php,
// mentre /api cerca src/api/index.php.
if (preg_match("~\A/(?:[a-z0-9_-]+(?:/[a-z0-9_-]+)*)?/?\z~D", $path)) {
    $route = trim($path, "/");
    if ($route === "") {
        $candidates = [$sourceDirectory . DIRECTORY_SEPARATOR . "index.php"];
    } else {
        $relativePath = str_replace("/", DIRECTORY_SEPARATOR, $route);
        $basePath = $sourceDirectory . DIRECTORY_SEPARATOR . $relativePath;
        $candidates = [
            $basePath . ".php",
            $basePath . DIRECTORY_SEPARATOR . "index.php",
        ];
    }

    foreach ($candidates as $candidate) {
        $directory = dirname($candidate);
        if (!is_dir($directory)) {
            continue;
        }

        // Rispetta esattamente il nome del file anche su filesystem che ignorano le maiuscole.
        $entries = scandir($directory);
        if (
            $entries === false ||
            !in_array(basename($candidate), $entries, true)
        ) {
            continue;
        }

        $file = realpath($candidate);

        // Non seguire symlink o percorsi che escono da src.
        if ($file !== false && $file === $candidate && is_file($file)) {
            require $file;
            return;
        }
    }
}

http_response_code(404);
header("Content-Type: application/json; charset=utf-8");
echo '{"error":"Not found"}';
