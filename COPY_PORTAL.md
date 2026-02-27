# Textos estándar del portal (microcopy)

Objetivo: tono profesional y tranquilo en todo el portal. Usar estos textos como referencia para mantener consistencia.

---

## 1. Error al cargar listados

Cuando falla la carga de una lista (facturas, clientes, productos, proveedores, cotizaciones):

| Elemento | Texto estándar |
|----------|----------------|
| **Título** | No pudimos cargar esto ahora. |
| **Descripción** (por defecto) | Puedes intentar de nuevo. |
| **Botón** | Reintentar |

La descripción puede sustituirse por mensajes contextuales (401, 403, 404, 5xx) generados por `portalListLoadErrorMessage` en `base_portal.html`. Fallback genérico: *Puedes intentar de nuevo.*

---

## 2. Empty states (sin datos)

| Sección | Título | Descripción | Botón principal |
|---------|--------|-------------|------------------|
| **Facturas emitidas** | No hay facturas emitidas este mes | Crea una factura nueva para empezar a facturar. | Generar factura |
| **Facturas recibidas** | No hay facturas recibidas este mes | Aún no hay facturas recibidas este mes. | Ver facturas emitidas |
| **Clientes** | Aún no tienes clientes | Guarda los datos de quien te paga para reutilizarlos en cada factura y ahorrar tiempo. | Nuevo cliente |
| **Productos** | Aún no tienes productos | Registra lo que vendes (descripción, precio e IVA) y úsalo en tus facturas sin volver a escribirlo. | Nuevo producto |
| **Proveedores** | Aún no hay proveedores | Agrega proveedores manualmente o sincroniza facturas recibidas desde el SAT para que aparezcan aquí. | (acción según vista) |
| **Cotizaciones** | Aún no tienes cotizaciones | Crea una cotización, comparte el link con tu cliente y él podrá aceptar o rechazarla desde el navegador. | Nueva cotización |

---

## 3. FIEL (Conectar SAT)

| Elemento | Texto estándar |
|----------|----------------|
| **Título** | Conectar SAT |
| **Explicación (1 línea)** | La FIEL es tu firma electrónica del SAT; la necesitamos para descargar y validar tus facturas desde el portal del SAT. Sube tu certificado (.cer) y tu clave privada (.key) para sincronizar. |

---

## 4. Botones de acción

| Contexto | Texto |
|----------|--------|
| Reintentar carga | Reintentar |
| Cerrar / Descartar acción | Cancelar |
| Guardar formulario | Guardar |
| Guardar borrador (cotizaciones) | Guardar borrador |
| Descartar borrador | Descartar borrador |
| Copiar al portapapeles | Copiar |
| Copiar link | Copiar link |
| Navegación paginada | Anterior / Siguiente |
| Limpiar filtros | Limpiar |
| Modal confirmación | Continuar / Listo |
| Sesión expirada | Iniciar sesión |
| FIEL: cambiar archivo | Cambiar archivo |
| FIEL: validar de nuevo | Validar de nuevo |
| FIEL: reemplazar archivos | Reemplazar archivos |

---

## 5. Toasts (notificaciones breves)

### Éxito
- **Guardado:** *Cliente/Proveedor/Producto guardado correctamente.*
- **Cotización:** *Cotización guardada como borrador.* / *Cotización enviada. Comparte el link con tu cliente.*
- **Copiado:** *Link/RFC/Clave copiado al portapapeles.* (o *Copiado* con mensaje vacío donde se use)
- **Eliminado:** *Puedes agregar otro cliente/producto cuando quieras.*
- **Factura timbrada:** *Factura timbrada* + total
- **Descargado:** *El archivo se está descargando.*

### Información
- **Borrador restaurado:** *Se recuperó tu borrador anterior.*
- **Borrador descartado:** *El borrador local se ha eliminado.*
- **Sync SAT:** *Los CFDI se descargan en segundo plano.*

### Advertencia (validación)
- **Cliente requerido:** *Selecciona un cliente de la lista o elige "Ingresar nombre manualmente" y escribe el nombre.*
- **Conceptos requeridos:** *Agrega al menos un concepto con descripción, cantidad > 0 y precio unitario ≥ 0.*
- **Datos requeridos (proveedor):** *RFC y razón social son obligatorios.*
- **Faltan datos (producto):** *Completa descripción, Clave ProdServ y precio unitario.*
- **Revisa los datos (cliente):** *Completa RFC y razón social. Si usas CP o email, revisa el formato.*

### Error
- **Título estándar:** *No pudimos guardar* / *No pudimos completar la acción*
- **Mensaje genérico:** *Revisa los datos e intenta de nuevo.*
- **No se pudo copiar:** *Tu navegador bloqueó el portapapeles.*
- **No se pudo eliminar:** *Revisa e intenta de nuevo o recarga la página.*

---

## 6. Sesión expirada (modal)

