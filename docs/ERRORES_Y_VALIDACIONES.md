# Errores y validaciones — UX Writer + QA

Objetivo: errores y validaciones **claros, humanos y accionables** (título + detalle + acción recomendada).

---

## 1. Lista de strings cambiados

### Errores normalizados (formato: Título + detalle + acción)

| Contexto | Antes | Después |
|----------|--------|---------|
| Toast error genérico | `title: 'Error'`, `message: 'No se pudo completar la acción.'` | `title: 'No pudimos completar la acción'`, `message: 'Revisa los datos e intenta de nuevo.'` |
| Guardar cliente | `'Error'`, `'No se pudo guardar el cliente.'` | `'No pudimos guardar'`, `'Revisa RFC, razón social y CP e intenta de nuevo.'` |
| Guardar producto | `'Error'`, `'No se pudo guardar el producto.'` | `'No pudimos guardar'`, `'Revisa descripción, clave ProdServ y precio e intenta de nuevo.'` |
| Guardar cotización | `'Error'`, `'No se pudo guardar la cotización.'` | `'No pudimos guardar'`, `'Revisa cliente y conceptos e intenta de nuevo.'` |
| Guardar proveedor | `'Error'`, `'No se pudo guardar el proveedor.'` | `'No pudimos guardar'`, `'Revisa RFC y razón social e intenta de nuevo.'` |
| Eliminar cliente | `'Error'`, `'No se pudo guardar la lista de clientes.'` | `'No se pudo eliminar'`, `'Revisa e intenta de nuevo o recarga la página.'` |
| Carga listado (toast) | `title: 'Error'`, `message: msg` | `title: 'No se pudo cargar el listado'`, `message: msg` (contextual) |
| Sync SAT error | `'Error'`, `'No se pudo iniciar la sincronización.'` | `'No se pudo sincronizar'`, `'Revisa tu conexión o intenta en otro momento.'` |
| API message fallback | `'Error desconocido'` / `'Error'` | `'No se pudo completar la acción. Revisa e intenta de nuevo.'` |
| List load 5xx | `'No se pudo cargar el listado. Intenta de nuevo en unos momentos.'` | `'El servidor no respondió. Intenta de nuevo en unos minutos.'` |
| List load genérico | `'No se pudo cargar el listado. Revisa tu conexión e intenta de nuevo.'` | `'Revisa tu conexión e intenta de nuevo.'` (título ya es "No se pudo cargar el listado") |

### Validaciones inline — mensajes de ayuda

| Campo | Antes | Después |
|-------|--------|---------|
| RFC (clientes + quick modal) | `'RFC requerido.'` | `'Revisa el RFC: 12 o 13 caracteres, solo letras y números.'` (y mensajes específicos: obligatorio, longitud, formato) |
| Razón social | `'Razón social requerida.'` | `'Escribe la razón social o nombre del cliente.'` |
| C.P. (opcional) | (no existía) | `'El código postal debe tener 5 dígitos.'` |
| Email (opcional) | (no existía) | `'Revisa el formato del correo (ej. nombre@dominio.com).'` |
| Warning pre-guardar cliente | `'Faltan datos'`, `'RFC y razón social son obligatorios.'` | `'Revisa los datos'`, `'Completa RFC y razón social. Si usas CP o email, revisa el formato.'` |

### SAT / sincronización

| Caso | Antes | Después |
|------|--------|---------|
| Respuesta tipo "sin información en periodo" | Se mostraba el mensaje técnico tal cual | `'No se encontraron CFDI en este rango. Prueba otro periodo o sincroniza más tarde.'` (no suena a error) |
| Sync SAT catch | `'Error'`, `'No se pudo iniciar la sincronización.'` | `'No se pudo sincronizar'`, `'Revisa tu conexión o intenta en otro momento.'` |

### Fallback visual en sección (listados)

- **Emitidas / Recibidas:** Al fallar la carga, la fila de error en tabla muestra el **mismo mensaje** que el toast (título "No se pudo cargar el listado" + detalle contextual).
- **Clientes:** Bloque `#custLoadError` con título "No se pudo cargar el listado", mensaje contextual y botón "Reintentar".

---

## 2. Validaciones inline implementadas

- **RFC:** Se normaliza a mayúsculas al validar; longitud 12 (moral) o 13 (física); patrón `^[A-Z&Ñ][0-9A-Z&Ñ]{11,12}$`. Mensajes: obligatorio, longitud incorrecta, formato inválido.
- **C.P.:** Opcional; si se escribe, debe ser exactamente 5 dígitos. `maxlength="5"`, `inputmode="numeric"`, `pattern="[0-9]*"` en el input.
- **Email:** Opcional; si se escribe, formato `nombre@dominio.ext`. Regex estándar.

Dónde aplica: **Clientes** (modal en `/portal/clients`) y **Factura rápida → Añadir cliente** (modal en home).

---

## 3. Captura mental — 5 flujos

### 3.1 Crear cliente

