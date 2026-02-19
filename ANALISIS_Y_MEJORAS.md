# Análisis del Portal de Facturación y Sincronización SAT

## Estado Actual

### Arquitectura
- **Portal Web**: FastAPI (Python) - `app.py`
- **Sincronización SAT**: Scripts PHP CLI en `sat_sync/`
- **Base de Datos**: SQLite (`invoicing.db`)
- **Almacenamiento XML**: `storage/xml/{issuer_id}/{direction}/{year}/{month}/{uuid}.xml`

### Flujo Actual de Sincronización

1. **sync_xml.php**: Crea requests al SAT para descargar XML (solo crea `sat_requests`, no descarga)
2. **verify_requests.php**: Worker que verifica requests y descarga paquetes ZIP con XML
3. **sync.php**: Descarga metadata (obsoleto, solo metadata sin XML)

### Problemas Identificados

#### 1. **Datos Limitados en el Portal**
- Solo se muestra metadata básica (fecha, RFC, nombre, total, status)
- Falta información importante:
  - Forma de pago
  - Método de pago (PUE/PPD)
  - Uso CFDI
  - Serie y folio
  - Tipo de comprobante
  - Subtotal, descuentos, impuestos desglosados
  - Conceptos/productos

#### 2. **Estado "(sin XML)" en el Portal**
- Causa: `sync_xml.php` solo crea requests, pero no garantiza que `verify_requests.php` haya procesado los XML
- Los XML se guardan correctamente en `verify_requests.php`, pero puede haber desfase temporal

#### 3. **Actualización de Estados de Cancelación**
- No hay mecanismo para detectar cuando una factura se cancela después de haber sido descargada
- El SAT puede reportar cambios de estado (Vigente → Cancelado) pero no se re-sincroniza

#### 4. **Estructura del Proyecto**
- Mezcla PHP (SAT sync) y Python (portal web)
- Todo en una sola carpeta puede volverse difícil de mantener

## Plan de Mejoras

### Fase 1: Extracción de Datos del XML ✅ PRIORITARIO

**Objetivo**: Parsear XML descargados y extraer todos los campos relevantes

**Cambios necesarios**:
1. Crear script PHP `sat_sync/parse_xml.php` que:
   - Lee XML de `storage/xml/`
   - Extrae campos del CFDI usando SimpleXML/DOMDocument
   - Actualiza `sat_cfdi` con campos adicionales

2. Agregar columnas a `sat_cfdi`:
   - `serie` TEXT
   - `folio` TEXT
   - `forma_pago` TEXT
   - `metodo_pago` TEXT (PUE/PPD)
   - `uso_cfdi` TEXT
   - `subtotal` REAL
   - `descuento` REAL
   - `impuestos` REAL
   - `tipo_comprobante` TEXT (ya existe pero puede estar vacío)
   - `lugar_expedicion` TEXT
   - `condiciones_pago` TEXT

3. Actualizar queries en `app.py` para mostrar estos campos

### Fase 2: Actualización de Estados de Cancelación

**Objetivo**: Detectar y actualizar estados cuando las facturas se cancelan

**Estrategias**:
1. **Re-sincronización periódica**: Ejecutar `sync_xml.php` periódicamente con status "Cancelado"
2. **Verificación por UUID**: Script que consulta estado específico de UUIDs conocidos
3. **Webhook/Notificación**: Si Facturapi soporta webhooks de cancelación, integrarlos

**Implementación recomendada**:
- Script `sat_sync/check_cancellations.php` que:
  - Consulta UUIDs de facturas vigentes en últimos N días
  - Verifica estado en SAT
  - Actualiza `status` en `sat_cfdi` si cambió

### Fase 3: Mejora de Descarga de XML

**Problemas actuales**:
- `sync_xml.php` y `verify_requests.php` están separados (correcto para async)
- Pero puede haber delay entre creación de request y descarga

**Mejoras**:
1. Agregar columna `xml_status` a `sat_cfdi`:
   - `pending`: Request creado pero XML no descargado
   - `downloaded`: XML descargado
   - `parsed`: XML parseado y datos extraídos
   - `error`: Error al descargar/parsear

2. Dashboard en portal para ver estado de sincronización

3. Retry automático para requests fallidos

### Fase 4: Reorganización del Proyecto (Opcional)

**Opción A: Mantener todo junto** ✅ RECOMENDADO para MVP
- Ventajas: Simple, fácil de deployar, compartir DB
- Desventajas: Mezcla tecnologías

**Opción B: Separar en módulos**
```
proyecto/
├── portal/          # FastAPI app
├── sat_sync/        # Scripts PHP CLI
├── shared/          # Scripts compartidos (DB migrations)
└── storage/         # XML files
```

**Recomendación**: Mantener junto por ahora, pero documentar bien la separación de responsabilidades.

## Prioridades

1. ✅ **URGENTE**: Parsear XML y extraer campos adicionales
2. ✅ **IMPORTANTE**: Actualizar estados de cancelación
3. ✅ **MEJORA**: Mejorar feedback de estado de descarga
4. ⚠️ **FUTURO**: Considerar separación de proyectos

## Próximos Pasos

1. Crear migración de DB para nuevos campos
2. Crear `parse_xml.php` para extraer datos
3. Actualizar templates del portal para mostrar más datos
4. Crear script de verificación de cancelaciones
5. Agregar indicadores de estado en el portal
