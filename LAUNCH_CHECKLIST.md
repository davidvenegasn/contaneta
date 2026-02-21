# Checklist Lanzamiento MVP — Conta_Invoicing

**Objetivo:** Beta cerrada con seguridad mínima, migraciones aplicadas, respaldos y flujos críticos funcionando.

**Fecha objetivo:** _______________

**Documentos relacionados:** `QA_STEPS.md` (pruebas rápidas 15 min), `ROLLBACK.md` (volver atrás con git tags), `SECURITY_NOTES.md`, `env.example` / `.env.example`.

---

## Pasos exactos (copy/paste) — Dueño / no programador

Ejecutar en orden. Sustituir `http://TU_SERVIDOR:8000` por tu URL real (ej. `https://tudominio.com`).

### 1. Crear tag antes de lanzar (para poder volver atrás)
```bash
cd /ruta/del/proyecto
git tag -a v1.0-pre-$(date +%Y%m%d) -m "Pre-lanzamiento $(date +%Y-%m-%d)"
git push origin --tags
```
Ver **ROLLBACK.md** para revertir a este tag si algo falla.

### 2. Copiar y configurar variables de entorno
```bash
cp .env.example .env
# Editar .env: ENV=prod, DEV_MODE=0, SESSION_SECRET (obligatorio en prod; si falta, la app emite log CRITICAL al arrancar), COOKIE_SECURE=1 si usas HTTPS
python3 -c "import secrets; print('SESSION_SECRET=' + secrets.token_hex(32))"
# Pegar la línea que imprime dentro de .env
```

### 3. Instalar dependencias y aplicar migraciones
```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -c "from migrations_runner import apply_migrations; from config import DB_PATH; apply_migrations(DB_PATH); print('Migraciones OK')"
```

### 4. Smoke test (comprobar que la app responde)
```bash
# Terminal 1: levantar la app
./run_server.sh 8000

# Terminal 2: esperar 3 segundos y ejecutar
./scripts/smoke.sh
# Debe terminar con "OK" y código 0
```

### 5. Verificación rápida en navegador (15 min)
Seguir **QA_STEPS.md** sección "Pruebas rápidas (15 min)": registro, login, portal, health.

### 6. Backup antes de abrir a usuarios
```bash
./scripts/backup_db.sh
# Si tienes storage: ./scripts/backup_storage_xml.sh
```

### 7. Arrancar en producción (ejemplo con gunicorn)
```bash
.venv/bin/pip install gunicorn
.venv/bin/gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
```
(O usar systemd/supervisor con ese comando; ver DEPLOY_GUIDE.md.)

### 8. Comprobar health desde fuera
```bash
curl -s http://TU_SERVIDOR:8000/health
# Debe devolver {"status":"ok", ...}
```

---

## 0. Verificación rápida (post-despliegue)

- [ ] **Registro:** Ir a `/register`, crear cuenta (email, contraseña, RFC, razón social, régimen). Debe redirigir a `/portal/home` sin token en la URL.
- [ ] **Login:** Cerrar sesión, entrar con email/contraseña en `/login`. Debe entrar al portal sin `?token=`.
- [ ] **Descargas:** En facturas emitidas/recibidas, descargar XML y PDF de un CFDI; debe funcionar con sesión cookie.
- [ ] **Detalle:** Abrir detalle de un CFDI (emitido o recibido); botones XML/PDF deben funcionar.
- [ ] **Health:** `curl -s http://localhost:8000/health` devuelve `{"status":"ok","db":"ok"}`.
- [ ] **Backups:** Ejecutar `./scripts/backup_db.sh` y (si existe) `./scripts/backup_storage_xml.sh`; se crean copias en `backup/` sin borrar nada.

Ver pasos detallados en **QA_STEPS.md**.

---

## 1. Seguridad mínima

### 1.1 Variables de entorno críticas
- [ ] **DEV_MODE=0** en `.env` de producción (por defecto es "1", debe estar OFF)
- [ ] **SESSION_SECRET** configurado con valor aleatorio fuerte (32+ caracteres hex)
- [ ] **COOKIE_SECURE=1** si se usa HTTPS (obligatorio en producción con HTTPS; con 0 la cookie se envía por HTTP y puede ser interceptada). Ver **SECURITY_NOTES.md** (sección Cookies).
- [ ] **APP_DB_PATH** apunta a ruta absoluta de `invoicing.db` (no relativa)
- [ ] **FACTURAPI_SECRET_KEY** configurado y válido para timbrado real

**Verificación:**
```bash
# En servidor de producción
grep DEV_MODE .env  # Debe mostrar DEV_MODE=0
grep SESSION_SECRET .env  # Debe existir y tener valor largo
```

