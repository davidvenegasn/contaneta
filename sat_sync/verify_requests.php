<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use GuzzleHttp\Client as GuzzleClient;
use PhpCfdi\SatWsDescargaMasiva\PackageReader\CfdiPackageReader;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\Fiel;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\FielRequestBuilder;
use PhpCfdi\SatWsDescargaMasiva\Service;
use PhpCfdi\SatWsDescargaMasiva\WebClient\GuzzleWebClient;

if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Este script solo se ejecuta por CLI.\n");
    exit(1);
}

/**
 * Worker: verifica requests en tabla sat_requests, y cuando estén finished,
 * descarga paquetes ZIP, extrae XML y los guarda en storage/xml,
 * actualizando sat_cfdi.xml_path + hashes.
 *
 * Uso:
 *   php sat_sync/verify_requests.php [--issuer=1] [--direction=issued|received] [--limit=10] [--loop] [--sleep=30]
 */

$issuerFilter = null;
$directionFilter = null;
$limit = 10;
$loop = false;
$sleepSeconds = 30;

foreach ($argv as $arg) {
    if (str_starts_with($arg, '--issuer=')) {
        $issuerFilter = (int) substr($arg, strlen('--issuer='));
        continue;
    }
    if (str_starts_with($arg, '--direction=')) {
        $directionFilter = substr($arg, strlen('--direction='));
        if (! in_array($directionFilter, ['issued', 'received'], true)) {
            $directionFilter = null;
        }
        continue;
    }
    if (str_starts_with($arg, '--limit=')) {
        $limit = max(1, min(200, (int) substr($arg, strlen('--limit='))));
        continue;
    }
    if ($arg === '--loop') {
        $loop = true;
        continue;
    }
    if (str_starts_with($arg, '--sleep=')) {
        $sleepSeconds = max(5, min(600, (int) substr($arg, strlen('--sleep='))));
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

// SQLite concurrency settings (avoid "database is locked")
$pdo->exec("PRAGMA busy_timeout = 5000;");
$pdo->exec("PRAGMA journal_mode = WAL;");
$pdo->exec("PRAGMA synchronous = NORMAL;");

$tz = new DateTimeZone('America/Mexico_City');
$xmlBase = $baseDir . '/storage/xml';
@mkdir($xmlBase, 0775, true);

// === Statements ===
$getCred = $pdo->prepare(
    "SELECT fiel_cer_path, fiel_key_path, fiel_key_password
     FROM sat_credentials
     WHERE issuer_id = :issuer_id
     LIMIT 1"
);

$selectQueued = function () use ($pdo, $issuerFilter, $directionFilter, $limit) {
    // Procesamos queued, y verifying viejos (por si un worker murió)
    $where = "WHERE status = 'queued' OR (status = 'verifying' AND updated_at <= datetime('now','-60 seconds'))";
    $params = [];

    if (null !== $issuerFilter) {
        $where .= " AND issuer_id = :issuer_id";
        $params[':issuer_id'] = $issuerFilter;
    }
    if (null !== $directionFilter) {
        $where .= " AND direction = :direction";
        $params[':direction'] = $directionFilter;
    }

    $sql = "
      SELECT *
      FROM sat_requests
      {$where}
      ORDER BY
        CASE status WHEN 'queued' THEN 0 ELSE 1 END,
        updated_at ASC,
        id ASC
      LIMIT {$limit}
    ";

    $stmt = $pdo->prepare($sql);
    $stmt->execute($params);
    return $stmt->fetchAll(PDO::FETCH_ASSOC);
};

$markVerifying = $pdo->prepare(
    "UPDATE sat_requests
     SET status='verifying', updated_at=datetime('now')
     WHERE id=:id"
);

$incTries = $pdo->prepare(
    "UPDATE sat_requests
     SET tries=tries+1, updated_at=datetime('now')
     WHERE id=:id"
);

$markError = $pdo->prepare(
    "UPDATE sat_requests
     SET status='error', last_error=:err, updated_at=datetime('now')
     WHERE id=:id"
);

$markFinished = $pdo->prepare(
    "UPDATE sat_requests
     SET status='finished', last_error=NULL, updated_at=datetime('now')
     WHERE id=:id"
);

$upsertMinimal = $pdo->prepare(
    "INSERT INTO sat_cfdi(issuer_id, direction, uuid, xml_path, xml_sha256, xml_downloaded_at, xml_status, status, updated_at)
     VALUES(:issuer_id, :direction, :uuid, :xml_path, :sha, datetime('now'), 'downloaded', 'V', datetime('now'))
     ON CONFLICT(issuer_id, direction, uuid) DO UPDATE SET
       xml_path = excluded.xml_path,
       xml_sha256 = excluded.xml_sha256,
       xml_downloaded_at = excluded.xml_downloaded_at,
       xml_status = 'downloaded',
       status = COALESCE(NULLIF(TRIM(status), ''), 'V'),
       updated_at = datetime('now')"
);

// Búsqueda case-insensitive para evitar duplicados (metadata puede tener uuid en distinto caso que el XML)
$findNeedsXml = $pdo->prepare(
    "SELECT id, xml_path FROM sat_cfdi
     WHERE issuer_id=:issuer_id AND direction=:direction AND LOWER(TRIM(uuid))=LOWER(TRIM(:uuid))
     LIMIT 1"
);
$updateRowWithXml = $pdo->prepare(
    "UPDATE sat_cfdi SET
       xml_path=:xml_path, xml_sha256=:xml_sha256,
       xml_downloaded_at=datetime('now'), xml_status='downloaded',
       uuid=:uuid,
       status = COALESCE(NULLIF(TRIM(status), ''), 'V'),
       updated_at=datetime('now')
     WHERE id=:id"
);

// === Service cache per issuer ===
$serviceCache = [];

$getServiceForIssuer = function (int $issuerId) use ($getCred, $baseDir, &$serviceCache): Service {
    if (isset($serviceCache[$issuerId])) {
        return $serviceCache[$issuerId];
    }

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
        $getCred->execute([':issuer_id' => $issuerId]);
        $cred = $getCred->fetch(PDO::FETCH_ASSOC);
        if (! $cred) {
            throw new RuntimeException("No hay sat_credentials para issuer_id={$issuerId}");
        }

        $cerPath = $baseDir . '/' . ltrim((string) $cred['fiel_cer_path'], '/');
        $keyPath = $baseDir . '/' . ltrim((string) $cred['fiel_key_path'], '/');
        $pass = (string) $cred['fiel_key_password'];
    }

    if (! file_exists($cerPath)) {
        throw new RuntimeException("No existe CER: {$cerPath}");
    }
    if (! file_exists($keyPath)) {
        throw new RuntimeException("No existe KEY: {$keyPath}");
    }

    $fiel = Fiel::create(
        file_get_contents($cerPath),
        file_get_contents($keyPath),
        $pass
    );

    $requestBuilder = new FielRequestBuilder($fiel);
    // Timeout 90s para evitar que se quede colgado esperando al SAT
    $guzzleClient = new GuzzleClient(['timeout' => 90, 'connect_timeout' => 30]);
    $webClient = new GuzzleWebClient($guzzleClient);
    $service = new Service($requestBuilder, $webClient);

    $serviceCache[$issuerId] = $service;
    return $service;
};

$processOne = function (array $req) use (
    $pdo, $baseDir, $tz, $xmlBase,
    $markVerifying, $incTries, $markError, $markFinished,
    $getServiceForIssuer,
    $findNeedsXml, $updateRowWithXml, $upsertMinimal
): void {
    $id = (int) $req['id'];
    $issuerId = (int) $req['issuer_id'];
    $direction = (string) $req['direction'];
    $requestId = (string) $req['request_id'];
    $windowFrom = (string) $req['window_from'];

    fwrite(STDOUT, "Verifying sat_requests.id={$id} issuer={$issuerId} dir={$direction} request={$requestId}\n");

    // marcar verifying
    $markVerifying->execute([':id' => $id]);
    $incTries->execute([':id' => $id]);

    try {
        $service = $getServiceForIssuer($issuerId);
        $verify = $service->verify($requestId);

        fwrite(STDOUT, "SAT Status: " . (string) $verify->getStatus()->getMessage() . "\n");
        fwrite(STDOUT, "SAT CodeRequest: " . (string) $verify->getCodeRequest()->getMessage() . "\n");
        fwrite(STDOUT, "SAT Finished?: " . ($verify->getStatusRequest()->isFinished() ? 'YES' : 'NO') . "\n");

        if (! $verify->getStatus()->isAccepted()) {
            $err = "Verify status no aceptado: " . $verify->getStatus()->getMessage();
            fwrite(STDERR, $err . "\n");
            $markError->execute([':id' => $id, ':err' => $err]);
            return;
        }

        // Si el SAT indica sin información, marcamos finished
        if (! $verify->getCodeRequest()->isAccepted()) {
            $msg = (string) $verify->getCodeRequest()->getMessage();
            if (
                stripos($msg, 'No se encontró la información') !== false
                || stripos($msg, 'falta de información') !== false
                || stripos($msg, 'no gener') !== false
            ) {
                fwrite(STDOUT, "SAT: sin información / sin paquetes. Marcando finished.\n");
                $markFinished->execute([':id' => $id]);
                return;
            }

            $err = "Solicitud rechazada: {$msg}";
            fwrite(STDERR, $err . "\n");
            $markError->execute([':id' => $id, ':err' => $err]);
            return;
        }

        if (! $verify->getStatusRequest()->isFinished()) {
            $tries = (int) $req['tries'];
            if ($tries >= 30) {
                $err = "Stuck: SAT no termina (tries={$tries}). Re-generar request para esta ventana.";
                fwrite(STDERR, $err . "\n");
                $markError->execute([':id' => $id, ':err' => $err]);
                return;
            }

            fwrite(STDOUT, "SAT aún en proceso (no finished). Se reintentará luego.\n");
            return;
        }

        $packagesIds = $verify->getPackagesIds();
        fwrite(STDOUT, "Finished. PaquetesIds: " . count($packagesIds) . "\n");
        if (! empty($packagesIds)) {
            fwrite(STDOUT, "Package IDs: " . implode(', ', $packagesIds) . "\n");
        }

        if ([] === $packagesIds) {
            fwrite(STDOUT, "Finished pero sin paquetes. Marcando finished.\n");
            $markFinished->execute([':id' => $id]);
            return;
        }

        $saved = 0;
        $skipped = 0;

        foreach ($packagesIds as $packageId) {
            $download = $service->download($packageId);

            if (! $download->getStatus()->isAccepted()) {
                fwrite(STDERR, "No descargó paquete {$packageId}: " . $download->getStatus()->getMessage() . "\n");
                continue;
            }

            $zipPath = sys_get_temp_dir() . "/{$packageId}.zip";
            file_put_contents($zipPath, $download->getPackageContent());

            $reader = CfdiPackageReader::createFromFile($zipPath);

            foreach ($reader->cfdis() as $uuid => $content) {
                $uuid = strtolower((string) $uuid);

                $findNeedsXml->execute([
                    ':issuer_id' => $issuerId,
                    ':direction' => $direction,
                    ':uuid' => $uuid,
                ]);
                $row = $findNeedsXml->fetch(PDO::FETCH_ASSOC);

                if ($row && ! empty($row['xml_path'])) {
                    $skipped++;
                    continue;
                }

                $dt = new DateTimeImmutable($windowFrom, $tz);
                $yyyy = $dt->format('Y');
                $mm = $dt->format('m');

                $dirPath = "{$xmlBase}/{$issuerId}/{$direction}/{$yyyy}/{$mm}";
                @mkdir($dirPath, 0775, true);

                $filePath = "{$dirPath}/{$uuid}.xml";
                file_put_contents($filePath, $content);

                $sha = hash('sha256', $content);

                // Ruta relativa a la raíz del proyecto (para guardar en DB)
                $relative = ltrim(str_replace($baseDir . '/', '', $filePath), '/');

                if ($row && isset($row['id'])) {
                    // Ya existe fila (metadata); actualizar por id para no duplicar
                    $updateRowWithXml->execute([
                        ':id' => (int) $row['id'],
                        ':uuid' => $uuid,
                        ':xml_path' => $relative,
                        ':xml_sha256' => $sha,
                    ]);
                } else {
                    $upsertMinimal->execute([
                        ':issuer_id' => $issuerId,
                        ':direction' => $direction,
                        ':uuid' => $uuid,
                        ':xml_path' => $relative,
                        ':sha' => $sha,
                    ]);
                }

                $saved++;
            }

            @unlink($zipPath);
            fwrite(STDOUT, "Paquete {$packageId} procesado.\n");
        }

        fwrite(STDOUT, "XML guardados: {$saved} | ya existían: {$skipped}\n");

        $markFinished->execute([':id' => $id]);

    } catch (Throwable $e) {
        $err = "Exception: " . $e->getMessage();
        fwrite(STDERR, $err . "\n");
        $markError->execute([':id' => $id, ':err' => $err]);
    }
};

// === Main loop ===
do {
    $batch = $selectQueued();

    if (! $batch) {
        fwrite(STDOUT, "No hay sat_requests pendientes.\n");
        if (! $loop) {
            break;
        }
        sleep($sleepSeconds);
        continue;
    }

    foreach ($batch as $req) {
        $processOne($req);
    }

    if (! $loop) {
        break;
    }

    sleep($sleepSeconds);

} while (true);