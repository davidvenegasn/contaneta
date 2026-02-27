<?php
declare(strict_types=1);

require __DIR__ . '/vendor/autoload.php';


if (PHP_SAPI !== 'cli') {
    fwrite(STDERR, "Este script solo se ejecuta por CLI.\n");
    exit(1);
}

/**
 * Parsea XML de CFDI descargados y extrae campos adicionales a sat_cfdi.
 *
 * Uso:
 *   php sat_sync/parse_xml.php [--issuer=1] [--direction=issued|received] [--limit=100] [--force]
 *
 * Opciones:
 *   --issuer=<id>      Filtrar por issuer_id
 *   --direction=<dir>  Filtrar por dirección (issued|received)
 *   --limit=<n>        Máximo de XML a procesar (default 100)
 *   --force            Re-parsear incluso si ya están parseados
 */

$issuerFilter = null;
$directionFilter = null;
$limit = 100;
$force = false;

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
        $limit = max(1, min(1000, (int) substr($arg, strlen('--limit='))));
        continue;
    }
    if ($arg === '--force') {
        $force = true;
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

// Comprobar si existe columna retenciones (para backfill de filas ya parseadas)
$hasRetencionesCol = false;
try {
    $chk = $pdo->query("SELECT retenciones FROM sat_cfdi LIMIT 1");
    if ($chk !== false) {
        $hasRetencionesCol = true;
    }
} catch (PDOException $e) {
    // Columna no existe, no hacer backfill
}

// === Seleccionar CFDI con XML pero sin parsear (o ya parseados sin retenciones, para backfill) ===
$where = ["xml_path IS NOT NULL", "xml_path != ''"];
$params = [];

if (! $force) {
    // Parsear: pendientes O ya parseados pero con retenciones NULL (backfill)
    $cond = "xml_status IS NULL OR xml_status = 'downloaded' OR xml_status = 'error'";
    if ($hasRetencionesCol) {
        $cond .= " OR (xml_status = 'parsed' AND retenciones IS NULL)";
    }
    $where[] = "(" . $cond . ")";
}

if (null !== $issuerFilter) {
    $where[] = "issuer_id = :issuer_id";
    $params[':issuer_id'] = $issuerFilter;
}
if (null !== $directionFilter) {
    $where[] = "direction = :direction";
    $params[':direction'] = $directionFilter;
}

$sql = "
    SELECT id, issuer_id, direction, uuid, xml_path
    FROM sat_cfdi
    WHERE " . implode(' AND ', $where) . "
    ORDER BY updated_at ASC
    LIMIT {$limit}
";

$stmt = $pdo->prepare($sql);
$stmt->execute($params);
$rows = $stmt->fetchAll(PDO::FETCH_ASSOC);

if (empty($rows)) {
    fwrite(STDOUT, "No hay XML pendientes de parsear.\n");
    exit(0);
}

fwrite(STDOUT, "Procesando " . count($rows) . " XML...\n");

// === Statement para actualizar ===
$updateStmt = $pdo->prepare("
    UPDATE sat_cfdi SET
        fecha_emision = COALESCE(:fecha_emision, fecha_emision),
        rfc_emisor = COALESCE(:rfc_emisor, rfc_emisor),
        nombre_emisor = COALESCE(:nombre_emisor, nombre_emisor),
        rfc_receptor = COALESCE(:rfc_receptor, rfc_receptor),
        nombre_receptor = COALESCE(:nombre_receptor, nombre_receptor),
        total = COALESCE(:total, total),
        moneda = COALESCE(:moneda, moneda),
        serie = :serie,
        folio = :folio,
        forma_pago = :forma_pago,
        metodo_pago = :metodo_pago,
        uso_cfdi = :uso_cfdi,
        subtotal = :subtotal,
        descuento = :descuento,
        impuestos = :impuestos,
        retenciones = :retenciones,
        lugar_expedicion = :lugar_expedicion,
        condiciones_pago = :condiciones_pago,
        tipo_comprobante = COALESCE(:tipo_comprobante, tipo_comprobante),
        concepto = :concepto,
        xml_status = :xml_status,
        status = COALESCE(NULLIF(TRIM(COALESCE(status, '')), ''), 'V'),
        parsed_at = datetime('now'),
        updated_at = datetime('now')
    WHERE id = :id
");

$parsed = 0;
$errors = 0;

foreach ($rows as $row) {
    $id = (int) $row['id'];
    $xmlPath = $baseDir . '/' . ltrim((string) $row['xml_path'], '/');

    if (! file_exists($xmlPath)) {
        fwrite(STDERR, "⚠️  XML no existe: {$xmlPath}\n");
        $updateStmt->execute([
            ':fecha_emision' => null,
            ':rfc_emisor' => null,
            ':nombre_emisor' => null,
            ':rfc_receptor' => null,
            ':nombre_receptor' => null,
            ':moneda' => null,
            ':id' => $id,
            ':serie' => null,
            ':folio' => null,
            ':forma_pago' => null,
            ':metodo_pago' => null,
            ':uso_cfdi' => null,
            ':subtotal' => null,
            ':descuento' => null,
            ':impuestos' => null,
            ':retenciones' => null,
            ':lugar_expedicion' => null,
            ':condiciones_pago' => null,
            ':tipo_comprobante' => null,
            ':concepto' => null,
            ':xml_status' => 'error',
            ':total' => null,
        ]);
        $errors++;
        continue;
    }

    try {
        $xmlContent = file_get_contents($xmlPath);
        if ($xmlContent === false) {
            throw new RuntimeException("No se pudo leer el archivo");
        }

        // Remover namespaces (CFDI 4.0 usa cfdi:Comprobante, tfd:TimbreFiscalDigital)
        $xmlContent = preg_replace('/<\w+:(\w+)(\s|>)/', '<$1$2', $xmlContent);
        $xmlContent = preg_replace('/<\/\w+:(\w+)\s*>/', '</$1>', $xmlContent);
        $xmlContent = preg_replace('/\s+xmlns[^=]*="[^"]*"/i', '', $xmlContent);

        $xml = @simplexml_load_string($xmlContent);
        if ($xml === false) {
            throw new RuntimeException("XML inválido");
        }

        // El elemento raíz es el Comprobante
        $comprobante = $xml;
        if (! isset($comprobante['SubTotal']) && ! isset($comprobante['Total'])) {
            throw new RuntimeException("No se encontró elemento Comprobante válido");
        }

        // Atributos principales
        $serie = (string) ($comprobante['Serie'] ?? '');
        $folio = (string) ($comprobante['Folio'] ?? '');
        $formaPago = (string) ($comprobante['FormaPago'] ?? '');
        $metodoPago = (string) ($comprobante['MetodoPago'] ?? '');
        $tipoComprobante = (string) ($comprobante['TipoDeComprobante'] ?? '');
        $lugarExpedicion = (string) ($comprobante['LugarExpedicion'] ?? '');
        $condicionesPago = (string) ($comprobante['CondicionesDePago'] ?? '');

        // Totales
        $subtotal = (float) ($comprobante['SubTotal'] ?? 0);
        $descuento = (float) ($comprobante['Descuento'] ?? 0);
        $total = (float) ($comprobante['Total'] ?? 0);

        // IVA: usar TotalImpuestosTrasladados del nodo Impuestos si existe
        $impuestosNode = $comprobante->Impuestos ?? null;
        $impuestos = 0.0;
        $retenciones = 0.0;
        if ($impuestosNode && isset($impuestosNode['TotalImpuestosTrasladados'])) {
            $impuestos = (float) $impuestosNode['TotalImpuestosTrasladados'];
        }
        if ($impuestos <= 0) {
            $impuestos = $total - $subtotal + $descuento;
        }
        if ($impuestosNode && isset($impuestosNode['TotalImpuestosRetenidos'])) {
            $retenciones = (float) $impuestosNode['TotalImpuestosRetenidos'];
        }
        // Fallback: atributo en raíz (algunos CFDI) o sumar Retencion(es)
        if ($retenciones <= 0.0 && isset($comprobante['TotalImpuestosRetenidos'])) {
            $retenciones = (float) $comprobante['TotalImpuestosRetenidos'];
        }
        if ($retenciones <= 0.0) {
            $sumRet = 0.0;
            if ($impuestosNode && isset($impuestosNode->Retenciones->Retencion)) {
                foreach ($impuestosNode->Retenciones->Retencion as $ret) {
                    $sumRet += (float) ($ret['Importe'] ?? 0);
                }
            }
            $conceptosNode = $comprobante->Conceptos ?? null;
            if ($conceptosNode && isset($conceptosNode->Concepto)) {
                foreach ($conceptosNode->Concepto as $conc) {
                    $impConc = $conc->Impuestos ?? null;
                    if ($impConc && isset($impConc->Retenciones->Retencion)) {
                        foreach ($impConc->Retenciones->Retencion as $ret) {
                            $sumRet += (float) ($ret['Importe'] ?? 0);
                        }
                    }
                }
            }
            if ($sumRet > 0) {
                $retenciones = $sumRet;
            }
            // Nómina: retenciones en Complemento/Nomina/Deducciones@TotalImpuestosRetenidos
            if ($retenciones <= 0.0 && isset($comprobante->Complemento->Nomina->Deducciones['TotalImpuestosRetenidos'])) {
                $retNomina = (float) $comprobante->Complemento->Nomina->Deducciones['TotalImpuestosRetenidos'];
                if ($retNomina > 0) {
                    $retenciones = $retNomina;
                }
            }
        }

        // Emisor y Receptor
        $emisor = $comprobante->Emisor ?? null;
        $receptor = $comprobante->Receptor ?? null;
        $rfcEmisor = $emisor ? (string) ($emisor['Rfc'] ?? '') : '';
        $nombreEmisor = $emisor ? (string) ($emisor['Nombre'] ?? '') : '';
        $rfcReceptor = $receptor ? (string) ($receptor['Rfc'] ?? '') : '';
        $nombreReceptor = $receptor ? (string) ($receptor['Nombre'] ?? '') : '';
        $usoCfdi = $receptor ? (string) ($receptor['UsoCFDI'] ?? '') : '';

        $fechaEmision = (string) ($comprobante['Fecha'] ?? '');
        $moneda = (string) ($comprobante['Moneda'] ?? 'MXN');

        // Primer concepto: descripción (para vista en portal)
        $concepto = '';
        $conceptos = $comprobante->Conceptos ?? null;
        if ($conceptos && isset($conceptos->Concepto)) {
            $primerConcepto = is_array($conceptos->Concepto) ? $conceptos->Concepto[0] : $conceptos->Concepto;
            $concepto = (string) ($primerConcepto['Descripcion'] ?? '');
        }

        // Actualizar DB (incluye fecha, emisor, receptor para filas creadas solo por verify)
        $updateStmt->execute([
            ':fecha_emision' => $fechaEmision ?: null,
            ':rfc_emisor' => $rfcEmisor ?: null,
            ':nombre_emisor' => $nombreEmisor ?: null,
            ':rfc_receptor' => $rfcReceptor ?: null,
            ':nombre_receptor' => $nombreReceptor ?: null,
            ':moneda' => $moneda ?: null,
            ':id' => $id,
            ':serie' => $serie ?: null,
            ':folio' => $folio ?: null,
            ':forma_pago' => $formaPago ?: null,
            ':metodo_pago' => $metodoPago ?: null,
            ':uso_cfdi' => $usoCfdi ?: null,
            ':subtotal' => $subtotal > 0 ? $subtotal : null,
            ':descuento' => $descuento > 0 ? $descuento : null,
            ':impuestos' => $impuestos > 0 ? $impuestos : null,
            ':retenciones' => $retenciones > 0 ? $retenciones : null,
            ':lugar_expedicion' => $lugarExpedicion ?: null,
            ':condiciones_pago' => $condicionesPago ?: null,
            ':tipo_comprobante' => $tipoComprobante ?: null,
            ':concepto' => $concepto ?: null,
            ':xml_status' => 'parsed',
            ':total' => $total > 0 ? $total : null,
        ]);

        $parsed++;
        fwrite(STDOUT, "✅ {$row['uuid']}: parseado\n");

    } catch (Throwable $e) {
        fwrite(STDERR, "❌ Error parseando {$row['uuid']}: {$e->getMessage()}\n");
        $updateStmt->execute([
            ':fecha_emision' => null,
            ':rfc_emisor' => null,
            ':nombre_emisor' => null,
            ':rfc_receptor' => null,
            ':nombre_receptor' => null,
            ':moneda' => null,
            ':id' => $id,
            ':serie' => null,
            ':folio' => null,
            ':forma_pago' => null,
            ':metodo_pago' => null,
            ':uso_cfdi' => null,
            ':subtotal' => null,
            ':descuento' => null,
            ':impuestos' => null,
            ':retenciones' => null,
            ':lugar_expedicion' => null,
            ':condiciones_pago' => null,
            ':tipo_comprobante' => null,
            ':concepto' => null,
            ':xml_status' => 'error',
            ':total' => null,
        ]);
        $errors++;
    }
}

fwrite(STDOUT, "\n✅ Parseados: {$parsed} | ❌ Errores: {$errors}\n");
exit($errors > 0 ? 1 : 0);
