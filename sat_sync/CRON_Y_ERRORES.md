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