1. Usuario entra a **Clientes** y pulsa "Crear primer cliente" o "Nuevo cliente".
2. **Validación inline:** RFC (obligatorio, 12/13 caracteres, solo letras y números; se pasa a mayúsculas), Razón social (obligatorio), C.P. (opcional, 5 dígitos), Email (opcional, formato).
3. Si falta algo o hay error de formato → mensaje bajo el campo ("Revisa el RFC...", "El código postal debe tener 5 dígitos", etc.) y toast "Revisa los datos" con mensaje genérico.
4. Al guardar: **éxito** → toast "Guardado" + cierre modal + recarga lista. **Error API** → toast "No pudimos guardar" + detalle del backend (ej. "RFC ya existe") o "Revisa RFC, razón social y CP e intenta de nuevo.".
5. Si **falla la carga** del listado → toast "No se pudo cargar el listado" + bloque de error en sección con el mismo mensaje y "Reintentar".

### 3.2 Crear producto

1. Usuario entra a **Productos** y pulsa "Crear primer producto" o "Agregar producto".
2. Validación: descripción, Clave ProdServ, precio (ya existente).
3. Al guardar: **éxito** → toast "Guardado" + cierre + recarga. **Error** → toast "No pudimos guardar" + "Revisa descripción, clave ProdServ y precio e intenta de nuevo.".
4. Si falla la carga del listado → toast + mensaje contextual (portalListLoadErrorMessage); en productos no hay bloque de error en sección (solo toast).

### 3.3 Crear cotización

1. Usuario entra a **Cotizaciones** y abre el modal de nueva cotización.
2. Cliente obligatorio; al menos un concepto con descripción y precio.
3. Al guardar borrador o enviar: **éxito** → toast y, si envió, overlay con link para copiar. **Error** → toast "No pudimos guardar" + "Revisa cliente y conceptos e intenta de nuevo.".
4. Carga del listado: mismo patrón de toast con título "No se pudo cargar el listado" y mensaje contextual.

### 3.4 Generar factura

1. Usuario va a **Genera tu factura** (o Factura rápida con cliente/producto elegidos).
2. El flujo de factura puede usar cliente/producto ya guardados o datos manuales; las validaciones de RFC/CP/email aplican si se usa el modal "Añadir cliente" desde Factura rápida (mismo esquema que Crear cliente).
3. Errores de envío/API en el formulario de factura: se espera que sigan el mismo formato (título corto + detalle + acción) donde se muestren toasts o mensajes en esa pantalla.

### 3.5 Ver facturas (emitidas / recibidas)

1. Usuario entra a **Emitidas** o **Recibidas**.
2. **Carga del listado:** Si la API falla → **toast** "No se pudo cargar el listado" + mensaje contextual (sin sesión, perfil incompleto, 5xx, conexión). **Fallback en sección:** una fila en la tabla con el mismo título y el mismo mensaje (detalle + acción), en lugar de lista vacía o error genérico.
3. **Sincronizar con SAT:** Si el backend responde con algo tipo "sin información en periodo" / "no hay datos" → se muestra **"No se encontraron CFDI en este rango. Prueba otro periodo o sincroniza más tarde."** (mensaje informativo, no técnico). Otros errores → toast "No se pudo sincronizar" + "Revisa tu conexión o intenta en otro momento.".

---

## 4. Archivos tocados

- **templates/base_portal.html:** `portalApiErrorMessage`, `portalToastApiError`, `portalToastError`, `portalListLoadErrorMessage`, manejo de sync SAT (mensaje "sin información" → amigable).
- **templates/portal_clients.html:** Validación RFC/CP/email, mensajes de ayuda, bloque `#custLoadError`, toasts y catch de save/delete.
- **templates/portal_home.html:** Modal rápido cliente: validación RFC/CP/email, mensajes de ayuda, toast "No pudimos guardar".
- **templates/portal_products.html:** Toast error guardar producto.
- **templates/portal_quotations.html:** Toast error guardar cotización.
- **templates/portal_providers.html:** Toast error guardar proveedor.
- **templates/portal_issued.html:** Toast + fila de error con mismo mensaje al fallar carga.
- **templates/portal_received.html:** Idem.

---

## 5. Cómo extender el formato

- **Toast de error:** Usar `portalToastError(err, títuloCorto, mensajePorDefecto)` o `portalToast({ type: 'danger', title: '...', message: '...' })`. El título = qué pasó; el message = detalle + qué hacer.
- **Error de API:** El backend puede seguir devolviendo `detail` (string o lista); `portalApiErrorMessage(data)` lo convierte en un solo string para el `message` del toast. Para un toast ya construido: `portalToastApiError(data, { title: 'No pudimos guardar', action: 'Revisa X e intenta de nuevo.' })`.
- **Nuevas validaciones inline:** Añadir `<div class="help" id="...Help" hidden>...</div>` y en `validate()` mostrar/ocultar según reglas; mensajes en español, sin tecnicismos.
