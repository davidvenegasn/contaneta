# Plan de pruebas móvil — Smoke UX (20 min)

**Objetivo:** Validar UX y móvil en viewport **390px** para **demo móvil impecable**.  
**Duración total:** ~20 min.  
**No se cambia código;** solo ejecución manual y registro.

**Criterios clave 390px:** Cero scroll horizontal en body; Emitidas/Recibidas con resumen fijo y facturas en cards con scroll interno; Generar factura con conceptos en cards, IVA/retenciones compactos, botones 44px; Drawer proveedores full-screen con safe-area y botones 44px.

---

## Configuración

- **Viewport:** **390×844** (o 390×667) — iPhone 14 / estándar móvil demo.
- **Navegador:** Chrome DevTools (Device Toolbar) o Safari responsive.
- **Usuario:** Issuer con al menos 1 cliente, 1 producto, 1 factura emitida y 1 recibida (para no depender de empty states en todas las pruebas).

---

## 1. Home + Factura rápida (~4 min)

| Paso | Acción | Expected result | Screenshot pointer |
|------|--------|-----------------|--------------------|
| 1.1 | Abrir `/portal/home` en 390px. | **Cero scroll horizontal.** Topbar con hamburguesa, nombre del issuer y RFC. Debajo: saludo "Hola [alias]", métricas del mes en grid legible. | **Home:** Topbar + metric-cards visibles; sin overflow-x en body. |
| 1.2 | Scroll down. | Bloque "Factura rápida": título, select Cliente, select Producto, botón "Generar factura". Sin solapamientos ni scroll horizontal. | **Factura rápida:** Card completa; botón y selects dentro del viewport. |
| 1.3 | Abrir menú (hamburguesa). | Drawer lateral (sidebar) se abre desde la izquierda; backdrop visible; navegación completa. Cierre con X o backdrop. | **Sidebar:** Drawer cubre ~280px; lista sin cortes. |
| 1.4 | Si no hay clientes/productos: clic en "+ Añadir cliente" o "+ Añadir producto". | Modal "Nuevo cliente" o "Nuevo producto"; al guardar se cierra y se refresca el dropdown. Empty state con CTA cuando la lista está vacía. | **Factura rápida:** Modales añadir cliente/producto; empty state con CTA. |
| 1.5 | Seleccionar Cliente y Producto. Clic en "Generar factura". | Modal "Precálculo de factura" a ancho completo; iframe/form visible; botón Cerrar accesible. **Sin scroll horizontal** en el modal. | **Modal factura rápida:** Título + iframe + close visibles. |

**Regresiones típicas:** Scroll horizontal en body; métricas que se salen; botón "Generar factura" cortado; drawer que no abre/cierra; modal que se sale por la derecha.

---

## 2. Generar factura — Conceptos en cards, IVA compacto, botones 44px (~5 min)

| Paso | Acción | Expected result | Screenshot pointer |
|------|--------|-----------------|--------------------|
| 2.1 | Ir a `/portal/create` en 390px. | Header con "Volver al portal", pill "Borrador". Secciones: Receptor, Comprobante, Conceptos, IVA (global), Retenciones, Resumen. Sticky bottom con acción (Guardar/Enviar) siempre visible. **Sin scroll horizontal.** | **Form create:** Primeras secciones + sticky action en viewport. |
| 2.2 | Scroll a "03 — Conceptos". | **Conceptos en cards** (no tabla ancha); cada concepto = card con campos legibles; botón añadir concepto visible. Scroll horizontal **solo dentro** de la card si aplica, nunca en body. | **Conceptos:** Cards apiladas; sin overflow en body. |
| 2.3 | Scroll a "04 — IVA (global)" / "05 — Retenciones". | **IVA y retenciones compactos**: card con tasa IVA, ISR retenido, IVA retenido en columna o grid que quepa en 390px; labels e inputs no superpuestos. | **IVA/Retenciones:** Bloque compacto en 390px. |
| 2.4 | Scroll al final. | Barra fija (sticky) con botón principal. **Botón con min 44px de alto** (área de toque suficiente). | **Sticky action:** Botón 44px visible y clickeable. |

**Regresiones típicas:** Sticky oculto por teclado; IVA/retenciones que se solapan; conceptos con scroll horizontal en body; botones &lt; 44px.

---

## 3. Emitidas / Recibidas — Resumen fijo, facturas en cards, scroll interno (~5 min)

