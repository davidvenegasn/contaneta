<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\Fiel;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\FielRequestBuilder;
use PhpCfdi\SatWsDescargaMasiva\Service;
use PhpCfdi\SatWsDescargaMasiva\Shared\DateTimePeriod;
use PhpCfdi\SatWsDescargaMasiva\Shared\DownloadType;
use PhpCfdi\SatWsDescargaMasiva\Shared\DocumentStatus;
use GuzzleHttp\Client as GuzzleClient;
use PhpCfdi\SatWsDescargaMasiva\Services\Query\QueryParameters;
use PhpCfdi\SatWsDescargaMasiva\WebClient\GuzzleWebClient;

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Este script solo se ejecuta por CLI.\n");
    exit(1);
}

/**
 * Uso:
 *   php sat_sync/sync_xml.php <issuer_id> <issued|received> [--month=YYYY-MM] [--backfill=<dias>] [--reset] [--window=<horas>] [--loop] [--max-windows=<n>]
 *
 * Ejemplos:
 *   # Backfill por mes completo (recomendado)
 *   php sat_sync/sync_xml.php 1 issued --month=2026-01
 *
 *   # Backfill por ventanas
 *   php sat_sync/sync_xml.php 1 issued --backfill=90 --window=6 --loop
 *   php sat_sync/sync_xml.php 1 received --backfill=90 --window=6 --loop
 */

$issuerId = (int)($argv[1] ?? 0);
$direction = (string)($argv[2] ?? 'issued'); // issued|received

if ($issuerId <= 0 || ! in_array($direction, ['issued', 'received'], true)) {
    fwrite(STDERR, "Uso: php sat_sync/sync_xml.php <issuer_id> <issued|received>\n");
    exit(1);
}

$backfillDays = 7;
$reset = false;
$windowHours = 6;
$loop = false;
$maxWindows = 200;
$month = null; // formato YYYY-MM para backfill mensual

foreach ($argv as $arg) {
    if (str_starts_with($arg, '--month=')) {
        $val = trim(substr($arg, strlen('--month=')));
        if (preg_match('/^\d{4}-\d{2}$/', $val) === 1) {
            $month = $val;
        } else {
            fwrite(STDERR, "Formato inválido para --month. Usa YYYY-MM (ej. 2026-01)\n");
            exit(1);
        }
        continue;
    }
    if (str_starts_with($arg, '--backfill=')) {
        $val = (int)substr($arg, strlen('--backfill='));
        if ($val >= 1 && $val <= 3650) $backfillDays = $val;
        continue;
    }
    if ($arg === '--reset') { $reset = true; continue; }
    if ($arg === '--loop') { $loop = true; continue; }
    if (str_starts_with($arg, '--window=')) {
        $val = (int)substr($arg, strlen('--window='));
        if ($val >= 1 && $val <= 720) $windowHours = $val;
        continue;
    }
    if (str_starts_with($arg, '--max-windows=')) {
        $val = (int)substr($arg, strlen('--max-windows='));
        if ($val >= 1 && $val <= 10000) $maxWindows = $val;
        continue;
    }
}

// Si se especifica --month, se ejecuta una sola ventana (mes completo)
if (null !== $month) {
    $reset = true;   // recalcula desde el mes indicado
    $loop = false;   // una sola ejecución
    $maxWindows = 1; // por claridad
}

// === Paths ===
$baseDir = realpath(__DIR__ . '/..'); // raíz del proyecto (donde está invoicing.db)
if (false === $baseDir) {
    fwrite(STDERR, "No se pudo resolver la ruta base del proyecto.\n");
    exit(1);
}

$dbPath = $baseDir . '/invoicing.db';
if (! file_exists($dbPath)) {
    fwrite(STDERR, "No existe invoicing.db en: {$dbPath}\n");
    exit(1);
}

// === DB ===
$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec('PRAGMA foreign_keys = ON;');

// SQLite concurrency settings (avoid "database is locked")
$pdo->exec("PRAGMA busy_timeout = 5000;");
$pdo->exec("PRAGMA journal_mode = WAL;");
$pdo->exec("PRAGMA synchronous = NORMAL;");

