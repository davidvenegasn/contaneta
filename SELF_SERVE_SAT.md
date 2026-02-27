# Guía self-serve SAT — Flujo completo para el usuario

Documento único para que cualquier usuario (o tú en pruebas) siga un flujo claro: desde el registro hasta factura rápida, pasando por Conectar SAT (FIEL), validación, sincronización y descarga de XML/PDF.

---

## Resumen del flujo

| Orden | Qué | Dónde |
|-------|-----|--------|
| 1 | Registrarse o entrar con token | `/signup` o `/login` |
| 2 | Completar Mi cuenta (Datos fiscales, FIEL, 1 cliente, 1 producto) | Menú usuario → **Mi cuenta** / **Conectar SAT** |
| 3 | Conectar y validar FIEL | `/portal/config/sat` |
| 4 | Sincronizar con el SAT | Inicio o Emitidas/Recibidas → **Sync SAT** |
| 5 | Ver y descargar facturas (XML/PDF) | `/portal/invoices/issued`, `/portal/invoices/received` → detalle → Descargar |
| 6 | Factura rápida (cliente + producto) | `/portal/home` → elegir Cliente y Producto → **Generar factura** |

---

## 1. Registro

**Objetivo:** Tener una cuenta y entrar al portal.

1. Abre **`/signup`** (o `/register`, que redirige a signup).
2. Completa:
   - Correo electrónico
   - Contraseña (mínimo 8 caracteres)
   - RFC, razón social, régimen fiscal, código postal (opcional)
3. Envía el formulario. La app crea tu usuario, tu emisor y te deja con sesión iniciada.
4. Serás redirigido a **`/portal/home`**. Si te pide **confirmar perfil** (nombre) o **onboarding** (RFC/razón social), completa esos pasos hasta llegar al inicio del portal.

**Entrar sin registro (token):**

- Si te dieron un **enlace con token**, abre por ejemplo:  
  `https://tu-dominio.com/login?token=TU_TOKEN`  
  o ve a `/login` y pega el token en el campo. Tras validar, se crea la sesión y se redirige a `/portal/home` sin token en la URL.

---

## 2. Mi cuenta → Conectar SAT (FIEL) → Validar

**Objetivo:** Tener datos fiscales completos y la FIEL (e.firma) configurada y validada para poder sincronizar con el SAT.

### 2.1 Abrir “Mi cuenta” o “Conectar SAT”

- En el **portal** (cualquier página), abre el **menú de usuario** (avatar o nombre arriba a la derecha).
- Verás la sección **“Mi cuenta”** con un checklist de 4 ítems:
  - **Datos fiscales** → enlace a `/portal/datos-fiscales`
  - **FIEL** → enlace a `/portal/config/sat`
  - **1 cliente** → enlace a `/portal/clients`
  - **1 producto** → enlace a `/portal/products`
- Para conectar el SAT, haz clic en **“FIEL”** o en el ítem **“Conectar SAT (FIEL)”** del menú (misma ruta: **`/portal/config/sat`**).

### 2.2 Subir archivos FIEL y validar

1. En **`/portal/config/sat`** (Conectar SAT):
   - **Certificado (.cer):** arrastra o selecciona el archivo `.cer` de tu e.firma.
   - **Clave privada (.key):** arrastra o selecciona el archivo `.key`.
   - **Contraseña:** la que te dio el SAT para usar el archivo .key.
2. Pulsa **“Guardar y validar”**. El sistema guarda los archivos y ejecuta la validación en ese momento.
3. En el panel **Estado** verás:
   - **Configurado** si hay archivos guardados.
   - **FIEL válida ✓** y la fecha de la última validación si todo es correcto.
   - **Error** y un mensaje si la contraseña es incorrecta, el certificado está vencido o no es e.firma.
4. Si hay error, corrige (contraseña, archivos o renovación de FIEL) y vuelve a **“Guardar y validar”** o **“Validar de nuevo”**.

Requisitos: solo `.cer` y `.key` (máximo 2 MB cada uno). La FIEL debe ser **e.firma vigente** (no CSD de facturación electrónica).

---

## 3. Sync SAT

**Objetivo:** Traer al portal tus facturas emitidas y recibidas desde el SAT.

1. Cuando el estado de FIEL muestre **FIEL válida ✓**, ve a **Inicio** (`/portal/home`), **Facturas emitidas** (`/portal/invoices/issued`) o **Facturas recibidas** (`/portal/invoices/received`).
2. Verás un bloque o barra con **“Último sync”** y un botón **“Sync SAT”**.
3. Pulsa **“Sync SAT”**. El sistema encola la sincronización (emitidas y recibidas). Verás **“Sincronizando…”** mientras el proceso corre en segundo plano.
4. Al terminar, se actualizará **“Último sync: fecha y hora”** y el estado pasará a **OK** (o **Error** con mensaje si algo falló).