| Paso | Acción | Expected result | Screenshot pointer |
|------|--------|-----------------|--------------------|
| 3.1 | Ir a `/portal/invoices/issued` en 390px. | **Cero scroll horizontal.** Selector de mes (month picker) y **resumen (métricas) no deslizable** arriba. Debajo: **lista de facturas en cards** (no tabla ancha). Solo el área de cards tiene scroll vertical interno; el resumen queda fijo. | **Emitidas:** Month picker + métricas fijas + cards con scroll interno. |
| 3.2 | Clic en "Filtros". | Panel de filtros se expande: búsqueda, Estatus, Pago, Mín/Máx; botón "Limpiar". Contenido no cortado. Sin scroll horizontal en body. | **Filtros emitidas:** Panel legible en 390px. |
| 3.3 | Cerrar filtros. Clic en "Detalle" (o equivalente) de una factura. | Navegación a `/portal/cfdi/issued/{uuid}`. Detalle: título, UUID, botones Descargar XML, Descargar PDF, Ver PDF, Copiar UUID. Botones **≥44px** o bien agrupados. | **Detalle CFDI:** Botones accesibles; sin overflow-x. |
| 3.4 | Clic en "Descargar XML" y "Descargar PDF" (o Ver PDF). | XML/PDF descargan o abren en nueva pestaña. Sin 404/500. Toast si existe. | **Descargas:** Sin errores; feedback visible. |
| 3.5 | Volver al listado. Ir a `/portal/invoices/received`. | **Misma estructura:** resumen (mes + métricas) no deslizable; facturas en **cards** con scroll interno. **Sin scroll horizontal en body.** | **Recibidas:** Resumen fijo + cards + scroll solo en lista. |

**Empty states:** Lista vacía → "Aún no tienes…" con CTA. "No se pudo cargar" solo cuando status ≥ 400; un solo mensaje (bloque Reintentar), sin toast duplicado.

**Regresiones típicas:** Scroll horizontal en body; resumen que se desplaza con la lista; tabla ancha en lugar de cards; botones &lt; 44px.

---

## 4. Proveedores — Drawer perfecto en móvil (~3 min)

| Paso | Acción | Expected result | Screenshot pointer |
|------|--------|-----------------|--------------------|
| 4.1 | Ir a `/portal/providers` en 390px. | Card con búsqueda, "Agregar proveedor", "Listado". Tabla con scroll horizontal **solo dentro** de .table-wrap. **Sin scroll horizontal en body.** Empty state o filas visibles. | **Proveedores listado:** Header + tabla en contenedor. |
| 4.2 | Clic en "Ver facturas" de un proveedor. | **Drawer a pantalla completa** (100% ancho); header con título + RFC + botón Cerrar con **safe-area** (no bajo notch); body del drawer con scroll interno; footer con paginación y botones **min 44px**; "Ver todas en Facturas recibidas" 44px. Cierre con X o backdrop. | **Drawer proveedor:** Full-screen; safe-area; botones 44px. |
| 4.3 | Con el drawer abierto: pulsar ESC. | Drawer se cierra. | — |
| 4.4 | Abrir de nuevo el drawer. Usar solo Tab: el foco debe circular dentro del drawer (focus trap). Cerrar con X o backdrop. | Foco no sale del drawer; al cerrar vuelve al botón "Ver facturas". Sin scroll lock residual en body. | — |

**Regresiones típicas:** Drawer que no abre o no va al 100% en 390px; botones &lt; 44px; header/footer sin safe-area; ESC no cierra; foco se escapa; overflow en body; doble mensaje de error al fallar carga.

### Checklist — Drawer proveedores (accesibilidad y robustez)

Verificar que el drawer "Ver facturas" cumple:

- [ ] **ESC cierra:** Al pulsar Escape con el drawer abierto, se cierra y el foco vuelve al disparador ("Ver facturas").
- [ ] **Tab trap real:** Usando solo Tab / Shift+Tab, el foco circula entre los elementos focusables del drawer (Cerrar, Anterior/Siguiente, PDF/Excel, Ver todas, enlaces de la lista) y no sale al contenido de la página.
- [ ] **Foco inicial:** Al abrir el drawer, el foco va al botón "Cerrar" (o primer elemento focusable).
- [ ] **Overlay click:** Clic en el backdrop (zona oscura fuera del panel) cierra el drawer.
- [ ] **Overlay full:** El overlay cubre toda la ventana (fixed, full viewport); no hay huecos por los que se vea o se pueda interactuar con la página de fondo.
- [ ] **Scroll interno:** Solo el cuerpo del drawer (lista de facturas) hace scroll; header y footer permanecen fijos. El body de la página no hace scroll con el drawer abierto (no-scroll).
- [ ] **Sin colapsos:** Header, body y footer del drawer no se solapan ni colapsan; el contenido no se corta ni genera doble scroll.

---

## 5. Cotizaciones — Modal (~3 min)

