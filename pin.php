<?php
/**
 * pin.php — lee/escribe los ids de modelos anclados en pins.json.
 * GET  -> {"ids": [...]}
 * POST {"ids": [...]} con header X-Pin-Token -> escribe pins.json (con .bak)
 */
header('Content-Type: application/json');
header('Cache-Control: no-store, max-age=0');
require __DIR__ . '/config.php';   // define $PIN_TOKEN (fichero local, NO versionado)
$file = __DIR__ . '/pins.json';
$token = $PIN_TOKEN;
$method = $_SERVER['REQUEST_METHOD'];

if ($method === 'GET') {
    echo file_exists($file) ? file_get_contents($file) : '{"ids":[]}';
    exit;
}

if ($method === 'POST') {
    if (!hash_equals($token, $_SERVER['HTTP_X_PIN_TOKEN'] ?? '')) {
        http_response_code(403);
        echo '{"error":"forbidden"}';
        exit;
    }
    $data = json_decode(file_get_contents('php://input'), true);
    if (!is_array($data) || !isset($data['ids']) || !is_array($data['ids'])) {
        http_response_code(400);
        echo '{"error":"bad request"}';
        exit;
    }
    $ids = array_values(array_filter($data['ids'], 'is_string'));
    $ids = array_values(array_unique($ids));
    if (file_exists($file)) {
        @copy($file, $file . '.bak');
    }
    if (file_put_contents($file, json_encode(['ids' => $ids], JSON_UNESCAPED_SLASHES)) === false) {
        http_response_code(500);
        echo '{"error":"write failed"}';
        exit;
    }
    echo json_encode(['ok' => true, 'count' => count($ids)]);
    exit;
}

http_response_code(405);
echo '{"error":"method not allowed"}';