$tz = new DateTimeZone('America/Mexico_City');

// === Storage XML ===
$xmlBase = $baseDir . '/storage/xml';
@mkdir($xmlBase, 0775, true);

// === Helper: checkpoint por sat_sync_state ===
$getState = function () use ($pdo, $issuerId, $direction): array {
    $stmt = $pdo->prepare(
        "SELECT last_sync_from, last_sync_to, last_run_at
         FROM sat_sync_state
         WHERE issuer_id = :issuer_id AND direction = :direction
         LIMIT 1"
    );
    $stmt->execute([':issuer_id' => $issuerId, ':direction' => $direction]);
    $row = $stmt->fetch(PDO::FETCH_ASSOC);
    return $row ?: ['last_sync_from' => null, 'last_sync_to' => null, 'last_run_at' => null];
};

$setState = function (DateTimeImmutable $from, DateTimeImmutable $to) use ($pdo, $issuerId, $direction): void {
    // Asegura fila
    $pdo->prepare(
        "INSERT INTO sat_sync_state(issuer_id, direction, last_sync_from, last_sync_to, last_run_at)
         VALUES(:issuer_id, :direction, NULL, NULL, datetime('now'))
         ON CONFLICT(issuer_id, direction) DO UPDATE SET last_run_at = datetime('now')"
    )->execute([':issuer_id' => $issuerId, ':direction' => $direction]);

    // Actualiza checkpoint
    $pdo->prepare(
        "UPDATE sat_sync_state
         SET last_sync_from = :from,
             last_sync_to   = :to,
             last_run_at    = datetime('now')
         WHERE issuer_id = :issuer_id AND direction = :direction"
    )->execute([
        ':from' => $from->format('Y-m-d H:i:s'),
        ':to' => $to->format('Y-m-d H:i:s'),
        ':issuer_id' => $issuerId,
        ':direction' => $direction,
    ]);
};

// === Helper: log opcional en sat_jobs (NO se usa para checkpoint) ===
$logJob = function (string $status, DateTimeImmutable $from, DateTimeImmutable $to, ?string $err = null) use ($pdo, $issuerId, $direction): void {
    // Si no existe sat_jobs en DB, no truena.
    try {
        $stmt = $pdo->prepare(
            "INSERT INTO sat_jobs(issuer_id, job_type, direction, window_from, window_to, status, attempts, started_at, finished_at, last_error)
             VALUES(:issuer_id, 'xml', :direction, :from, :to, :status, 1, datetime('now'), datetime('now'), :err)"
        );
        $stmt->execute([
            ':issuer_id' => $issuerId,
            ':direction' => $direction,
            ':from' => $from->format('Y-m-d H:i:s'),
            ':to' => $to->format('Y-m-d H:i:s'),
            ':status' => $status,
            ':err' => $err,
        ]);
    } catch (Throwable $e) {
        // ignore
    }
};

// === 1) Obtener credenciales SAT para el issuer ===
// Override seguro: si el caller inyecta credenciales desencriptadas vía env,
// usarlas en lugar de leer paths/password de la DB (por cifrado at-rest).
$overrideCer = getenv('SAT_FIEL_CER_PATH') ?: '';
$overrideKey = getenv('SAT_FIEL_KEY_PATH') ?: '';
$overridePass = getenv('SAT_FIEL_PASSWORD') ?: '';

if ($overrideCer && $overrideKey) {
    $cerPath = $overrideCer;
    $keyPath = $overrideKey;
    $pass = $overridePass;
} else {
    $stmt = $pdo->prepare(
        'SELECT fiel_cer_path, fiel_key_path, fiel_key_password
         FROM sat_credentials
         WHERE issuer_id = :issuer_id
         LIMIT 1'
    );
    $stmt->execute([':issuer_id' => $issuerId]);
    $cred = $stmt->fetch(PDO::FETCH_ASSOC);

    if (! $cred) {
        fwrite(STDERR, "No hay sat_credentials para issuer_id={$issuerId}\n");
        exit(1);
    }

    $cerPath = $baseDir . '/' . ltrim((string)$cred['fiel_cer_path'], '/');
    $keyPath = $baseDir . '/' . ltrim((string)$cred['fiel_key_path'], '/');
    $pass = (string)$cred['fiel_key_password'];
}