No hace falta mantener la página abierta; puedes volver más tarde y comprobar el estado.

Si aparece **“Configura y valida tu FIEL en Ajustes primero”** o **“Valida tu FIEL en Ajustes antes de sincronizar”**, vuelve a **Conectar SAT** (`/portal/config/sat`) y completa la subida y validación hasta ver **FIEL válida ✓**.

---

## 4. Emitidas / Recibidas → Descargar XML y PDF

**Objetivo:** Ver el listado de facturas y descargar el XML o el PDF de una factura.

### 4.1 Listados

- **Facturas emitidas:** **`/portal/invoices/issued`**. Puedes filtrar por mes, búsqueda, estatus, método de pago, etc.
- **Facturas recibidas:** **`/portal/invoices/received`**. Misma lógica de filtros.

### 4.2 Detalle y descargas

1. En el listado, haz clic en la factura (por ejemplo **“Ver detalle”** o el renglón) para ir al detalle:
   - Emitidas: **`/portal/cfdi/issued/{uuid}`**
   - Recibidas: **`/portal/cfdi/received/{uuid}`**
2. En la página de detalle tendrás:
   - **Descargar XML:** enlace a **`/portal/sat/xml/{uuid}`** (descarga el XML del CFDI).
   - **Descargar PDF:** enlace a **`/portal/sat/pdf/{uuid}`** (ver en navegador) o **`/portal/sat/pdf/{uuid}?dl=1`** (descarga directa).

Usa esos enlaces según prefieras ver en pantalla o guardar el archivo.

---

## 5. Factura rápida (cliente + producto)

**Objetivo:** Abrir la pantalla de factura con un cliente y un producto ya elegidos.

1. Ve a **Inicio** (**`/portal/home`**).
2. En el bloque **“Factura rápida”**:
   - Elige un **Cliente** en el desplegable.
   - Elige un **Producto** en el desplegable.
3. Pulsa **“Generar factura”**. Serás redirigido a  
   **`/portal/create/quick?customer_id=...&product_id=...`**  
   con el formulario de factura precargado con ese cliente y ese producto.

Si no tienes clientes o productos, el checklist de **Mi cuenta** te lleva a **Clientes** (`/portal/clients`) o **Productos** (`/portal/products`) para dar de alta al menos uno.

---

## Rutas de referencia

| Acción | Ruta |
|--------|------|
| Registro | `/signup` |
| Login | `/login` (o `/login?token=...`) |
| Inicio del portal | `/portal/home` |
| Mi cuenta (checklist en menú) | Menú usuario → ítems FIEL, Datos fiscales, 1 cliente, 1 producto |
| Conectar SAT (FIEL) | `/portal/config/sat` |
| Facturas emitidas | `/portal/invoices/issued` |
| Facturas recibidas | `/portal/invoices/received` |
| Detalle CFDI emitido | `/portal/cfdi/issued/{uuid}` |
| Detalle CFDI recibido | `/portal/cfdi/received/{uuid}` |
| Descargar XML | `/portal/sat/xml/{uuid}` |
| Descargar / ver PDF | `/portal/sat/pdf/{uuid}` o `?dl=1` para descarga |
| Factura rápida (form con cliente/producto) | `/portal/create/quick?customer_id=X&product_id=Y` |
| Clientes | `/portal/clients` |
| Productos | `/portal/products` |

---

## Si algo falla

- **“Configura y valida tu FIEL en Ajustes primero”**  
  → Entra en **Conectar SAT** (`/portal/config/sat`), sube .cer y .key, escribe la contraseña y guarda/valida hasta ver **FIEL válida ✓**.

- **“Valida tu FIEL en Ajustes antes de sincronizar”**  
  → La FIEL no está validada. En **Conectar SAT** pulsa **“Validar de nuevo”**.

- **“Ya hay una sincronización en curso”**  
  → Espera a que termine; puedes refrescar la página para ver si el estado ya cambió.

- **Estado “Error” en sync con mensaje**  
  → Revisa el mensaje (contraseña, certificado vencido, SAT no disponible). Si quieres, entra en **Conectar SAT** y usa **“Ver detalle / Revalidar FIEL”** (en el bloque de error en Inicio/Emitidas/Recibidas) para volver a validar.

Con esta guía puedes seguir el flujo completo de forma self-serve, sin depender del administrador.
