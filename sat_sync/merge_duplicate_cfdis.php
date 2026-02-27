<?php
declare(strict_types=1);

/**
 * One-off: fusiona filas duplicadas en sat_cfdi (mismo UUID en distinto caso)
 * y normaliza uuid a minúsculas.
 *
 * Causa: metadata (sync.php) y XML (verify_requests) podían guardar el mismo
 * UUID en distinto caso, generando dos filas por UNIQUE(issuer_id, direction, uuid).
 *
 * Uso: php sat_sync/merge_duplicate_cfdis.php [--dry-run]
 */

$dryRun = in_array('--dry-run', $argv ?? [], true);

$baseDir = realpath(__DIR__ . '/..');
if (false === $baseDir) {
    fwrite(STDERR, "No se pudo resolver ruta base.\n");
    exit(1);
}

$dbPath = $baseDir . '/invoicing.db';
if (! file_exists($dbPath)) {
    fwrite(STDERR, "No existe DB: {$dbPath}\n");
    exit(1);
}

$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

// Grupos (issuer_id, direction, LOWER(uuid)) con más de una fila
$stmt = $pdo->query("
    SELECT issuer_id, direction, LOWER(TRIM(uuid)) AS uuid_norm
    FROM sat_cfdi
    GROUP BY issuer_id, direction, LOWER(TRIM(uuid))
    HAVING COUNT(*) > 1
");
$groups = $stmt->fetchAll(PDO::FETCH_ASSOC);

if (empty($groups)) {
    fwrite(STDOUT, "No hay duplicados por (issuer_id, direction, uuid).\n");
} else {
    fwrite(STDOUT, "Grupos duplicados: " . count($groups) . "\n");
}

$getIdToKeep = $pdo->prepare("
    SELECT id FROM sat_cfdi
    WHERE issuer_id = :issuer_id AND direction = :direction AND LOWER(TRIM(uuid)) = :uuid_norm
    ORDER BY
        CASE WHEN xml_path IS NOT NULL AND TRIM(COALESCE(xml_path,'')) != '' THEN 0 ELSE 1 END,
        CASE WHEN total IS NOT NULL AND total >= 0.01 THEN 0 ELSE 1 END,
        id ASC
    LIMIT 1
");
$getDuplicateIds = $pdo->prepare("
    SELECT id, uuid, xml_path, total FROM sat_cfdi
    WHERE issuer_id = :issuer_id AND direction = :direction AND LOWER(TRIM(uuid)) = :uuid_norm
    ORDER BY id
");
$deleteRow = $pdo->prepare("DELETE FROM sat_cfdi WHERE id = :id");

$deleted = 0;
$normalized = 0;

foreach ($groups as $g) {
    $issuerId = (int) $g['issuer_id'];
    $direction = (string) $g['direction'];
    $uuidNorm = (string) $g['uuid_norm'];

    $getIdToKeep->execute([
        ':issuer_id' => $issuerId,
        ':direction' => $direction,
        ':uuid_norm' => $uuidNorm,
    ]);
    $keepRow = $getIdToKeep->fetch(PDO::FETCH_ASSOC);
    if (! $keepRow) {
        continue;
    }
    $keepId = (int) $keepRow['id'];

    $getDuplicateIds->execute([
        ':issuer_id' => $issuerId,
        ':direction' => $direction,
        ':uuid_norm' => $uuidNorm,
    ]);
    $rows = $getDuplicateIds->fetchAll(PDO::FETCH_ASSOC);

    foreach ($rows as $r) {
        $id = (int) $r['id'];
        if ($id === $keepId) {
            continue;
        }
        if (! $dryRun) {
            $deleteRow->execute([':id' => $id]);
        }
        $deleted++;
        fwrite(STDOUT, "  Eliminada fila id={$id} (uuid={$r['uuid']}) en favor de id={$keepId}\n");
    }
}

// Normalizar UUID a minúsculas en toda la tabla
if (! $dryRun) {
    $n = $pdo->exec("UPDATE sat_cfdi SET uuid = LOWER(TRIM(uuid)) WHERE uuid != LOWER(TRIM(uuid))");
    $normalized = $n !== false ? $n : 0;
} else {
    $normalized = 0;
}

if ($dryRun) {
    fwrite(STDOUT, "[DRY-RUN] Se habrían eliminado {$deleted} duplicados y normalizado UUIDs.\n");
} else {
    fwrite(STDOUT, "Eliminadas {$deleted} filas duplicadas. UUIDs normalizados: {$normalized}.\n");
}