| Elemento | Texto |
|----------|--------|
| **Título** | Sesión expirada |
| **Mensaje** | Tu sesión ha expirado. Inicia sesión para continuar. |
| **Botón** | Iniciar sesión |

En listas (401), el texto en línea puede ser: *Sesión expirada. [Inicia sesión](/login)* o el retorno de `uiSessionExpiredMessage()`.

---

## 7. Mensajes contextuales de carga (portalListLoadErrorMessage)

Cuando la descripción del bloque de error se rellena por código según status:

| Status | Ejemplo (emitidas/recibidas) | Ejemplo (clientes/productos/proveedores/cotizaciones) |
|--------|------------------------------|--------------------------------------------------------|
| **401** | Inicia sesión o enlaza tus claves del SAT para ver tus facturas. | Inicia sesión o usa tu enlace de acceso para ver tus clientes / tus productos / … |
| **403** | Completa tu perfil fiscal para ver tus facturas. | Completa tu perfil fiscal para ver tus clientes / … |
| **404** | No encontrado. | No encontrado. |
| **5xx** | El servidor no respondió. Intenta de nuevo en unos minutos. | Idem |
| **Genérico** | Puedes intentar de nuevo. | Puedes intentar de nuevo. |

---

## 8. Drawer / paneles secundarios

- **Proveedores – Error al cargar facturas del proveedor:** *No pudimos cargar esto ahora.* + botón *Reintentar*.

---

## 9. Impersonación (modo soporte) — P44

Objetivo: que el admin no confunda la vista con la de un usuario normal. Siempre visible: banner + indicador en topbar + botón fijo.

| Elemento | Texto estándar |
|----------|----------------|
| **Banner – badge** | Modo soporte |
| **Banner – línea 1** | Viendo como **[nombre/RFC del issuer]** |
| **Banner – línea 2** | No eres el titular de esta cuenta. |
| **Banner – botón** | Salir de impersonación |
| **Topbar (botón usuario)** | Pill "Soporte" + nombre del issuer |
| **Menú usuario** | Salir de impersonación (primera opción) |
| **Botón flotante (fijo)** | Salir de impersonación |

**Auditoría:** Cada entrada y salida se registra en `audit_log` con `action = 'impersonate_start'` o `action = 'impersonate_stop'` (user_id del admin, issuer_id/target_issuer_id, details, IP y user_agent).

---

## 10. Autosave local (cotizaciones) — P46

Borrador de cotización solo en el navegador (sin tocar la DB).

| Comportamiento | Detalle |
|----------------|---------|
| **Autosave** | Cada 500 ms tras el último cambio (debounce). Cliente, nombre/email manual, líneas, notas. |
| **Al cerrar modal** | Se hace flush del estado actual a `localStorage` para no perder lo último escrito. |
| **Al abrir modal** | Si existe borrador en `localStorage`, se restaura y se muestra toast "Borrador restaurado". |
| **Descartar borrador** | Botón "Descartar borrador" → confirmación → borra `localStorage` y resetea el formulario. Toast "Borrador descartado". |

Clave: `portal_quot_draft`. Tras guardar o enviar en el servidor, el borrador local se elimina.

---

## 11. Atajos de teclado (pro) — P47

No se activan cuando el foco está en un `input`, `textarea` o `select` (no robar foco al escribir).

| Atajo | Acción |
|-------|--------|
| **/** | Enfoca el campo de búsqueda del listado (emitidas/recibidas abre el panel de filtros si estaba cerrado; clientes/productos/proveedores enfoca el search). |
| **g** luego **h** | Ir a Inicio (/portal/home). |
| **g** luego **i** | Ir a Facturas emitidas (/portal/invoices/issued). |
| **g** luego **r** | Ir a Facturas recibidas (/portal/invoices/received). |
| **Esc** | Cierra el overlay superior: PDF, confirmación, sesión expirada, drawer CFDI, drawer proveedores, modal cotización, menú usuario, sidebar. |

---

## 12. One-click copy (UUID) — P49

Copiar al portapapeles sin seleccionar texto. Botón pequeño (icono) junto al UUID en listas y en detalle.

| Contexto | Comportamiento |
|----------|----------------|
| **Listas (emitidas, recibidas, nómina)** | Columna UUID: texto truncado + botón icono copia (`uuid-copy-btn`, `data-copy-uuid`). Un clic copia el UUID completo. |
| **Drawer detalle (emitidas/recibidas)** | Botón «Copiar UUID» en el footer del drawer; mismo toast. |
| **Página detalle CFDI** | UUID en cabecera y en datos: texto + botón icono copia. También botón «Copiar UUID» en la barra de acciones. |
| **Toast** | Siempre: título **«Copiado»**, mensaje vacío (o «UUID copiado al portapapeles» si se unifica con otros copy). |

Clase del botón pequeño: `.uuid-copy-btn` (icono SVG). Contenedor: `.uuid-copy-wrap`.

---

*Documento generado en P42 (microcopy polish). Actualizado P44, P46, P47, P49.*