**Riesgo si falla:** Acceso sin autenticación (DEV_MODE), sesiones predecibles, timbrado fallido.

- [ ] **Rate limiting login:** Máx. 5 intentos por IP en 60 s (ya implementado en `POST /login`). Ver **SECURITY_NOTES.md**.

---

### 1.2 Tokens y autenticación
- [ ] Todos los `issuer_tokens` en producción tienen `active=1` y tokens únicos
- [ ] Cada issuer tiene al menos un token activo en `issuer_tokens`
- [ ] Tokens no están hardcodeados en código ni logs
- [ ] `get_issuer_by_token()` valida `t.active=1` y `i.active=1` (ya implementado)

**Verificación SQL:**
```sql
-- Verificar tokens activos por issuer
SELECT i.id, i.rfc, COUNT(t.id) as tokens_activos
FROM issuers i
LEFT JOIN issuer_tokens t ON t.issuer_id = i.id AND t.active = 1
WHERE i.active = 1
GROUP BY i.id;
-- Cada issuer debe tener >= 1 token activo
```

**Riesgo si falla:** Issuers sin acceso o tokens compartidos entre clientes.

---

### 1.3 Separación por issuer_id
- [ ] **Auditoría rápida:** Todas las queries SELECT/UPDATE/DELETE incluyen `WHERE issuer_id = ?`
- [ ] Endpoints públicos (cotizaciones `/q/{public_token}`) no exponen datos de otros issuers
- [ ] Path traversal protegido en `/portal/sat/xml/{uuid}` y `/portal/sat/pdf/{uuid}` (ya implementado con `_safe_abs_path`)

Detalle de dónde se valida `issuer_id` (descargas, detalle, APIs): **SECURITY_NOTES.md**.

**Verificación código:**
```bash
# Buscar queries sin issuer_id (deben ser pocas y justificadas)
grep -n "FROM sat_cfdi\|FROM invoices\|FROM quotations" app.py | grep -v "issuer_id"
# Solo debe aparecer en queries de catálogos o admin (si existen)
```

**Riesgo si falla:** Un cliente ve datos de otro cliente (violación de privacidad crítica).

---

## 2. Migraciones de base de datos

### 2.1 Migraciones aplicadas
- [ ] **001_baseline.sql** aplicada (crea todas las tablas base)
- [ ] **003** aplicada (columnas críticas de `sat_cfdi` e `invoices.issue_date`)
- [ ] **004** aplicada (columnas opcionales, índices, `customer_profiles` nullable)

**Verificación:**
```sql
-- Verificar migraciones aplicadas
SELECT version, applied_at FROM schema_migrations ORDER BY version;
-- Debe mostrar: 001, 003, 004 (y otras si existen)
```

**Si falta:** La app crashea al listar facturas (falta `subtotal`, `impuestos`, etc.) o al usar `api_pending_invoices` (falta `issue_date`).

---

### 2.2 Compatibilidad con DBs viejas
- [ ] Si hay DBs existentes de instalaciones anteriores, ejecutar migraciones manualmente antes de lanzar:
  ```bash
  python -c "from migrations_runner import apply_migrations; apply_migrations('invoicing.db')"
  ```
- [ ] Verificar que `customer_profiles.zip` y `customer_profiles.tax_system` son nullable (evita constraint errors)

**Verificación SQL:**
```sql
-- Verificar nullable en customer_profiles
PRAGMA table_info(customer_profiles);
-- zip y tax_system deben mostrar "notnull = 0"
```

**Riesgo si falla:** Crash en listados de facturas o errores de constraint al guardar clientes.

---

## 3. Respaldo de datos

### 3.1 Respaldo de base de datos
- [ ] **Script de backup diario** configurado (cron o systemd timer)
- [ ] Backup incluye `invoicing.db`, `invoicing.db-wal`, `invoicing.db-shm` (si existe WAL)
- [ ] Backup se guarda en ubicación externa (otro servidor, S3, o disco separado)
- [ ] Retención mínima: 7 días de backups diarios + 1 backup mensual

**Scripts incluidos (no destructivos):**
- `scripts/backup_db.sh`: copia `invoicing.db` a `backup/invoicing_YYYYMMDD_HHMMSS.db`
- `scripts/backup_storage_xml.sh`: copia directorio `storage` a `backup/storage_YYYYMMDD_HHMMSS`
- `scripts/cron_backup_example.sh`: ejemplo de entradas cron

