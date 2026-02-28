<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use PhpCfdi\SatWsDescargaMasiva\PackageReader\MetadataPackageReader;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\Fiel;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\FielRequestBuilder;
use PhpCfdi\SatWsDescargaMasiva\Service;
use PhpCfdi\SatWsDescargaMasiva\Shared\DateTimePeriod;
use PhpCfdi\SatWsDescargaMasiva\Shared\DownloadType;
use PhpCfdi\SatWsDescargaMasiva\Shared\RequestType;
use PhpCfdi\SatWsDescargaMasiva\Services\Query\QueryParameters;
use GuzzleHttp\Client as GuzzleClient;
use PhpCfdi\SatWsDescargaMasiva\WebClient\GuzzleWebClient;

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Este script solo se ejecuta por CLI.\n");
    exit(1);
}

/**
 * Uso:
 *   php sat_sync/sync.php <issuer_id> <issued|received> [--backfill=<dias>] [--reset] [--window=<horas>] [--loop] [--max-windows=<n>]
 *
 * Opciones:
 *   --backfill=<dias>     (default 7) Si NO hay checkpoint (o si usas --reset), inicia desde hoy - <dias>.
 *                         Ejemplo: --backfill=60
 *   --reset               Ignora el checkpoint guardado y vuelve a iniciar desde backfill.
 *   --window=<horas>      (default 6) Tamaño de ventana en horas. Permitimos hasta 720h (30 días).
 *                         Ejemplo: --window=92
 *   --loop                Procesa ventanas consecutivas hasta alcanzar "ahora" (o hasta max-windows).
 *   --max-windows=<n>     (default 200) Límite de ventanas por corrida para no quedarte atorado infinito.
 *
 * Ejemplos:
 *   php sat_sync/sync.php 1 issued
 *   php sat_sync/sync.php 1 received
 *   php sat_sync/sync.php 1 issued --backfill=60 --reset --window=92 --loop
 *   php sat_sync/sync.php 1 received --backfill=60 --reset --window=92 --loop
 */

$issuerId = (int)($argv[1] ?? 0);
$direction = (string)($argv[2] ?? 'issued'); // issued|received

if ($issuerId <= 0 || ! in_array($direction, ['issued', 'received'], true)) {
    fwrite(STDERR, "Uso: php sat_sync/sync.php <issuer_id> <issued|received>\n");
    exit(1);
}

// === Opciones CLI ===
$backfillDays = 7;
$reset = false;
$windowHours = 6;
$loop = false;
$maxWindows = 200;

for ($i = 3; $i < $argc; $i++) {
    $arg = (string)$argv[$i];

    if ($arg === '--reset') {
        $reset = true;
        continue;
    }
    if ($arg === '--loop') {
        $loop = true;
        continue;
    }

    if (str_starts_with($arg, '--backfill=')) {
        $val = (int)substr($arg, strlen('--backfill='));
        if ($val >= 1 && $val <= 3650) { // hasta 10 años por si acaso
            $backfillDays = $val;
        }
        continue;
    }

    if (str_starts_with($arg, '--window=')) {
        $val = (int)substr($arg, strlen('--window='));
        // Permitimos ventanas grandes (ej. 92h). Límite de seguridad: 720h (30 días).
        if ($val >= 1 && $val <= 720) {
            $windowHours = $val;
        }
        continue;
    }

    if (str_starts_with($arg, '--max-windows=')) {
        $val = (int)substr($arg, strlen('--max-windows='));
        if ($val >= 1 && $val <= 10000) {
            $maxWindows = $val;
        }
        continue;
    }
}

// === Paths ===
$baseDir = realpath(__DIR__ . '/..'); // raíz del proyecto
if (false === $baseDir) {
    fwrite(STDERR, "No se pudo resolver la ruta base del proyecto.\n");
    exit(1);
}

$dbPath = getenv('APP_DB_PATH') ?: ($baseDir . '/invoicing.db');
$dbPath = strpos($dbPath, '/') === 0 ? $dbPath : $baseDir . '/' . ltrim($dbPath, '/');
if (!file_exists($dbPath)) {
    fwrite(STDERR, "No existe la base de datos en: {$dbPath}\n");
    exit(1);
}

// === DB ===
$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec('PRAGMA foreign_keys = ON;');

$tz = new DateTimeZone('America/Mexico_City');

