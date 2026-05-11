# Desarrollo — Guía y checklist

Documentación y checklist de pruebas manuales para desarrolladores. No sustituye las pruebas automatizadas ni el runbook de producción.

---

## Página QA (solo desarrollo)

Con `DEV_MODE=1` o `ENV=dev`, la ruta **`/portal/qa`** está disponible una vez iniciada sesión en el portal. Muestra:

- Conteos del mes: facturas emitidas y recibidas (sin datos sensibles).
- Estado del último sync SAT.
- Enlaces rápidos: Inicio, Facturas, Movimientos, Bancos, Resumen, Contactos, Nueva factura.

En producción (o con `DEV_MODE=0`) la ruta devuelve **404**.

---

## Checklist de pruebas manuales (anti-rupturas)

Usar este checklist tras cambios en el portal o en la navegación para asegurar que no se rompió nada contable ni de flujo.

### 1. Inicio

- [ ] **Inicio carga sin error** — `/portal/home` carga y muestra el dashboard (resumen del mes, pendientes, acciones rápidas o empty state).

### 2. Hub Facturas

- [ ] **Emitidas lista carga** — Pestaña “Emitidas” en `/portal/facturas` muestra la lista (o empty state).
- [ ] **Recibidas lista carga** — Pestaña “Recibidas” en `/portal/facturas` muestra la lista (o empty state).
- [ ] **PPD no truena** — Pestaña “PPD” (recibidas PPD) carga sin error aunque no haya datos.

### 3. Hub Contactos

- [ ] **Clientes carga** — En `/portal/contactos`, pestaña Clientes muestra la lista (o empty state).
- [ ] **Proveedores carga** — Pestaña Proveedores muestra la lista (o empty state).

### 4. Hub Bancos

- [ ] **Subir PDF accesible** — Flujo “Convertir Edo. de Cuenta” o subir estado de cuenta está accesible desde el hub.
- [ ] **Estados guardados accesible** — Listado de estados de cuenta guardados (si aplica) carga sin error.

### 5. Movimientos

- [ ] **Movimientos carga** — `/portal/movimientos` carga y muestra el listado o empty state.

### 6. Resumen

- [ ] **Resumen carga** — `/portal/summary` carga sin error.

### 7. Nueva factura

- [ ] **Nueva factura funciona** — Acceso a “Nueva factura” (rail o menú) lleva a `/portal/create` y el formulario carga; el flujo de timbrado (o mensaje de restricción) se comporta como se espera.

### 8. Dropdown usuario

- [ ] **Dropdown usuario funciona** — El menú del usuario (nombre/avatar en la barra superior) se abre y cierra correctamente.
- [ ] **Contiene “Mi plan”** — El dropdown incluye el enlace “Mi plan” (y no aparece “Mi plan” en el nav principal del rail/sidebar).

### 9. Shell anterior (PORTAL_SHELL_V2=0)

- [ ] **PORTAL_SHELL_V2=0 vuelve al shell anterior sin fallas** — Con `PORTAL_SHELL_V2=0` el portal usa el layout anterior (sidebar clásico); todas las rutas anteriores (Inicio, Facturas, Contactos, Bancos, Movimientos, Resumen, Nueva factura, etc.) siguen funcionando.

---

## Variables de desarrollo

| Variable | Uso |
|----------|-----|
| `ENV=dev` | Entorno desarrollo; por defecto activa `DEV_MODE=1` si no se define `DEV_MODE`. |
| `DEV_MODE=1` | Habilita página `/portal/qa`, log de emails en consola, etc. |
| `PORTAL_SHELL_V2=1` | Activa rail + drawer (navegación tipo Mindtrip). `0` = sidebar clásico. |

---

## Más documentación

- [README.md](README.md) — Arranque, variables de entorno, autenticación.
- [MIGRATIONS.md](MIGRATIONS.md) — Schema y migraciones.
- [OPERATIONS.md](OPERATIONS.md) — Operación y producción.