if (! file_exists($cerPath)) { fwrite(STDERR, "No existe CER: {$cerPath}\n"); exit(1); }
if (! file_exists($keyPath)) { fwrite(STDERR, "No existe KEY: {$keyPath}\n"); exit(1); }

// === 2) Crear servicio SAT (FIEL + Guzzle) ===
$fiel = Fiel::create(
    file_get_contents($cerPath),
    file_get_contents($keyPath),
    $pass
);

$requestBuilder = new FielRequestBuilder($fiel);
$guzzleClient = new GuzzleClient(['timeout' => 90, 'connect_timeout' => 30]);
$webClient = new GuzzleWebClient($guzzleClient);
$service = new Service($requestBuilder, $webClient);

// issued/received
$downloadType = ($direction === 'issued') ? DownloadType::issued() : DownloadType::received();

// === Helper: calcular ventana ===
$computeWindow = function (bool $forceReset) use ($tz, $backfillDays, $windowHours, $getState, $month): array {
    $now = new DateTimeImmutable('now', $tz);

    // Modo mensual: del 1er día del mes 00:00:00 al 1er día del siguiente mes 00:00:00
    if (null !== $month) {
        [$y, $m] = explode('-', $month, 2);
        $from = new DateTimeImmutable(sprintf('%04d-%02d-01 00:00:00', (int)$y, (int)$m), $tz);
        $to = $from->modify('first day of next month');
        if ($to > $now) $to = $now;
        return ['MONTH', $from, $to, $now];
    }

    if ($forceReset) {
        $from = $now->sub(new DateInterval("P{$backfillDays}D"));
        $mode = 'RESET';
    } else {
        $state = $getState();
        if (! empty($state['last_sync_to'])) {
            $from = new DateTimeImmutable((string) $state['last_sync_to'], $tz);
            $mode = 'INCREMENTAL';
        } else {
            $from = $now->sub(new DateInterval("P{$backfillDays}D"));
            $mode = 'BACKFILL';
        }
    }

    $to = $from->add(new DateInterval("PT{$windowHours}H"));
    if ($to > $now) $to = $now;

    return [$mode, $from, $to, $now];
};

// === Preparar statements DB ===
// (removed $findNeedsXml and $upsertMinimal as per instructions)

