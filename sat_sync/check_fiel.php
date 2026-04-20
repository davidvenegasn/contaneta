<?php
declare(strict_types=1);
/**
 * Comprueba que las credenciales FIEL (CER + KEY + contraseña) sean válidas
 * para cada issuer con sat_credentials. La FIEL debe ser e.firma (no CSD) y vigente.
 *
 * Uso: php sat_sync/check_fiel.php [issuer_id]
 *   Sin argumentos: comprueba todos los issuers en sat_credentials.
 *   Con issuer_id: solo ese issuer.
 * Sale 0 si todo OK, 1 si falta credencial, archivo o FIEL inválida/vencida.
 */

require __DIR__ . '/vendor/autoload.php';

use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\Fiel;

if (PHP_SAPI !== 'cli') {
    exit(1);
}

$filterIssuerId = isset($argv[1]) ? (int) $argv[1] : null;

$baseDir = realpath(__DIR__ . '/..');
if ($baseDir === false) {
    fwrite(STDERR, "No se pudo resolver la ruta base del proyecto.\n");
    exit(1);
}

$dbPath = getenv('APP_DB_PATH') ?: ($baseDir . '/invoicing.db');
$dbPath = strpos($dbPath, '/') === 0 ? $dbPath : $baseDir . '/' . ltrim($dbPath, '/');
if (!file_exists($dbPath)) {
    fwrite(STDERR, "No existe la base de datos en: {$dbPath}\n");
    exit(1);
}

$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

$sql = 'SELECT sc.issuer_id, sc.fiel_cer_path, sc.fiel_key_path, sc.fiel_key_password, i.rfc, i.razon_social
        FROM sat_credentials sc
        LEFT JOIN issuers i ON i.id = sc.issuer_id
        WHERE 1=1';
$params = [];
if ($filterIssuerId !== null) {
    $sql .= ' AND sc.issuer_id = :issuer_id';
    $params[':issuer_id'] = $filterIssuerId;
}
$sql .= ' ORDER BY sc.issuer_id';

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

if (empty($rows)) {
    fwrite(STDERR, "No hay registros en sat_credentials" . ($filterIssuerId !== null ? " para issuer_id={$filterIssuerId}" : '') . ".\n");
    exit(1);
}

$allOk = true;
foreach ($rows as $cred) {
    $issuerId = (int) $cred['issuer_id'];
    $rfc = $cred['rfc'] ?? '';
    $label = $rfc ? "{$rfc} (issuer_id={$issuerId})" : "issuer_id={$issuerId}";

    // Override seguro: el caller puede inyectar credenciales desencriptadas vía env
    // (SAT_FIEL_CER_PATH, SAT_FIEL_KEY_PATH, SAT_FIEL_PASSWORD). Útil cuando están cifradas at-rest.
    $overrideCer = getenv('SAT_FIEL_CER_PATH') ?: '';
    $overrideKey = getenv('SAT_FIEL_KEY_PATH') ?: '';
    $overridePass = getenv('SAT_FIEL_PASSWORD') ?: '';
    $useOverride = ($filterIssuerId !== null && $issuerId === (int) $filterIssuerId && $overrideCer && $overrideKey);

    $cerPath = $useOverride ? $overrideCer : ($baseDir . '/' . ltrim((string) $cred['fiel_cer_path'], '/'));
    $keyPath = $useOverride ? $overrideKey : ($baseDir . '/' . ltrim((string) $cred['fiel_key_path'], '/'));
    $pass = $useOverride ? $overridePass : (string) $cred['fiel_key_password'];

    if (!file_exists($cerPath)) {
        fwrite(STDERR, "[{$label}] No existe archivo CER: {$cerPath}\n");
        $allOk = false;
        continue;
    }
    if (!file_exists($keyPath)) {
        fwrite(STDERR, "[{$label}] No existe archivo KEY: {$keyPath}\n");
        $allOk = false;
        continue;
    }
    if ($pass === '' || strpos($pass, 'CAMBIAR') === 0) {
        fwrite(STDERR, "[{$label}] Contraseña FIEL no configurada (o sigue siendo placeholder). Actualiza sat_credentials.fiel_key_password.\n");
        $allOk = false;
        continue;
    }

    try {
        $fiel = Fiel::create(
            file_get_contents($cerPath),
            file_get_contents($keyPath),
            $pass
        );
    } catch (Throwable $e) {
        $msg = $e->getMessage();
        if (strpos($msg, 'bad decrypt') !== false || strpos($msg, 'Cannot open private key') !== false) {
            $msg = 'La contraseña de la clave privada (.key) no es correcta. Verifica que sea exactamente la que te entregó el SAT al emitir tu e.firma (FIEL), sin espacios al inicio o final. Si acabas de subir los archivos, revisa el campo «Contraseña de la clave FIEL».';
        }
        fwrite(STDERR, "[{$label}] Error al crear FIEL: " . $msg . "\n");
        $allOk = false;
        continue;
    }

    if (!$fiel->isValid()) {
        fwrite(STDERR, "[{$label}] FIEL inválida o vencida (debe ser e.firma vigente, no CSD).\n");
        $allOk = false;
        continue;
    }

    // Extract RFC and legal name from the certificate
    $certRfc = '';
    $certName = '';
    try {
        $credential = PhpCfdi\Credentials\Credential::openFiles($cerPath, $keyPath, $pass);
        $certRfc = trim($credential->rfc());
        $certName = trim($credential->certificate()->legalName());
    } catch (Throwable $e) {
        // Non-fatal: extraction is best-effort
    }

    echo "OK FIEL: {$label}\n";
    if ($certRfc !== '') {
        echo "CERT_RFC={$certRfc}\n";
    }
    if ($certName !== '') {
        echo "CERT_NAME={$certName}\n";
    }
}

if (!$allOk) {
    fwrite(STDERR, "\nCorrige los errores antes de ejecutar la descarga (sync/verify).\n");
    exit(1);
}

echo "\nTodas las FIEL están listas. Puedes ejecutar la descarga (ej. ./sat_sync/download_all_xml_now.sh).\n";
exit(0);
