<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';

use PDO;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\Fiel;
use PhpCfdi\SatWsDescargaMasiva\RequestBuilder\FielRequestBuilder\FielRequestBuilder;
use PhpCfdi\SatWsDescargaMasiva\Service;
use PhpCfdi\SatWsDescargaMasiva\WebClient\GuzzleWebClient;

if (PHP_SAPI !== 'cli') exit(1);

$requestId = $argv[1] ?? '';
$issuerId  = (int)($argv[2] ?? 1);

if (!$requestId) {
    fwrite(STDERR, "Uso: php sat_sync/debug_verify.php <request_id> [issuer_id]\n");
    exit(1);
}

$baseDir = realpath(__DIR__ . '/..');
$dbPath  = $baseDir . '/invoicing.db';

$pdo = new PDO('sqlite:' . $dbPath);
$pdo->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

$stmt = $pdo->prepare("SELECT fiel_cer_path, fiel_key_path, fiel_key_password FROM sat_credentials WHERE issuer_id=:id LIMIT 1");
$stmt->execute([':id' => $issuerId]);
$cred = $stmt->fetch(PDO::FETCH_ASSOC);
if (!$cred) { fwrite(STDERR, "No hay credenciales para issuer_id={$issuerId}\n"); exit(1); }

$cerPath = $baseDir . '/' . ltrim((string)$cred['fiel_cer_path'], '/');
$keyPath = $baseDir . '/' . ltrim((string)$cred['fiel_key_path'], '/');
$pass    = (string)$cred['fiel_key_password'];

$fiel = Fiel::create(file_get_contents($cerPath), file_get_contents($keyPath), $pass);
$service = new Service(new FielRequestBuilder($fiel), new GuzzleWebClient());

$verify = $service->verify($requestId);

echo "Status accepted?: " . ($verify->getStatus()->isAccepted() ? "YES" : "NO") . PHP_EOL;
echo "Status message: " . $verify->getStatus()->getMessage() . PHP_EOL;

echo "CodeRequest accepted?: " . ($verify->getCodeRequest()->isAccepted() ? "YES" : "NO") . PHP_EOL;
echo "CodeRequest message: " . $verify->getCodeRequest()->getMessage() . PHP_EOL;

echo "StatusRequest finished?: " . ($verify->getStatusRequest()->isFinished() ? "YES" : "NO") . PHP_EOL;
echo "Packages count: " . $verify->countPackages() . PHP_EOL;

$ids = $verify->getPackagesIds();
echo "Packages IDs: " . implode(", ", $ids) . PHP_EOL;