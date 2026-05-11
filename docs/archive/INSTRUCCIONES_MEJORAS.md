# Instrucciones para Aplicar las Mejoras

## Resumen de Cambios Implementados

### ✅ 1. Migración de Base de Datos
**Archivo**: `db_migrate_004_add_cfdi_fields.py`

Agrega campos adicionales a la tabla `sat_cfdi`:
- `serie`, `folio`
- `forma_pago`, `metodo_pago` (PUE/PPD)
- `uso_cfdi`
- `subtotal`, `descuento`, `impuestos`
- `lugar_expedicion`, `condiciones_pago`
- `xml_status` (pending, downloaded, parsed, error)

**Ejecutar**:
```bash
python db_migrate_004_add_cfdi_fields.py
```

### ✅ 2. Script de Parseo de XML
**Archivo**: `sat_sync/parse_xml.php`

Extrae datos adicionales de los XML descargados y actualiza la base de datos.

**Uso**:
```bash
# Parsear todos los XML pendientes
php sat_sync/parse_xml.php

# Parsear solo para un issuer específico
php sat_sync/parse_xml.php --issuer=1

# Parsear solo recibidas
php sat_sync/parse_xml.php --direction=received

# Re-parsear todos (incluso los ya parseados)
php sat_sync/parse_xml.php --force
```

**Recomendación**: Ejecutar después de cada descarga de XML, o como cron job cada hora.

### ✅ 3. Script de Verificación de Cancelaciones
**Archivo**: `sat_sync/check_cancellations.php`

Verifica si facturas vigentes han sido canceladas y actualiza su estado.

**Uso**:
```bash
# Verificar últimos 30 días
php sat_sync/check_cancellations.php 1

# Verificar últimos 60 días
php sat_sync/check_cancellations.php 1 --days=60

# Solo facturas emitidas
php sat_sync/check_cancellations.php 1 --direction=issued
```

**Recomendación**: Ejecutar diariamente o cada 12 horas.

### ✅ 4. Clientes y Proveedores por Usuario (Migración 007)
**Archivo**: `db_migrate_007_customer_supplier_profiles.py`

Crea las tablas `customer_profiles` y `supplier_profiles` si no existen. Cada usuario (issuer) puede guardar:
- **Clientes**: para facturar rápido (portal Clientes)
- **Proveedores**: empresas de las que recibe facturas (portal Proveedores)

**Ejecutar** (una sola vez):
```bash
python3 db_migrate_007_customer_supplier_profiles.py
```

En el portal de Proveedores ahora puedes agregar proveedores manualmente con el botón "Agregar proveedor". Los datos se combinan con los proveedores detectados en facturas recibidas del SAT.

### ✅ 5. Actualización del Portal
- Templates actualizados para mostrar más campos
- Indicadores de estado de descarga de XML
- Columnas adicionales: Serie/Folio, Subtotal, Impuestos, Método de Pago

## Flujo de Trabajo Recomendado

### Configuración Inicial

1. **Ejecutar migración**:
   ```bash
   python db_migrate_004_add_cfdi_fields.py
   ```

2. **Parsear XML existentes**:
   ```bash
   php sat_sync/parse_xml.php --force
   ```

### Operación Normal

#### Opción A: Manual (para pruebas)
```bash
# 1. Crear requests para descargar XML
php sat_sync/sync_xml.php 1 issued --month=2026-01
php sat_sync/sync_xml.php 1 received --month=2026-01

# 2. Verificar y descargar XML (worker)
php sat_sync/verify_requests.php --issuer=1 --loop --sleep=30

# 3. Parsear XML descargados
php sat_sync/parse_xml.php --issuer=1

# 4. Verificar cancelaciones (opcional, puede ser menos frecuente)
php sat_sync/check_cancellations.php 1 --days=30
```

#### Opción B: Automatizado con Cron

**Cron jobs sugeridos**:

```bash
# Cada hora: verificar y descargar XML pendientes
0 * * * * cd /ruta/al/proyecto && php sat_sync/verify_requests.php --loop --sleep=30 --limit=50

# Cada 2 horas: parsear XML descargados
0 */2 * * * cd /ruta/al/proyecto && php sat_sync/parse_xml.php --limit=200

# Diario a las 3 AM: sincronizar nuevo mes
0 3 * * * cd /ruta/al/proyecto && php sat_sync/sync_xml.php 1 issued --month=$(date +\%Y-\%m -d "1 month ago")
0 3 * * * cd /ruta/al/proyecto && php sat_sync/sync_xml.php 1 received --month=$(date +\%Y-\%m -d "1 month ago")

# Diario a las 4 AM: verificar cancelaciones
0 4 * * * cd /ruta/al/proyecto && php sat_sync/check_cancellations.php 1 --days=30
```

## Mejoras en el Portal

### Nuevos Campos Mostrados

1. **Serie/Folio**: Identificación fiscal de la factura
2. **Subtotal**: Monto antes de impuestos
3. **Impuestos**: Total de impuestos
4. **Método de Pago**: PUE (Pago en una exhibición) o PPD (Pago en parcialidades o diferido)
5. **Estado de XML**: 
   - "Descargando..." si está pendiente
   - "Error" si hubo problema
   - Botón "Ver XML" si está disponible

### Indicadores de Estado

- **xml_status = 'pending'**: Request creado pero XML aún no descargado
- **xml_status = 'downloaded'**: XML descargado pero no parseado
- **xml_status = 'parsed'**: XML parseado y datos extraídos
- **xml_status = 'error'**: Error al descargar o parsear

## Solución de Problemas

### "Sin XML" sigue apareciendo

1. Verificar que `verify_requests.php` esté ejecutándose
2. Revisar logs de `verify_requests.php`
3. Verificar que los requests estén en estado 'finished' en `sat_requests`
4. Ejecutar manualmente: `php sat_sync/verify_requests.php --issuer=1`

### Datos no aparecen en el portal

1. Ejecutar parseo: `php sat_sync/parse_xml.php --issuer=1`
2. Verificar que la migración se ejecutó correctamente
3. Revisar que los XML existan en `storage/xml/`

### Cancelaciones no se detectan

1. Verificar que `check_cancellations.php` se ejecute periódicamente
2. El script solo verifica facturas vigentes de los últimos N días
3. Si una factura ya estaba cancelada cuando se descargó, no se detectará cambio

## Próximos Pasos Sugeridos

1. **Automatización completa**: Configurar todos los cron jobs
2. **Dashboard de sincronización**: Agregar página en portal para ver estado de sync
3. **Notificaciones**: Email/WhatsApp cuando se detecten cancelaciones
4. **Búsqueda avanzada**: Filtrar por serie/folio, método de pago, etc.
5. **Exportación**: Descargar reportes en Excel/PDF

## Estructura del Proyecto

**Recomendación**: Mantener todo junto por ahora (MVP). La separación puede hacerse después si:
- El proyecto crece significativamente
- Necesitas escalar horizontalmente
- Quieres deployar componentes por separado

**Ventajas de mantener junto**:
- Compartir base de datos fácilmente
- Deploy simple
- Desarrollo más rápido

**Desventajas**:
- Mezcla PHP y Python
- Puede volverse difícil de mantener con muchos archivos

Para separar en el futuro, estructura sugerida:
```
proyecto/
├── portal/          # FastAPI (Python)
├── sat_sync/        # Scripts PHP CLI
├── shared/          # Migraciones y utilidades compartidas
└── storage/         # XML files
```