// === Helper: guardar checkpoint ===
$saveCheckpoint = function (DateTimeImmutable $from, DateTimeImmutable $to) use ($pdo, $issuerId, $direction): void {
    $checkpoint = $pdo->prepare(
        'INSERT INTO sat_sync_state(issuer_id, direction, last_sync_from, last_sync_to, last_run_at)
         VALUES(:issuer_id, :direction, :from, :to, datetime(\'now\'))
         ON CONFLICT(issuer_id, direction) DO UPDATE SET
            last_sync_from=excluded.last_sync_from,
            last_sync_to=excluded.last_sync_to,
            last_run_at=datetime(\'now\')'
    );

    $checkpoint->execute([
        ':issuer_id' => $issuerId,
        ':direction' => $direction,
        ':from' => $from->format('Y-m-d H:i:s'),
        ':to' => $to->format('Y-m-d H:i:s'),
    ]);
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

if (! file_exists($cerPath)) {
    fwrite(STDERR, "No existe CER: {$cerPath}\n");
    exit(1);
}
if (! file_exists($keyPath)) {
    fwrite(STDERR, "No existe KEY: {$keyPath}\n");
    exit(1);
}

// === 2) Crear servicio SAT (FIEL + Guzzle) ===
$fiel = Fiel::create(
    file_get_contents($cerPath),
    file_get_contents($keyPath),
    $pass
);

if (! $fiel->isValid()) {
    fwrite(STDERR, "FIEL inválida o vencida para issuer_id={$issuerId}\n");
    exit(1);
}

$guzzleClient = new GuzzleClient(['timeout' => 90, 'connect_timeout' => 30]);
$webClient = new GuzzleWebClient($guzzleClient);
$requestBuilder = new FielRequestBuilder($fiel);
$service = new Service($requestBuilder, $webClient);

// === Upsert statement (se reutiliza en cada ventana) ===
$upsert = $pdo->prepare(
    'INSERT INTO sat_cfdi (
        issuer_id, direction, uuid, fecha_emision, rfc_emisor, rfc_receptor, total, moneda, status, metadata_json, updated_at
     ) VALUES (
        :issuer_id, :direction, :uuid, :fecha_emision, :rfc_emisor, :rfc_receptor, :total, :moneda, :status, :metadata_json, datetime(\'now\')
     )
     ON CONFLICT(issuer_id, direction, uuid) DO UPDATE SET
        fecha_emision=excluded.fecha_emision,
        rfc_emisor=excluded.rfc_emisor,
        rfc_receptor=excluded.rfc_receptor,
        total=excluded.total,
        moneda=excluded.moneda,
        status=excluded.status,
        metadata_json=excluded.metadata_json,
        updated_at=datetime(\'now\')'
);

$getStateLastTo = function () use ($pdo, $issuerId, $direction): ?string {
    $st = $pdo->prepare(
        'SELECT last_sync_to
         FROM sat_sync_state
         WHERE issuer_id = :issuer_id AND direction = :direction
         LIMIT 1'
    );
    $st->execute([':issuer_id' => $issuerId, ':direction' => $direction]);
    $row = $st->fetch(PDO::FETCH_ASSOC);
    if (! $row || empty($row['last_sync_to'])) {
        return null;
    }
    return (string)$row['last_sync_to'];
};

$computeWindow = function (bool $effectiveReset) use ($getStateLastTo, $tz, $backfillDays, $windowHours): array {
    $now = new DateTimeImmutable('now', $tz);

    $lastTo = (!$effectiveReset) ? $getStateLastTo() : null;

    if ($lastTo) {
        $from = new DateTimeImmutable($lastTo, $tz);
        $mode = 'incremental';
    } else {
        $from = $now->sub(new DateInterval('P' . $backfillDays . 'D'));
        $mode = $effectiveReset ? 'reset' : 'first_run';
    }

    $to = $from->add(new DateInterval('PT' . $windowHours . 'H'));
    if ($to > $now) {
        $to = $now;
    }

    // asegurar mínimo 2 segundos
    if (($to->getTimestamp() - $from->getTimestamp()) < 2) {
        $to = $from->add(new DateInterval('PT2S'));
    }

    return [$mode, $from, $to, $now];
};

$runOneWindow = function (DateTimeImmutable $from, DateTimeImmutable $to) use (
    $service, $direction, $issuerId, $saveCheckpoint, $upsert
): bool {
    fwrite(STDOUT, "SYNC issuer_id={$issuerId} direction={$direction}\n");
    fwrite(STDOUT, "Periodo: {$from->format('Y-m-d H:i:s')} -> {$to->format('Y-m-d H:i:s')}\n");

    $downloadType = ($direction === 'issued') ? DownloadType::issued() : DownloadType::received();

    $period = DateTimePeriod::createFromValues(
        $from->format('Y-m-d H:i:s'),
        $to->format('Y-m-d H:i:s')
    );

    $params = QueryParameters::create($period)
        ->withDownloadType($downloadType)
        ->withRequestType(RequestType::metadata());

    $query = $service->query($params);
    if (! $query->getStatus()->isAccepted()) {
        fwrite(STDERR, "Query falló: " . $query->getStatus()->getMessage() . "\n");
        return false;
    }

    $requestId = $query->getRequestId();
    fwrite(STDOUT, "Solicitud SAT: {$requestId}\n");

    $maxTries = 12; // 12*10s = 2 minutos
    $packagesIds = [];

    for ($i = 0; $i < $maxTries; $i++) {
        sleep(10);

        $verify = $service->verify($requestId);

        if (! $verify->getStatus()->isAccepted()) {
            fwrite(STDERR, "Verify falló: " . $verify->getStatus()->getMessage() . "\n");
            return false;
        }

        if (! $verify->getCodeRequest()->isAccepted()) {
            $msg = (string)$verify->getCodeRequest()->getMessage();

            if (
                stripos($msg, 'No se encontró la información') !== false
                || stripos($msg, 'falta de información') !== false
                || stripos($msg, 'no generó paquetes') !== false
                || stripos($msg, 'no generó paquetes') !== false
            ) {
                fwrite(STDOUT, "Sin información en el periodo. Guardando checkpoint y avanzando.\n");
                $saveCheckpoint($from, $to);
                fwrite(STDOUT, "OK. Checkpoint guardado (sin CFDI).\n");
                return true;
            }

            fwrite(STDERR, "Solicitud rechazada: {$msg}\n");
            return false;
        }

        $statusRequest = $verify->getStatusRequest();

        if ($statusRequest->isFinished()) {
            $packagesIds = $verify->getPackagesIds();
            fwrite(STDOUT, "Listo. Paquetes: " . $verify->countPackages() . "\n");
            break;
        }

        $n = $i + 1;
        fwrite(STDOUT, "En proceso... ({$n}/{$maxTries})\n");
    }

    if ([] === $packagesIds) {
        fwrite(STDOUT, "Sin paquetes para este periodo. Guardando checkpoint y avanzando.\n");
        $saveCheckpoint($from, $to);
        fwrite(STDOUT, "OK. Checkpoint guardado (sin paquetes).\n");
        return true;
    }

    foreach ($packagesIds as $packageId) {
        $download = $service->download($packageId);

        if (! $download->getStatus()->isAccepted()) {
            fwrite(STDERR, "No descargó paquete {$packageId}: " . $download->getStatus()->getMessage() . "\n");
            continue;
        }

        $zipPath = sys_get_temp_dir() . "/{$packageId}.zip";
        file_put_contents($zipPath, $download->getPackageContent());

        $reader = MetadataPackageReader::createFromFile($zipPath);

        $count = 0;
        foreach ($reader->metadata() as $uuid => $m) {
            $uuidNorm = strtolower((string) $m->uuid);
            $upsert->execute([
                ':issuer_id' => $issuerId,
                ':direction' => $direction,
                ':uuid' => $uuidNorm,
                ':fecha_emision' => (string)($m->fechaEmision ?? ''),
                ':rfc_emisor' => (string)($m->rfcEmisor ?? ''),
                ':rfc_receptor' => (string)($m->rfcReceptor ?? ''),
                ':total' => (float)($m->total ?? 0),
                ':moneda' => (string)($m->moneda ?? 'MXN'),
                ':status' => (string)($m->estatus ?? ''),
                ':metadata_json' => json_encode($m, JSON_UNESCAPED_UNICODE),
            ]);
            $count++;
        }

        @unlink($zipPath);
        fwrite(STDOUT, "Paquete {$packageId} procesado. Registros: {$count}\n");
    }

    $saveCheckpoint($from, $to);
    fwrite(STDOUT, "OK. Checkpoint guardado.\n");

    return true;
};

// === Ejecutar ===
fwrite(
    STDOUT,
    "Modo CLI: window={$windowHours}h | backfill={$backfillDays}d"
    . ($reset ? " | reset" : "")
    . ($loop ? " | loop" : "")
    . " | max-windows={$maxWindows}\n"
);

$windowsRun = 0;

do {
    $effectiveReset = ($reset && $windowsRun === 0);

    [$mode, $from, $to, $now] = $computeWindow($effectiveReset);

    fwrite(STDOUT, "Modo: {$mode}\n");

    // si ya estamos “al día”, salimos
    if ($from >= $now) {
        fwrite(STDOUT, "Ya está al día (from >= now). Saliendo.\n");
        exit(0);
    }

    $ok = $runOneWindow($from, $to);
    if (! $ok) {
        exit(1);
    }

    $windowsRun++;

    // condición de salida si no loop
    if (! $loop) {
        break;
    }

    // si ya alcanzamos "now" (o casi), salimos
    if ($to >= $now) {
        fwrite(STDOUT, "Alcanzado NOW. Saliendo.\n");
        break;
    }

    // límite anti-infinito
    if ($windowsRun >= $maxWindows) {
        fwrite(STDOUT, "Alcanzado max-windows={$maxWindows}. Saliendo.\n");
        break;
    }

    // mini pausa para no pegarle tan duro al SAT
    sleep(2);

} while (true);

exit(0);