**Uso:**
```bash
APP_DB_PATH=/ruta/invoicing.db ./scripts/backup_db.sh
STORAGE_DIR=/ruta/storage BACKUP_DIR=/backups/conta ./scripts/backup_storage_xml.sh
```
Ver ejemplo de cron en `scripts/cron_backup_example.sh`. Retención (borrar copias antiguas) se configura fuera del script.

**Riesgo si falla:** Pérdida total de datos en caso de corrupción de DB o borrado accidental.

---

### 3.2 Respaldo de XMLs
- [ ] **Script de backup de `storage/xml/`** configurado (rsync o tar comprimido)
- [ ] Backup incluye estructura completa: `storage/xml/{issuer_id}/{direction}/{year}/{month}/{uuid}.xml`
- [ ] Retención mínima: 30 días (los XMLs son críticos para auditoría SAT)

**Script sugerido (`backup_xml.sh`):**
```bash
#!/bin/bash
BACKUP_DIR="/backups/conta_invoicing_xml"
DATE=$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR"
tar -czf "$BACKUP_DIR/xml_${DATE}.tar.gz" storage/xml/
# Limpiar backups > 30 días
find "$BACKUP_DIR" -name "xml_*.tar.gz" -mtime +30 -delete
```

**Riesgo si falla:** Pérdida de XMLs descargados del SAT (no se pueden re-descargar fácilmente).

---

## 4. Flujos críticos

### 4.1 Ver facturas (portal)
- [ ] `/portal/invoices/issued` lista facturas emitidas del issuer correcto
- [ ] `/portal/invoices/received` lista facturas recibidas del issuer correcto
- [ ] `/portal/invoices/nomina` lista nóminas recibidas (si aplica)
- [ ] Filtros por mes funcionan correctamente
- [ ] Totales del mes se calculan correctamente (subtotal, IVA, retenciones)

**Prueba manual:**
1. Login con token válido de issuer_id=1
2. Verificar que solo aparecen facturas con `issuer_id=1`
3. Cambiar mes y verificar que los totales coinciden con suma manual

**Riesgo si falla:** Cliente no puede ver sus facturas (funcionalidad core del MVP).

---

### 4.2 Descargar XML
- [ ] `/portal/sat/xml/{uuid}?token=...` descarga XML correcto
- [ ] Validación de `issuer_id` funciona (no permite descargar XML de otro issuer)
- [ ] Path traversal protegido (no permite `../../../etc/passwd`)
- [ ] Si `xml_path` es NULL o archivo no existe, muestra error claro

**Prueba manual:**
1. Intentar descargar XML de factura propia → debe funcionar
2. Intentar descargar XML de factura de otro issuer (cambiar UUID) → debe fallar con 404/400
3. Verificar que `_safe_abs_path()` rechaza rutas fuera de `BASE_DIR`

**Riesgo si falla:** Cliente no puede obtener XML para auditoría o contabilidad.

---

### 4.3 Generar PDF
- [ ] `/portal/sat/pdf/{uuid}?token=...` genera PDF correctamente
- [ ] PDF muestra datos completos del CFDI (emisor, receptor, conceptos, totales)
- [ ] Validación de `issuer_id` funciona (igual que XML)
- [ ] Si falta XML en disco, muestra error claro (no crashea)

**Prueba manual:**
1. Generar PDF de factura propia → debe mostrar PDF completo
2. Verificar que datos coinciden con XML
3. Intentar generar PDF de factura sin XML → debe mostrar error claro

**Riesgo si falla:** Cliente no puede imprimir/compartir facturas en formato PDF.

---

### 4.4 Sincronización SAT
- [ ] Scripts PHP de `sat_sync/` funcionan en servidor de producción
- [ ] Cron configurado para ejecutar sync periódicamente:
  - `sync_xml.php` (crea requests)
  - `verify_requests.php` (descarga XMLs)
  - `parse_xml.php` (extrae campos adicionales)
- [ ] Credenciales FIEL configuradas en `sat_credentials` por issuer
- [ ] XMLs se guardan en `storage/xml/{issuer_id}/{direction}/{year}/{month}/{uuid}.xml`

**Cron sugerido (`/etc/cron.d/conta-invoicing`):**
```
# Sync SAT cada 6 horas
0 */6 * * * cd /ruta/proyecto && php sat_sync/sync_xml.php --issuer=1 issued --window=168 --max-windows=5
0 */6 * * * cd /ruta/proyecto && php sat_sync/sync_xml.php --issuer=1 received --window=168 --max-windows=5
# Verificar requests cada hora
0 * * * * cd /ruta/proyecto && php sat_sync/verify_requests.php --limit=20
# Parsear XMLs cada 2 horas
0 */2 * * * cd /ruta/proyecto && php sat_sync/parse_xml.php --limit=500
```

