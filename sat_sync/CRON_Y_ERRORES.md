# Cron y Errores SAT Sync

## Errores comunes y soluciones

### 1. `CONNECT tunnel failed, response 403`
- **Causa**: Proxy, firewall o VPN bloqueando `cfdidescargamasivasolicitud.clouda.sat.gob.mx`
- **Solución**: Ejecutar desde red sin proxy restrictivo. En macOS, desactivar VPN si bloquea.

### 2. `SAT aún en proceso (no finished)`
- **Causa**: El SAT tarda 2–15 min en preparar paquetes. El script verifica cada request y sale si no está listo.
- **Solución**: Es normal. Ejecutar el cron cada 30–60 min; en la siguiente corrida se seguirán procesando.

### 3. `Stuck: SAT no termina (tries=30)`
- **Causa**: El SAT no ha terminado de preparar el paquete tras ~30 intentos.
- **Solución**: Borrar el request y volver a solicitar:
  ```sql
  DELETE FROM sat_requests WHERE id = X AND status = 'error';
  ```
  Luego ejecutar de nuevo `sync_xml` para esa ventana.

### 4. `No hay sat_credentials para issuer_id=X`
- **Causa**: Falta configurar FIEL (CER, KEY, contraseña) para ese cliente.
- **Solución**: Insertar fila en `sat_credentials` con rutas a los archivos y contraseña.

### 5. `No existe CER` / `No existe KEY`
- **Causa**: Las rutas en `sat_credentials` son incorrectas.
- **Solución**: Comprobar que los archivos existan y las rutas en la BD sean correctas.

### 6. Requests en "verifying" mucho tiempo
- **Causa**: El proceso se interrumpió (timeout, Ctrl+C) mientras procesaba.
- **Solución**: El cron los retomará (si `updated_at` es mayor a 60 segundos). Para forzar reintento:
  ```sql
  UPDATE sat_requests SET status='queued' WHERE status='verifying';
  ```

### 7. IVA recibido muestra el monto completo (sin restar retenciones)
- **Causa**: La columna `retenciones` en `sat_cfdi` está vacía porque los XML se parsearon antes de que se agregara esa extracción.
- **Solución**: Re-parsear los XML para llenar retenciones (TotalImpuestosRetenidos del CFDI):
  ```bash
  php sat_sync/parse_xml.php --force
  ```
  Opcionalmente por emisor: `php sat_sync/parse_xml.php --issuer=1 --force`

### 8. Muchas facturas muestran "Sin estatus"
- **Causa**: El estatus (Vigente/Cancelada) viene de la metadata del SAT (sync.php). Las filas creadas solo al descargar XML (verify_requests) o que no tenían estatus en la metadata quedan con `status` NULL.
- **Solución** (una vez, para datos ya existentes):
  ```bash
  sqlite3 invoicing.db "UPDATE sat_cfdi SET status = 'V' WHERE status IS NULL OR TRIM(COALESCE(status, '')) = '';"
  ```
  Luego ejecutar **check_cancellations** para marcar como canceladas las que lo estén:
  ```bash
  php sat_sync/check_cancellations.php <issuer_id> --days=365
  ```
  Para todos los issuers con credenciales:
  ```bash
  for i in $(sqlite3 invoicing.db "SELECT issuer_id FROM sat_credentials"); do
    php sat_sync/check_cancellations.php "$i" --days=365
  done
  ```
- **De ahora en adelante**: verify_requests y parse_xml rellenan `status = 'V'` cuando falta; check_cancellations actualiza a "Cancelado" cuando corresponde.

---

## Configuración de Cron (todos los clientes)

El script `cron_sat_sync.sh` procesa **todos los issuers** que tengan `sat_credentials` en la base de datos.

### Instalación

```bash
chmod +x sat_sync/cron_sat_sync.sh
```

### Crontab (recomendado cada 15 min)

```bash
crontab -e
```

Añadir:

```
# SAT Sync: metadata + XML + cancelaciones para todos los clientes
# Cada 15 min (metadata rápido, XML cuando el SAT lo prepare)
*/15 * * * * /ruta/completa/al/proyecto/sat_sync/cron_sat_sync.sh >> /tmp/sat_sync.log 2>&1
```

Reemplazar `/ruta/completa/al/proyecto` por la ruta real, por ejemplo:
```
*/30 * * * * /Users/macbokpro/Documents/Projects/conta_invoicing_mvp_PRO_clean/sat_sync/cron_sat_sync.sh >> /tmp/sat_sync.log 2>&1
```

### Ejecución manual

```bash
./sat_sync/cron_sat_sync.sh
```

### Qué hace en cada ejecución

1. **Metadata** (sync.php): Lista rápida con total, fecha, estado. El SAT prepara metadata más rápido que XML.
2. **Solicitudes XML** (sync_xml): Crea requests para mes actual y anterior.
3. **Verify** (verify_requests): Descarga paquetes cuando el SAT los tenga listos.
4. **Parse** (parse_xml): Extrae subtotal, IVA, fecha, emisor/receptor del XML.
5. **Cancelaciones** (check_cancellations): Actualiza estado de facturas canceladas.

---

## Ver logs

```bash
tail -f /tmp/sat_sync.log
```

---

## Nota sobre fecha en macOS

El script usa `date -v-1m` (macOS). En Linux usa `date -d "1 month ago"`. Si falla, ajusta la línea `YM_PREV` en `cron_sat_sync.sh`.

---

## Worker desde cola (sat_worker.py) — Sync iniciado desde la UI

Cuando el usuario pulsa **"Sincronizar SAT"** en el portal, se encolan jobs en `sat_jobs`. El script `scripts/sat_worker.py` procesa esa cola: toma jobs con `status = 'queued'`, ejecuta `php sat_sync/sync.php <issuer_id> issued` y `received`, y actualiza el estado a `ok` o `error`.

### Ejecución manual

```bash
cd /ruta/al/proyecto
APP_DB_PATH=/ruta/al/proyecto/invoicing.db python3 scripts/sat_worker.py
```

Variables de entorno opcionales:
- `APP_DB_PATH`: ruta a `invoicing.db` (por defecto: `./invoicing.db`)
- `PHP_BIN`: ejecutable PHP (por defecto: `php`)
- `SAT_SYNC_BACKFILL_DAYS`: días de backfill para sync.php (default: 7)
- `SAT_SYNC_WINDOW_HOURS`: ventana en horas (default: 6)

### Cron en producción (cada 15 min)

Ejemplo para procesar la cola cada 15 minutos:

```bash
crontab -e
```

Añadir (ajustar rutas y venv si aplica):

```
# Worker SAT: procesa jobs encolados desde la UI (Sincronizar SAT)
*/15 * * * * cd /var/www/conta-invoicing && .venv/bin/python scripts/sat_worker.py >> /var/log/conta/sat_worker.log 2>&1
```

O sin venv:

```
*/15 * * * * cd /var/www/conta-invoicing && APP_DB_PATH=/var/www/conta-invoicing/invoicing.db python3 scripts/sat_worker.py >> /var/log/conta/sat_worker.log 2>&1
```

El worker es idempotente y seguro ejecutarlo cada X minutos: solo toma jobs `queued`, los marca `running`, ejecuta el PHP y actualiza el estado. Usa `PRAGMA busy_timeout` y WAL para reducir locks en SQLite.
