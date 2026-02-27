# Cómo leer logs y localizar fallos (SRE)

Guía para operar en producción y entender fallos rápido usando el logging consistente de la aplicación.

---

## 1. Formato de cada línea de log

Cada línea de aplicación incluye un **request_id** al inicio (si `LOG_REQUEST_ID=1`, que es el default):

```
[abc12def3456] INFO:     Started server process 12345
[xyz78abc9012] action=login issuer_id=2 user_id=10
```

- **Request_id:** 12 caracteres (UUID acortado o el que envíe el cliente en `X-Request-Id`). Sirve para seguir **toda la vida de una petición** en un mismo request.
- El middleware añade `request_id` al contexto; el `LogRecordFactory` lo inyecta en cada `logging.info()` (y similares) durante ese request.

**Variables de entorno útiles:**

| Variable | Efecto |
|----------|--------|
| `LOG_REQUEST_ID=1` | Incluir `[request_id]` en cada línea (default). |
| `LOG_REQUEST_ID=0` | No incluir request_id. |
| `LOG_FILE=/ruta/app.log` | Escribir además a archivo. |
| `LOG_FORMAT="%(asctime)s [%(request_id)s] %(message)s"` | Formato personalizado. |

---

## 2. Acciones clave que se registran

Se escribe **una línea por acción** con el prefijo `action=` y datos mínimos (sin datos sensibles). Puedes buscar por `action=` para filtrar solo estas líneas.

| action | Dónde | Qué buscar |
|--------|--------|------------|
| `action=login` | Auth (POST /login) | Login correcto; ver `user_id`, `issuer_id`, `outcome` (portal_home, confirmar_perfil, choose_issuer). |
| `action=logout` | GET/POST /logout | Cierre de sesión; `user_id`, `issuer_id`. |
| `action=download_xml` | Portal e Invoicing (descarga XML CFDI) | Descargas de XML; `issuer_id`, `entity_id` (UUID del CFDI). |
| `action=download_pdf` | Portal e Invoicing (descarga PDF CFDI) | Descargas de PDF; `issuer_id`, `entity_id`. |
| `action=quotation_pdf` | Portal (PDF de cotización) | Descarga PDF de cotización; `issuer_id`, `quotation_id`. |
| `action=invoice_created` | Invoicing (POST submit factura) | Factura generada con Facturapi; `issuer_id`, `invoice_id`, `uuid`. |

**Ejemplo de líneas:**

```
[abc12def3456] action=login issuer_id=2 outcome=portal_home user_id=10
[abc12def3456] action=download_pdf entity_id=a1b2c3d4-... issuer_id=2
[xyz78abc9012] action=invoice_created invoice_id=fr-123 issuer_id=1 uuid=abc-def-...
```

---

## 3. Cómo localizar un fallo rápido

### Por request_id (una petición concreta)

1. El cliente o el balanceador puede enviar `X-Request-Id`; si no, el servidor genera uno y lo devuelve en la cabecera de respuesta **`X-Request-Id`**.
2. El usuario te dice “me dio error al descargar el PDF” y (si tienes acceso) ves en el navegador o en tu front que la respuesta tenía `X-Request-Id: abc12def3456`.
3. En el log del servidor:
   ```bash
   grep '\[abc12def3456\]' /var/log/conta/app.log
   ```
4. Ahí ves toda la secuencia de esa petición: acciones y cualquier `ERROR`/`EXCEPTION` asociado a ese request.

### Por acción (ej. solo logins o solo descargas)

```bash
grep 'action=login' /var/log/conta/app.log
grep 'action=download_xml\|action=download_pdf' /var/log/conta/app.log
grep 'action=invoice_created' /var/log/conta/app.log
```

### Por error (excepciones no capturadas)

```bash
grep -E 'ERROR|Exception|Traceback' /var/log/conta/app.log
```

Los 500 no capturados pasan por el handler que hace `logging.exception(...)`, así que verás traceback y en la misma línea (o cercana) el `request_id` del request que falló.

### Por issuer (auditoría por cliente)

```bash
grep 'issuer_id=5' /var/log/conta/app.log
```

Útil para ver actividad de un issuer concreto (logins, descargas, facturas generadas).

---

## 4. Health y readiness

| Endpoint | Uso | Respuesta esperada |
|----------|-----|---------------------|
| **GET /health** | Liveness: ¿el proceso está vivo y la DB se puede leer? | 200, `{"status":"ok","db":"ok", "migration_version":"001", ...}`. Si DB falla: `"status":"degraded"`, `"db":"error"`. |
| **GET /ready** | Readiness: ¿puede recibir tráfico? (K8s/balanceador) | 200 si migraciones aplicadas y DB legible: `{"ready":true,"migration_version":"001"}`. Si no: **503** y `{"ready":false,"reason":"migrations_not_applied"}` o `"db_not_readable"`. |

Para comprobar desde la shell:

```bash
curl -s http://localhost:8000/health | jq .
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ready
```

---

## 5. Errores en la API (/api/*)

Las rutas bajo `/api/` devuelven errores en **JSON estándar**:

```json
{
  "ok": false,
  "error": { "code": "NOT_FOUND", "message": "Not Found" },
  "detail": "Not Found"
}
```

Códigos de `error.code`: `BAD_REQUEST`, `UNAUTHORIZED`, `FORBIDDEN`, `NOT_FOUND`, `INTERNAL_ERROR`.  
Para depurar: combinar el `request_id` de la respuesta (cabecera `X-Request-Id`) con el log del servidor como en el apartado 3.

---

## 6. Resumen: qué buscar según el síntoma

| Síntoma | Qué buscar en logs |
|---------|---------------------|
| “No puedo entrar” | `action=login` + posibles `ERROR`/`bad_credentials`; rate limit en auth. |
| “No me deja descargar XML/PDF” | `action=download_xml` o `action=download_pdf` para ese issuer; 402/404/500 en respuesta; `ERROR` con el mismo `request_id`. |
| “La factura no se generó” | `action=invoice_created` (si aparece, Facturapi respondió OK); si no aparece, buscar `ERROR` o excepción en el request del submit. |
| Errores 500 genéricos | `grep -E 'ERROR|Exception|Traceback'` y luego `grep '[request_id]'` con el id de la cabecera. |
| “¿La app está lista para tráfico?” | `GET /ready` → 200 con `"ready":true`. |