**Riesgo si falla:** Facturas no se sincronizan del SAT (cliente no ve facturas nuevas).

---

## 5. Configuración de servidor

### 5.1 Servidor web
- [ ] Uvicorn/Gunicorn configurado con workers adecuados (1-2 para MVP)
- [ ] Puerto y host configurados (no escuchar en 0.0.0.0 sin firewall)
- [ ] Logs configurados y rotados (logrotate)
- [ ] Si se usa HTTPS, certificado SSL válido configurado

**Comando sugerido:**
```bash
uvicorn app:app --host 127.0.0.1 --port 8000 --workers 2
# O con Gunicorn
gunicorn app:app -w 2 -k uvicorn.workers.UvicornWorker --bind 127.0.0.1:8000
```

---

### 5.2 Permisos de archivos
- [ ] `invoicing.db` tiene permisos 644 (lectura para app, escritura solo para usuario de la app)
- [ ] `storage/xml/` tiene permisos 755 (lectura/escritura para app)
- [ ] Usuario de la app tiene permisos de escritura en directorio del proyecto

**Verificación:**
```bash
ls -la invoicing.db  # Debe ser -rw-r--r-- (644)
ls -ld storage/xml/  # Debe ser drwxr-xr-x (755)
```

---

### 5.3 Dependencias
- [ ] `requirements.txt` instalado en entorno virtual
- [ ] Python 3.8+ instalado
- [ ] PHP 8.0+ instalado (para sat_sync)
- [ ] Extensiones PHP requeridas: `pdo_sqlite`, `zip`, `xml`, `curl`

**Verificación:**
```bash
python --version  # >= 3.8
php --version     # >= 8.0
pip list | grep fastapi  # Debe estar instalado
php -m | grep -E "pdo_sqlite|zip|xml|curl"  # Deben estar habilitadas
```

---

## 6. Monitoreo básico

### 6.1 Logs y errores
- [ ] Logs de aplicación accesibles (archivo o stdout)
- [ ] Errores de Python se registran (no solo print)
- [ ] Errores de PHP se registran (error_log o archivo)

**Configuración sugerida:**
```python
# En app.py ya está:
logging.basicConfig(level=logging.INFO, format="%(message)s")
# Añadir handler de archivo si se requiere:
# logging.basicConfig(level=logging.INFO, filename='app.log', format="%(asctime)s %(levelname)s %(message)s")
```

---

### 6.2 Health check básico
- [ ] Endpoint `/health` o similar responde 200 si la app está funcionando
- [ ] Verifica conexión a DB (SELECT 1)
- [ ] Opcional: verifica que migraciones están aplicadas

**Endpoint sugerido:**
```python
@app.get("/health")
def health():
    try:
        conn = db()
        conn.execute("SELECT 1")
        conn.close()
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        return Response(content=f"Error: {str(e)}", status_code=500)
```

---

## 7. Documentación para beta

### 7.1 Documentación de usuario
- [ ] Guía rápida de uso del portal (cómo ver facturas, descargar XML/PDF)
- [ ] Cómo obtener token de acceso (si se entrega manualmente)
- [ ] Contacto de soporte para reportar problemas

---

### 7.2 Documentación técnica
- [ ] README con instrucciones de instalación básicas
- [ ] Variables de entorno documentadas (`.env.example`)
- [ ] Comandos de backup/restore documentados

---

## Top 5 Riesgos y Mitigaciones Rápidas

### 🔴 Riesgo #1: DEV_MODE activo en producción
**Impacto:** Cualquiera puede acceder sin token o con token "demo", ver datos de todos los issuers.

**Mitigación rápida:**
```bash
# Verificar y corregir inmediatamente
grep DEV_MODE .env  # Si muestra "DEV_MODE=1", cambiar a "DEV_MODE=0"
# Reiniciar aplicación después del cambio
```

**Prevención:** Script de pre-flight check que valida `.env` antes de iniciar app.

---

### 🔴 Riesgo #2: Falta de separación por issuer_id en alguna query
**Impacto:** Un cliente ve datos de otro cliente (violación de privacidad crítica, posible demanda).

**Mitigación rápida:**
```bash
# Auditoría rápida antes de lanzar
grep -n "FROM sat_cfdi\|FROM invoices\|FROM quotations\|FROM customer_profiles" app.py | grep -v "issuer_id"
# Si aparece alguna query sin issuer_id, revisar manualmente
```

**Prevención:** Test automatizado que verifica que cada endpoint solo devuelve datos del issuer autenticado.

---

