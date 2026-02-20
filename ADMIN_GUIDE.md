# Guía de administración — ContaNeta

Guía para operar el SaaS sin usar terminal. Si tienes rol **admin** u **owner** en alguna cuenta, puedes usar el panel de administración.

---

## Cómo entrar al admin

1. Inicia sesión con un usuario que tenga rol **admin** u **owner** (en Memberships de algún issuer).
2. Ve a **/admin** en el navegador (ej: https://tu-dominio.com/admin).
3. Si no tienes ese rol verás 403; entra con una cuenta de administrador.

---

## Cómo ver leads y usuarios

- **Dashboard (/admin):** Resumen: usuarios, issuers, memberships; CFDI del mes por dirección; sat_requests por estado; últimos 20 eventos de audit_log.
- **Usuarios (/admin/users):** Lista con email, nombre, fecha de creación y rol máximo (owner, admin, etc.).
- **Issuers (/admin/issuers):** RFC, razón social, régimen, activo, facturapi_org_id.
- **Memberships (/admin/memberships):** Quién tiene acceso a qué issuer y con qué rol.

---

## Cómo impersonar (entrar como un cliente)

1. Ve a **/admin/issuers**.
2. Pulsa **Entrar como este issuer** en la fila del issuer deseado.
3. Verás el portal como ese issuer y un **banner amarillo**: "Modo soporte: estás viendo como [nombre]".
4. Para salir, pulsa **Salir de soporte** en el banner. La acción queda en audit_log (con IP y user-agent).

---

## Operar soporte (pasos simples)

1. Entra a **/admin** con tu usuario admin u owner.
2. En **Issuers** localiza al cliente (por RFC o razón social) y pulsa **Entrar como este issuer**.
3. Resuelve lo que necesites en el portal (ves exactamente lo que ve el cliente).
4. Pulsa **Salir de soporte** en el banner amarillo cuando termines.

Todas las entradas y salidas quedan registradas en **Dashboard** (últimos 20 eventos) y en la tabla `audit_log`.

---

## Cómo hacer backup

1. Ve a **/admin/ops**.
2. Pulsa **Crear backup ahora**.
3. Se ejecutan los scripts de backup (DB y storage XML si existe). El resultado se muestra en pantalla y se registra en audit_log. Los archivos van a la carpeta backup/ del proyecto.

---

## Cómo correr migraciones y verificar la base de datos

- **Correr migraciones:** En **/admin/ops** pulsar **Correr migraciones**.
- **Verificar DB:** En **/admin/ops** pulsar **Verificar DB** para ver tablas y versiones de migraciones aplicadas.

---

## Qué hacer si algo falla (problemas típicos)

1. **No puedo entrar a /admin:** Asegúrate de haber iniciado sesión con un usuario que tenga rol **admin** u **owner** en alguna membership. Si no tienes ninguno, un técnico debe asignarlo en la base de datos.
2. **Comprobar estado del sistema:** Abre **/admin/status** (o **/status** sin login). Ahí ves número de usuarios, issuers, CFDI por estado y jobs pendientes. Si la DB falla, sigue RECOVERY_PLAYBOOK.md.
3. **Revisar quién hizo qué:** En el Dashboard (**/admin**) se ven los últimos 20 eventos de audit_log (login, logout, register, impersonación, descargas, etc.).
4. **Backup:** Si "Crear backup ahora" en /admin/ops falla, en RECOVERY_PLAYBOOK.md hay pasos alternativos (ej. ejecutar scripts desde el servidor).

---

## Enlaces útiles

- Panel admin: **/admin**
- Conteos (admin): **/admin/status** o **/admin/health**
- Estado público (sin login): **/status**
- Health JSON: **/health**
