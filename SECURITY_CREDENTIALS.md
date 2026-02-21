# Seguridad de credenciales SAT (FIEL)

Este documento describe cómo se almacenan y protegen las credenciales FIEL en el portal y qué recomendaciones aplicar en producción.

## Cómo se guardan

### Archivos .cer y .key
- **Ubicación:** `storage/credentials/{issuer_id}/fiel.cer` y `fiel.key`.
- **Permisos:** Los archivos se crean con `chmod 0600` (solo lectura/escritura del usuario que ejecuta la aplicación). El directorio `storage/credentials` y cada subdirectorio `{issuer_id}` se crean con `0700` (solo el propietario puede entrar y listar).
- **Validación:** Extensiones `.cer` / `.key` y tamaño máximo 2 MB por archivo.

### Contraseña FIEL en base de datos
- **Tabla:** `sat_credentials` (columnas `fiel_cer_path`, `fiel_key_path`, `fiel_key_password`).
- **Estado actual:** La contraseña se guarda en texto plano en `fiel_key_password`. No hay cifrado en reposo con clave de entorno en esta versión.
- **Messaging en la UI:** Se usa la expresión "almacenamiento seguro" refiriéndose a permisos de archivos y control de acceso al portal, no a cifrado de la contraseña en BD.

### Control de acceso
- Solo usuarios autenticados con sesión de portal pueden acceder a `/portal/config/sat`.
- Las rutas de subida y validación requieren `get_portal_issuer`; cada emisor solo puede ver/actualizar sus propias credenciales.

## Riesgos

1. **Contraseña en claro en BD:** Si alguien obtiene acceso a la base de datos (copia, backup, dump), puede leer la contraseña FIEL. En producción se recomienda cifrar este campo con una clave de entorno (p. ej. `CREDENTIALS_ENC_KEY`).
2. **Archivos en disco:** Los .cer y .key están en el sistema de archivos con permisos 0600. Un compromiso del servidor (acceso shell, backup sin restricciones) podría permitir leerlos.
3. **Rate limit:** Existe límite por IP (5 subidas y 10 validaciones por minuto) para reducir abuso; no sustituye otras protecciones.

## Recomendaciones para producción

1. **Cifrado de la contraseña en BD:** Implementar cifrado simétrico (p. ej. Fernet o AES) para `fiel_key_password` usando una clave derivada de `CREDENTIALS_ENC_KEY`. No guardar la contraseña en claro.
2. **Permisos del proceso:** Ejecutar la aplicación con un usuario dedicado y asegurar que `storage/credentials` y su contenido pertenezcan a ese usuario y no sean legibles por otros.
3. **Backups:** Excluir `storage/credentials` de backups no cifrados o almacenarlos en un medio con control de acceso y cifrado.
4. **Auditoría:** Las acciones `credentials_uploaded` y `credentials_validated` se registran en `audit_log` y en el action log del portal; revisar estos logs de forma periódica.
5. **HTTPS:** Usar siempre HTTPS en producción para que los archivos y la contraseña no viajen en claro por la red.
6. **Secrets:** No commitear `.env` ni claves; usar variables de entorno o un gestor de secretos en el entorno de despliegue.

## Referencia rápida

| Elemento              | Ubicación / detalle                          |
|-----------------------|----------------------------------------------|
| Certificado / clave   | `storage/credentials/{issuer_id}/fiel.cer`, `fiel.key` |
| Permisos archivos     | 0600                                         |
| Permisos carpetas     | 0700 (storage, storage/credentials, por issuer_id) |
| Contraseña en BD      | Texto plano (sin cifrado en esta versión)     |
| Rate limit upload     | 5 por minuto por IP                          |
| Rate limit validate   | 10 por minuto por IP                         |
| Audit actions         | `credentials_uploaded`, `credentials_validated` |