### 🔴 Riesgo #3: Migraciones no aplicadas en DB vieja
**Impacto:** Crash al listar facturas (falta `subtotal`, `impuestos`) o al usar `api_pending_invoices` (falta `issue_date`).

**Mitigación rápida:**
```bash
# Aplicar migraciones manualmente antes de lanzar
python -c "from migrations_runner import apply_migrations; apply_migrations('invoicing.db')"
# Verificar que se aplicaron
sqlite3 invoicing.db "SELECT version FROM schema_migrations ORDER BY version;"
```

**Prevención:** Migraciones se aplican automáticamente en startup (ya implementado), pero verificar logs de startup.

---

### 🟡 Riesgo #4: Sin respaldo automático de DB/XML
**Impacto:** Pérdida total de datos en caso de corrupción de DB o borrado accidental de XMLs.

**Mitigación rápida:**
```bash
# Configurar backup diario inmediatamente (ver sección 3.1 y 3.2)
# Probar restore antes de lanzar:
sqlite3 invoicing.db ".backup test_restore.db"
# Verificar que test_restore.db tiene datos
```

**Prevención:** Automatizar backups con cron y probar restore periódicamente.

---

### 🟡 Riesgo #5: Sync SAT no configurado o fallando silenciosamente
**Impacto:** Cliente no ve facturas nuevas del SAT (pensará que la app no funciona).

**Mitigación rápida:**
```bash
# Verificar que cron está configurado
crontab -l | grep sat_sync
# Probar sync manualmente antes de lanzar
php sat_sync/sync_xml.php --issuer=1 issued --window=24 --max-windows=1
php sat_sync/verify_requests.php --limit=5
# Verificar que se crean requests y se descargan XMLs
```

**Prevención:** Monitorear tabla `sat_requests` (debe tener requests recientes) y `sat_cfdi` (debe tener facturas nuevas).

---

## Checklist Pre-Lanzamiento (Día del lanzamiento)

- [ ] DEV_MODE=0 verificado
- [ ] SESSION_SECRET configurado
- [ ] Migraciones 001, 003, 004 aplicadas y verificadas
- [ ] Backups configurados y probados (DB + XML)
- [ ] Todos los tokens de beta testers creados y activos
- [ ] Sync SAT probado manualmente (al menos una vez)
- [ ] Health check responde 200
- [ ] Flujos críticos probados manualmente:
  - [ ] Ver facturas emitidas/recibidas
  - [ ] Descargar XML
  - [ ] Generar PDF
- [ ] Logs accesibles y sin errores críticos
- [ ] Contacto de soporte disponible para beta testers

---

## Post-Lanzamiento (Primera semana)

- [ ] Monitorear logs diariamente (buscar errores 500, excepciones)
- [ ] Verificar que sync SAT está funcionando (requests nuevos cada día)
- [ ] Verificar que backups se están ejecutando correctamente
- [ ] Recopilar feedback de beta testers (qué funciona, qué falla)
- [ ] Documentar problemas encontrados y soluciones aplicadas

---

---

## Verificación final y cómo revertir

### Verificación final antes de lanzar
1. Copiar `env.example` a `.env` y rellenar valores de producción (DEV_MODE=0, SESSION_SECRET, COOKIE_SECURE=1 si HTTPS, APP_DB_PATH, FACTURAPI_SECRET_KEY si aplica).
2. Ejecutar pasos de **QA_STEPS.md** (registro, login, logout, portal, detalle, XML/PDF, cotizaciones, health, backups).
3. Revisar **SECURITY_NOTES.md** (rate limit login, cookies, issuer_id).

### Cómo revertir usando git
Si tras desplegar esta rama necesitas volver al estado anterior (ej. rama `main`):

```bash
# Opción A: volver a la rama main y descartar cambios de esta rama
git checkout main

# Opción B: deshacer el último commit de la rama actual (mantener cambios en working tree)
git reset --soft HEAD~1

# Opción C: revertir un commit concreto (crea un nuevo commit que deshace el indicado)
git revert <commit-hash> --no-edit
```

Para desplegar de nuevo desde `agent/autonomous-hardening` después de haber vuelto a `main`:
```bash
git checkout agent/autonomous-hardening
```

**Importante:** Revertir no borra la base de datos ni los archivos de `storage/` ni `backup/`. Solo afecta al código del repositorio.

---

**Notas finales:**
- Este checklist está diseñado para **beta cerrada** (pocos usuarios controlados).
- Rate limiting de login ya está implementado (ver SECURITY_NOTES.md); para producción con varios workers valorar límite por IP en Redis.
- Priorizar seguridad (riesgos #1 y #2) sobre features adicionales.
