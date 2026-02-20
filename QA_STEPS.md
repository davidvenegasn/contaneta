# Pasos de QA para lanzamiento

Verificación manual o automatizable de flujos críticos antes y después del despliegue.

---

## 1. Registro y login

1. **Registro nuevo usuario**
   - Ir a `/register`.
   - Completar: email, contraseña (≥8 caracteres), RFC, razón social, régimen fiscal.
   - Enviar formulario.
   - **Esperado:** Redirección a `/portal/home` sin token en la URL; sesión por cookie.
2. **Login con email**
   - Cerrar sesión (o usar ventana privada). Ir a `/login`.
   - Entrar con el mismo email y contraseña.
   - **Esperado:** Redirección a `/portal/home`; no se requiere `?token=`.
3. **Token legacy**
   - Obtener un token válido de `issuer_tokens` para un issuer.
   - Abrir `/login?token=TOKEN`.
   - **Esperado:** Redirección a `/portal/home` sin token en la URL; cookie establecida.

---

## 2. Descargas y detalle

4. **Descarga XML (portal)**
   - Con sesión activa (cookie), ir a facturas emitidas o recibidas.
   - En una fila con XML disponible, clic en “Ver XML” o “Descargar XML”.
   - **Esperado:** Se descarga o muestra el XML correcto para ese UUID; no se mezcla con otro issuer.
5. **Descarga PDF (portal)**
   - Clic en “Ver PDF” o “Descargar PDF” para un CFDI con XML.
   - **Esperado:** Se genera y muestra/descarga el PDF del CFDI.
6. **Vista detalle CFDI**
   - Clic en un UUID o “Ver detalle” para ir a `/portal/cfdi/issued/{uuid}` o recibidas.
   - **Esperado:** Página de detalle con datos del CFDI; botones XML/PDF funcionan.
7. **PDF cotización**
   - Ir a Cotizaciones → una cotización guardada → “Vista previa PDF” o “Descargar PDF”.
   - **Esperado:** Se muestra o descarga el PDF de la cotización.

---

## 3. Separación y auditoría

8. **Issuer aislado**
   - Con usuario A (issuer 1), anotar un UUID de una factura emitida.
   - Cerrar sesión; iniciar sesión con usuario B (issuer 2) o con token de otro issuer.
   - Intentar abrir `/portal/sat/xml/{uuid_de_A}` (o el detalle de esa factura).
   - **Esperado:** 404 o “no encontrado”; no se sirve el XML/dato del issuer A.
9. **Audit log**
   - Tras hacer login, logout, una descarga XML y una descarga PDF, consultar:
     ```sql
     SELECT action, user_id, issuer_id, details, created_at FROM audit_log ORDER BY id DESC LIMIT 10;
     ```
   - **Esperado:** Filas con `login`, `logout`, `download_xml`, `download_pdf` (y opcionalmente `quotation_pdf`) con los IDs correctos.

---

## 4. Operación

10. **Health**
    - `GET /health` sin autenticación.
    - **Esperado:** `200` y cuerpo `{"status": "ok", "db": "ok"}` si la DB es accesible.
11. **Backups (no destructivos)**
    - Ejecutar `./scripts/backup_db.sh`.
    - **Esperado:** Se crea un archivo en `backup/invoicing_YYYYMMDD_HHMMSS.db`.
    - Si existe directorio `storage`, ejecutar `./scripts/backup_storage_xml.sh`.
    - **Esperado:** Se crea `backup/storage_YYYYMMDD_HHMMSS`.

---

## 5. Checklist rápido pre-lanzamiento

- [ ] `DEV_MODE=0` en producción.
- [ ] `SESSION_SECRET` definido y fuerte.
- [ ] Migraciones aplicadas (`schema_migrations` con 001–008 según corresponda).
- [ ] Al menos un usuario admin para impersonación (si se usa).
- [ ] Cron o timer configurado para backup de DB (y opcionalmente storage) según `scripts/cron_backup_example.sh`.
- [ ] Health endpoint comprobado y monitoreado.

---

*Documento de apoyo al LAUNCH_CHECKLIST.md.*
