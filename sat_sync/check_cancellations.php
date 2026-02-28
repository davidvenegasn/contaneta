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
 * Verifica y actualiza estados de cancelación de facturas.
 * Consulta el SAT para facturas que estaban vigentes y pueden haberse cancelado.
 *
 * Uso:
 *   php sat_sync/check_cancellations.php <issuer_id> [--days=30] [--direction=issued|received]
 *
 * Opciones:
 *   --days=<n>        Días hacia atrás para verificar (default 30)
 *   --direction=<dir>  issued|received (default: ambos)
 */

$issuerId = (int)($argv[1] ?? 0);
if ($issuerId <= 0) {
    fwrite(STDERR, "Uso: php sat_sync/check_cancellations.php <issuer_id> [--days=30] [--direction=issued|received]\n");
    exit(1);
}

$days = 30;
$directionFilter = null;

foreach ($argv as $arg) {
    if (str_starts_with($arg, '--days=')) {
        $days = max(1, min(365, (int) substr($arg, strlen('--days='))));
        continue;
    }
    if (str_starts_with($arg, '--direction=')) {
        $directionFilter = substr($arg, strlen('--direction='));
        if (! in_array($directionFilter, ['issued', 'received'], true)) {
            $directionFilter = null;
        }
        continue;
    }
}

// === Paths ===
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

// === DB ===
$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);
$pdo->exec('PRAGMA foreign_keys = ON;');
$pdo->exec("PRAGMA busy_timeout = 5000;");
$pdo->exec("PRAGMA journal_mode = WAL;");

$tz = new DateTimeZone('America/Mexico_City');

// === Obtener credenciales ===
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

// === Crear servicio SAT ===
$fiel = Fiel::create(
    file_get_contents($cerPath),
    file_get_contents($keyPath),
    $pass
);

$requestBuilder = new FielRequestBuilder($fiel);
$guzzleClient = new GuzzleClient(['timeout' => 90, 'connect_timeout' => 30]);
$webClient = new GuzzleWebClient($guzzleClient);
$service = new Service($requestBuilder, $webClient);

// === Obtener facturas vigentes recientes ===
$now = new DateTimeImmutable('now', $tz);
$from = $now->sub(new DateInterval("P{$days}D"));

$where = [
    "issuer_id = :issuer_id",
    "status IN ('V', 'Vigente', '1')",
    "fecha_emision >= :from_date"
];
$params = [
    ':issuer_id' => $issuerId,
    ':from_date' => $from->format('Y-m-d'),
];

if ($directionFilter) {
    $where[] = "direction = :direction";
    $params[':direction'] = $directionFilter;
}

$sql = "
    SELECT uuid, direction, status, fecha_emision
    FROM sat_cfdi
    WHERE " . implode(' AND ', $where) . "
    ORDER BY fecha_emision DESC
    LIMIT 500
";

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

if (empty($rows)) {
    fwrite(STDOUT, "No hay facturas vigentes recientes para verificar.\n");
    exit(0);
}

fwrite(STDOUT, "Verificando " . count($rows) . " facturas vigentes desde {$from->format('Y-m-d')}...\n");

// === Agrupar por dirección ===
$byDirection = [];
foreach ($rows as $row) {
    $dir = (string) $row['direction'];
    if (! isset($byDirection[$dir])) {
        $byDirection[$dir] = [];
    }
    $byDirection[$dir][] = $row;
}

$updateStmt = $pdo->prepare("
    UPDATE sat_cfdi
    SET status = :status, updated_at = datetime('now')
    WHERE issuer_id = :issuer_id AND direction = :direction AND uuid = :uuid
");

$checked = 0;
$cancelled = 0;

foreach ($byDirection as $direction => $cfdis) {
    $downloadType = ($direction === 'issued') ? DownloadType::issued() : DownloadType::received();

    // Consultar solo cancelados en el mismo periodo
    $period = DateTimePeriod::createFromValues($from, $now);

    $params = QueryParameters::create($period)
        ->withDownloadType($downloadType)
        ->withDocumentStatus(DocumentStatus::cancelled())
        ->withRequestType(\PhpCfdi\SatWsDescargaMasiva\Shared\RequestType::metadata());

    $query = $service->query($params);
    if (! $query->getStatus()->isAccepted()) {
        fwrite(STDERR, "Query falló para {$direction}: " . $query->getStatus()->getMessage() . "\n");
        continue;
    }

    $requestId = $query->getRequestId();
    fwrite(STDOUT, "Request ID para {$direction}: {$requestId}\n");

    // Esperar a que esté listo
    $maxTries = 12;
    $packagesIds = [];

    for ($i = 0; $i < $maxTries; $i++) {
        sleep(10);
        $verify = $service->verify($requestId);

        if (! $verify->getStatus()->isAccepted()) {
            fwrite(STDERR, "Verify falló: " . $verify->getStatus()->getMessage() . "\n");
            break;
        }

        if (! $verify->getCodeRequest()->isAccepted()) {
            $msg = (string)$verify->getCodeRequest()->getMessage();
            if (
                stripos($msg, 'No se encontró') !== false
                || stripos($msg, 'no generó paquetes') !== false
            ) {
                fwrite(STDOUT, "Sin facturas canceladas en el periodo.\n");
                break;
            }
            fwrite(STDERR, "Solicitud rechazada: {$msg}\n");
            break;
        }

        if ($verify->getStatusRequest()->isFinished()) {
            $packagesIds = $verify->getPackagesIds();
            break;
        }
    }

    if (empty($packagesIds)) {
        continue;
    }

    // Descargar metadata y comparar UUIDs
    $cancelledUuids = [];

    foreach ($packagesIds as $packageId) {
        $download = $service->download($packageId);
        if (! $download->getStatus()->isAccepted()) {
            continue;
        }

        $zipPath = sys_get_temp_dir() . "/{$packageId}.zip";
        file_put_contents($zipPath, $download->getPackageContent());

        $reader = \PhpCfdi\SatWsDescargaMasiva\PackageReader\MetadataPackageReader::createFromFile($zipPath);

        foreach ($reader->metadata() as $uuid => $m) {
            $cancelledUuids[strtolower((string)$m->uuid)] = (string)$m->estado;
        }

        @unlink($zipPath);
    }

    // Actualizar estados
    foreach ($cfdis as $cfdi) {
        $uuid = strtolower((string) $cfdi['uuid']);
        $checked++;

        if (isset($cancelledUuids[$uuid])) {
            $updateStmt->execute([
                ':issuer_id' => $issuerId,
                ':direction' => $direction,
                ':uuid' => $cfdi['uuid'],
                ':status' => 'Cancelado',
            ]);
            $cancelled++;
            fwrite(STDOUT, "  ✅ Cancelada: {$cfdi['uuid']}\n");
        }
    }
}

fwrite(STDOUT, "\n✅ Verificadas: {$checked} | ❌ Canceladas encontradas: {$cancelled}\n");
exit(0);