| Paso | Acción | Expected result | Screenshot pointer |
|------|--------|-----------------|--------------------|
| 5.1 | Ir a `/portal/cotizaciones` en 390px. | Título "Cotizaciones", botón "Nueva cotización", tabla con columnas (Fecha, Cliente, Total, Estatus, Link, Acciones) con scroll horizontal contenido. | **Cotizaciones listado:** Botón + tabla en wrap. |
| 5.2 | Clic en "Nueva cotización". | Modal "Nueva cotización" se abre (quotModal): título, subtítulo, campo Cliente, sección conceptos; botón Cerrar en la cabecera. Modal ocupa casi todo el ancho; scroll vertical dentro del modal si hay mucho contenido. | **Modal cotización:** Head + body con Cliente y conceptos; close visible. |
| 5.3 | Scroll dentro del modal (si aplica). | Contenido legible; footer fijo (Guardar borrador / Enviar) visible al final del scroll. Sin doble scroll (body + modal). | **Modal cotización scroll:** Footer de acciones visible. |
| 5.4 | Cerrar modal. | Modal se cierra; listado visible de nuevo. | — |

**Regresiones típicas:** Modal que se sale por los lados; campos que se solapan; botón Cerrar cubierto; scroll del body activo con modal abierto.

---

## 6. Checklist rápido de navegación (1 min)

- En 390px: desde Home ir a Emitidas → Recibidas → Proveedores → Cotizaciones → Generar factura usando solo el menú (hamburguesa).  
- **Expected:** Cada destino carga correctamente; breadcrumb o título de página coherente; sin redirecciones inesperadas ni pantalla en blanco.

---

## Screenshot pointers — Resumen

| Área | Qué capturar |
|------|----------------|
| Home | Topbar + 4 metric-cards sin overflow-x. |
| Factura rápida | Card con selects y botón "Generar factura" completo. |
| Sidebar | Drawer abierto con todas las secciones visibles. |
| Modal factura rápida | Título + iframe + close. |
| Form create | Secciones Receptor/Conceptos/IVA/Retenciones + sticky action. |
| Emitidas/Recibidas | Month picker + tabla con scroll solo en contenedor. |
| Filtros | Panel filtros expandido legible. |
| Detalle CFDI | Botones XML/PDF/Ver PDF/Copiar UUID. |
| Proveedores drawer | Panel derecho con título y close. |
| Modal cotización | Head + Cliente + close; footer al scroll. |

---

## 10 Bug patterns comunes en móvil (revisar en cada flujo)

1. **Scroll horizontal en body**  
   La página entera se desplaza horizontalmente. Suele ser por `min-width` en tablas o contenedores sin `overflow-x: auto` en un wrapper.

2. **Elementos encimados (overlap)**  
   Texto sobre texto, botones sobre inputs, o footer fijo tapando contenido. Revisar z-index y márgenes en sticky/fixed.

3. **Botones o links demasiado pequeños**  
   Área de toque &lt; 44×44 px. Dificulta tap y puede incumplir accesibilidad. Revisar padding y min-height en botones/links.

4. **Drawer o modal que no ocupa ancho útil**  
   En 390px el panel lateral/modal deja un margen enorme o contenido comprimido. Debe usar max-width: 100% o width en % y padding adecuado.

5. **Inputs que no se pueden enfocar o enviar**  
   Teclado virtual tapa el submit o el campo activo; o el sticky bottom queda detrás del teclado. Revisar viewport y scroll al focus.

6. **Filtros o acordeones que “empujan” el contenido de forma rara**  
   Al abrir filtros, la tabla salta o se corta. Revisar si el panel está en flow vs fixed y si reserva espacio.

7. **Tablas anchas sin contenedor con overflow**  
   La tabla crece y obliga al body a scroll horizontal. Debe estar en un div con `overflow-x: auto` y opcionalmente `-webkit-overflow-scrolling: touch`.

8. **Texto truncado sin indicación**  
   Nombres largos (RFC, razón social) cortados sin ellipsis o tooltip. Revisar `text-overflow` y `overflow: hidden` en celdas.

9. **Backdrop que no cierra**  
   Al tocar fuera del modal/drawer no se cierra, o el evento está capturado por otro elemento. Revisar `data-close="true"` y listeners en backdrop.

10. **Contenido duplicado o desalineado al rotar**  
    En 390×844 (portrait) todo bien; al rotar a landscape algo se duplica o se desalinea. Revisar media queries y contenedores flex/grid.

---

## Criterios de paso/fallo

- **Paso:** Todas las acciones de la tabla se completan con el resultado esperado; no se detecta ninguno de los 10 bug patterns en los flujos probados.
- **Fallo:** Cualquier expected result no se cumple, o se identifica uno de los bug patterns (documentar en qué paso y vista).

**Tiempo por sección (orientativo):** Home+factura rápida 4 min, Generar factura 5 min, Emitidas/Recibidas 5 min, Proveedores 3 min, Cotizaciones 3 min, Navegación 1 min ≈ 20 min.
