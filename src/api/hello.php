<?php

declare(strict_types=1);

header("Content-Type: application/json; charset=utf-8");

echo json_encode(
    ["message" => "Ciao da Lori!", "path" => "/api/hello"],
    JSON_THROW_ON_ERROR,
);