// === Ejecutar una ventana ===
$runOneWindow = function (DateTimeImmutable $from, DateTimeImmutable $to) use (
    $service, $downloadType, $direction, $issuerId, $pdo, $xmlBase,
    $logJob, $setState
): bool {
    fwrite(STDOUT, "XML window: {$from->format('Y-m-d H:i:s')} -> {$to->format('Y-m-d H:i:s')}\n");
    fwrite(STDOUT, "RequestType=XML(CFDI) | DownloadType=" . ($direction === 'issued' ? 'issued' : 'received') . "\n");

    $period = DateTimePeriod::createFromValues($from, $to);

    $params = QueryParameters::create($period)
        ->withDownloadType($downloadType)
        // IMPORTANT: Para obtener paquetes (ZIP) con XML CFDI, el RequestType debe ser XML ("CFDI" en el SAT)
        ->withRequestType(\PhpCfdi\SatWsDescargaMasiva\Shared\RequestType::xml());

    // Para received, el SAT exige status Vigente (no permite Cancelados ni Todos)
    if ($direction === 'received') {
        $params = $params->withDocumentStatus(DocumentStatus::active());
    }

    // Validación (si algo está mal, lo imprimimos antes de llamar al SAT)
    $validationErrors = $params->validate();
    if (! empty($validationErrors)) {
        $msg = "QueryParameters inválidos: " . implode(' | ', $validationErrors);
        fwrite(STDERR, $msg . "\n");
        $logJob('error', $from, $to, $msg);
        return false;
    }

    // Para que el SAT genere paquetes, pedimos Vigentes y Cancelados.
    // IMPORTANTE: Para "received" el SAT NO permite Cancelados, solo Vigentes.
    $statuses = ($direction === 'received')
        ? [DocumentStatus::active()]
        : [DocumentStatus::active(), DocumentStatus::cancelled()];

    $existsReq = $pdo->prepare(
        "SELECT COUNT(*) AS c
         FROM sat_requests
         WHERE issuer_id = :issuer_id
           AND direction = :direction
           AND window_from = :from
           AND window_to = :to"
    );

    $fromStr = $from->format('Y-m-d H:i:s');
    $toStr   = $to->format('Y-m-d H:i:s');

    $existsReq->execute([
        ':issuer_id' => $issuerId,
        ':direction' => $direction,
        ':from' => $fromStr,
        ':to' => $toStr,
    ]);
    $already = (int) (($existsReq->fetch(PDO::FETCH_ASSOC)['c'] ?? 0));
    if ($already > 0) {
        fwrite(STDOUT, "Ya existen sat_requests para esta ventana. Avanzando checkpoint y saliendo OK.\n");
        $logJob('queued', $from, $to, null);
        $setState($from, $to);
        return true;
    }

    $stmtInsertReq = $pdo->prepare(
        "INSERT INTO sat_requests (issuer_id, direction, request_id, window_from, window_to, status)
         VALUES (:issuer_id, :direction, :request_id, :from, :to, 'queued')"
    );

    $anyAccepted = false;

    foreach ($statuses as $st) {
        $label = method_exists($st, 'value') ? (string) $st->value() : get_class($st);
        fwrite(STDOUT, "DocumentStatus=" . $label . "\n");

        $p = $params->withDocumentStatus($st);

        $query = $service->query($p);
        if (! $query->getStatus()->isAccepted()) {
            $msg = "Query falló (status={$label}): " . $query->getStatus()->getMessage();
            fwrite(STDERR, $msg . "\n");
            // no abortamos; intentamos el otro estatus
            continue;
        }

        $anyAccepted = true;
        $requestId = $query->getRequestId();
        fwrite(STDOUT, "Solicitud SAT registrada: {$requestId}\n");

        $stmtInsertReq->execute([
            ':issuer_id' => $issuerId,
            ':direction' => $direction,
            ':request_id' => $requestId,
            ':from' => $fromStr,
            ':to' => $toStr,
        ]);

        fwrite(STDOUT, "Request guardado para procesamiento posterior.\n");
    }

    if (! $anyAccepted) {
        $msg = "Ninguna query fue aceptada por el SAT (active/cancelled).";
        fwrite(STDERR, $msg . "\n");
        $logJob('error', $from, $to, $msg);
        return false;
    }

    $logJob('queued', $from, $to, null);
    $setState($from, $to);
    return true;
};

// === Loop de ventanas ===
fwrite(
    STDOUT,
    "Modo CLI XML: "
    . (null !== $month ? "month={$month} | " : "")
    . "window={$windowHours}h | backfill={$backfillDays}d"
    . ($reset ? " | reset" : "")
    . ($loop ? " | loop" : "")
    . " | max-windows={$maxWindows}\n"
);

$windowsRun = 0;

do {
    $effectiveReset = ($reset && $windowsRun === 0);
    [$mode, $from, $to, $now] = $computeWindow($effectiveReset);

    fwrite(STDOUT, "Modo: {$mode}\n");

    if ($from >= $now) {
        fwrite(STDOUT, "Ya está al día (from >= now). Saliendo.\n");
        exit(0);
    }

    $ok = $runOneWindow($from, $to);
    if (! $ok) exit(1);

    $windowsRun++;

    if (! $loop) break;
    if ($to >= $now) { fwrite(STDOUT, "Alcanzado NOW. Saliendo.\n"); break; }
    if ($windowsRun >= $maxWindows) { fwrite(STDOUT, "Alcanzado max-windows={$maxWindows}. Saliendo.\n"); break; }

    sleep(2);
} while (true);