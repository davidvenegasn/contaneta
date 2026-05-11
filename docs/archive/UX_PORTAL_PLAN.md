# Plan de Mejoras UX - Portal Facturas Emitidas/Recibidas

Este documento describe mejoras propuestas para las vistas `/portal/invoices/issued` y `/portal/invoices/received`, enfocadas en mejor experiencia de usuario, filtros avanzados, selector de mes mejorado y modal de detalle.

---

## 1. Estructura General

### 1.1 Layout Propuesto

```
┌─────────────────────────────────────────────────────────────┐
│ Header: Título + Subtítulo                                  │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Barra Superior:                                         │ │
│ │  • Selector de mes (mejorado)                          │ │
│ │  • Botón "Filtros" (toggle)                             │ │
│ │  • Botón "Exportar" (dropdown: PDF, Excel, CSV)        │ │
│ │  • Contador de resultados (ej: "45 facturas")          │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Panel de Filtros (colapsable):                          │ │
│ │  • Rango de fechas (desde/hasta)                        │ │
│ │  • RFC / Nombre cliente/proveedor                       │ │
│ │  • Estatus (Vigente, Cancelada, En cancelación)         │ │
│ │  • Método de pago                                       │ │
│ │  • Rango de montos (min/max)                            │ │
│ │  • Búsqueda por UUID o concepto                         │ │
│ │  • Botones: "Aplicar filtros" / "Limpiar"              │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Métricas del mes (cards horizontales):                   │ │
│ │  • Total ingresos/egresos                               │ │
│ │  • IVA recibido/pagado                                  │ │
│ │  • Retenciones (si aplica)                             │ │
│ └─────────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Tabla de facturas:                                       │ │
│ │  • Columnas ordenables                                  │ │
│ │  • Paginación (si > 50 resultados)                      │ │
│ │  • Vista compacta/expandida (toggle)                    │ │
│ │  • Acciones por fila: Ver detalle (modal)              │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Componentes Detallados

### 2.1 Selector de Mes Mejorado

**Estado actual:** Dropdown con calendario mensual básico.

**Mejoras propuestas:**

#### 2.1.1 Selector con Navegación Rápida

```
┌─────────────────────────────────────────────┐
│ [‹]  Febrero 2026  [›]    [📅]             │
└─────────────────────────────────────────────┘
```

- **Botones de navegación:** `<` (mes anterior) y `>` (mes siguiente) visibles siempre.
- **Selector de mes/año:** Click en el texto abre el calendario actual (mejorado).
- **Botón calendario:** Icono adicional para abrir selector visual.

#### 2.1.2 Selector con Opciones Rápidas

```
┌─────────────────────────────────────────────┐
│ [‹]  Febrero 2026  [›]    [📅]             │
│ ┌─────────────────────────────────────────┐ │
│ │ Este mes                                 │ │
│ │ Mes pasado                               │ │
│ │ Últimos 3 meses                         │ │
│ │ Últimos 6 meses                         │ │
│ │ Año completo (2026)                      │ │
│ │ Rango personalizado...                  │ │
│ └─────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
```

- **Dropdown con opciones rápidas:**
  - Este mes
  - Mes pasado
  - Últimos 3 meses
  - Últimos 6 meses
  - Año completo (selector de año)
  - Rango personalizado (abre selector de fechas)

#### 2.1.3 Selector de Rango de Fechas

```
┌─────────────────────────────────────────────┐
│ Desde: [01/01/2026]  Hasta: [29/02/2026]  │
│ [Aplicar]  [Cancelar]                      │
└─────────────────────────────────────────────┘
```

- **Inputs de fecha:** Date picker nativo o componente custom.
- **Validación:** Desde < Hasta, máximo 12 meses de diferencia.
- **Persistencia:** Guardar último rango usado en localStorage.

---

### 2.2 Panel de Filtros Avanzados

**Ubicación:** Debajo del selector de mes, colapsable.

**Componentes:**

#### 2.2.1 Filtros por Texto

```
┌─────────────────────────────────────────────┐
│ 🔍 Buscar: [________________]              │
│    Busca en: UUID, concepto, RFC, nombre   │
└─────────────────────────────────────────────┘
```

- **Búsqueda global:** Campo de texto que busca en múltiples columnas.
- **Autocompletado:** Sugerencias mientras escribes (opcional, para grandes volúmenes).

#### 2.2.2 Filtros por Cliente/Proveedor

**Para Emitidas:**
```
┌─────────────────────────────────────────────┐
│ Receptor:                                  │
│ RFC: [________________]                    │
│ Nombre: [________________]                  │
└─────────────────────────────────────────────┘
```

**Para Recibidas:**
```
┌─────────────────────────────────────────────┐
│ Emisor:                                    │
│ RFC: [________________]                    │
│ Nombre: [________________]                  │
└─────────────────────────────────────────────┘
```

- **Inputs separados:** RFC y nombre (búsqueda independiente o combinada).
- **Sugerencias:** Dropdown con clientes/proveedores frecuentes.

#### 2.2.3 Filtros por Estatus

```
┌─────────────────────────────────────────────┐
│ Estatus:                                   │
│ ☑ Vigente                                  │
│ ☐ Cancelada                                │
│ ☐ En cancelación                           │
│ ☐ Sin estatus                              │
└─────────────────────────────────────────────┘
```

- **Checkboxes múltiples:** Permitir seleccionar varios estatus.
- **Visual:** Usar los mismos colores que los pills de estatus.

#### 2.2.4 Filtros por Monto

```
┌─────────────────────────────────────────────┐
│ Monto:                                     │
│ Desde: $[______]  Hasta: $[______]         │
└─────────────────────────────────────────────┘
```

- **Rango numérico:** Validar que Desde ≤ Hasta.
- **Formato:** Formatear con separadores de miles.

#### 2.2.5 Filtros por Método de Pago

```
┌─────────────────────────────────────────────┐
│ Método de pago:                            │
│ ☑ PUE (Pago en una exhibición)            │
│ ☑ PPD (Pago en parcialidades)             │
│ ☐ Sin especificar                          │
└─────────────────────────────────────────────┘
```

- **Checkboxes:** Basado en valores comunes del catálogo SAT.

#### 2.2.6 Botones de Acción

```
┌─────────────────────────────────────────────┐
│ [Aplicar filtros]  [Limpiar]  [Guardar...] │
└─────────────────────────────────────────────┘
```

- **Aplicar filtros:** Ejecuta la búsqueda con los filtros activos.
- **Limpiar:** Resetea todos los filtros a valores por defecto.
- **Guardar como...:** Guarda combinación de filtros como "vista guardada" (opcional, feature avanzado).

---

### 2.3 Tabla de Facturas Mejorada

#### 2.3.1 Columnas Propuestas

**Facturas Emitidas:**
- Fecha (ordenable)
- Receptor (RFC + Nombre, ordenable por nombre)
- Concepto (truncado, expandible en modal)
- UUID (click para copiar)
- Total (ordenable)
- IVA recibido (ordenable)
- Método de pago (filtrable)
- Estatus (filtrable, con colores)
- Acciones (Ver detalle, Ver XML, Ver PDF)

**Facturas Recibidas:**
- Fecha (ordenable)
- Emisor (RFC + Nombre, ordenable por nombre)
- Concepto (truncado, expandible en modal)
- UUID (click para copiar)
- Total (ordenable)
- IVA pagado (ordenable)
- Método de pago (filtrable)
- Estatus (filtrable, con colores)
- Acciones (Ver detalle, Ver XML, Ver PDF)

#### 2.3.2 Mejoras de Interacción

- **Ordenamiento:** Click en header de columna para ordenar (asc/desc), indicador visual de columna activa.
- **Vista compacta/expandida:** Toggle para mostrar más/menos columnas.
- **Selección múltiple:** Checkbox en cada fila para acciones en lote (exportar seleccionadas, etc.).
- **Hover:** Resaltar fila al pasar el mouse.
- **Click en fila:** Abre modal de detalle (no solo botón "Ver detalle").

#### 2.3.3 Paginación

```
┌─────────────────────────────────────────────┐
│ Mostrando 1-50 de 234 facturas             │
│ [‹ Anterior]  [1] [2] [3] ... [5]  [Siguiente ›] │
└─────────────────────────────────────────────┘
```

- **Paginación:** Si hay > 50 resultados, mostrar paginación.
- **Selector de página:** Input para ir a página específica.
- **Tamaño de página:** Dropdown para cambiar cantidad por página (25, 50, 100, 200).

---

### 2.4 Modal de Detalle de Factura

**Trigger:** Click en fila o botón "Ver detalle".

**Estructura:**

```
┌─────────────────────────────────────────────────────────┐
│ Detalle de Factura                    [×]                │
├─────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Información General                                 │ │
│ │ • UUID: [copiar]                                    │ │
│ │ • Fecha de emisión: DD/MM/YYYY                      │ │
│ │ • Estatus: [Pill con color]                         │ │
│ │ • Serie/Folio: XXX-XXXX                              │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Emisor/Receptor                                      │ │
│ │ RFC: XXXXXXXXX                                       │ │
│ │ Nombre: Nombre Completo                             │ │
│ │ Email: email@ejemplo.com                            │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Conceptos                                            │ │
│ │ [Tabla con descripción, cantidad, precio, importe]  │ │
│ │                                                      │ │
│ │ Subtotal: $X,XXX.XX                                  │ │
│ │ Descuento: $X,XXX.XX                                 │ │
│ │ IVA: $X,XXX.XX                                       │ │
│ │ Retenciones: $X,XXX.XX                               │ │
│ │ Total: $X,XXX.XX MXN                                 │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Información de Pago                                  │ │
│ │ • Forma de pago: [valor]                             │ │
│ │ • Método de pago: [valor]                           │ │
│ │ • Uso CFDI: [valor]                                  │ │
│ └─────────────────────────────────────────────────────┘ │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ Archivos                                             │ │
│ │ [Ver XML]  [Ver PDF]  [Descargar XML]  [Descargar PDF] │
│ └─────────────────────────────────────────────────────┘ │
│                                                          │
│ [Cerrar]  [Ver XML completo]  [Ver PDF completo]        │
└─────────────────────────────────────────────────────────┘
```

**Características:**

- **Scroll interno:** Si el contenido es largo, el modal tiene scroll propio.
- **Botón copiar UUID:** Click para copiar al portapapeles con feedback visual.
- **Enlaces a archivos:** Botones para ver/descargar XML y PDF.
- **Navegación:** Botones "Anterior" / "Siguiente" para navegar entre facturas del listado filtrado.
- **Responsive:** En móvil, modal ocupa casi toda la pantalla.

---

### 2.5 Exportación

**Ubicación:** Botón "Exportar" en barra superior (dropdown).

**Opciones:**

```
┌─────────────────────────────────────────────┐
│ Exportar                                    │
│ ─────────────────────────────────────────── │
│ 📄 PDF (facturas seleccionadas)            │
│ 📊 Excel (listado completo)                │
│ 📋 CSV (datos sin formato)                  │
│ ─────────────────────────────────────────── │
│ Exportar con filtros aplicados            │
└─────────────────────────────────────────────┘
```

- **PDF:** Genera PDF con facturas seleccionadas o todas las del mes/filtro.
- **Excel:** Exporta tabla completa con formato (colores, formato de moneda).
- **CSV:** Datos sin formato para análisis externo.
- **Con filtros:** Opción para exportar solo lo visible (con filtros aplicados) o todo el mes.

---

## 3. Estados y Comportamientos

### 3.1 Estados Vacíos

**Sin resultados (sin filtros):**
- Mensaje: "No hay facturas [emitidas/recibidas] en [mes]."
- Acción sugerida: "Cambiar de mes" o "Generar factura" (solo en emitidas).

**Sin resultados (con filtros):**
- Mensaje: "No se encontraron facturas con los filtros aplicados."
- Acción: Botón "Limpiar filtros" prominente.

### 3.2 Estados de Carga

- **Cargando datos:** Skeleton loader en lugar de tabla vacía.
- **Aplicando filtros:** Indicador de carga en botón "Aplicar filtros".
- **Exportando:** Toast/notificación "Generando PDF..." con progreso si es posible.

### 3.3 Persistencia

- **Filtros:** Guardar filtros aplicados en `localStorage` (clave: `portal_filters_[issued|received]`).
- **Ordenamiento:** Guardar última columna ordenada y dirección.
- **Vista:** Guardar preferencia de vista compacta/expandida.
- **Página:** Restaurar página actual al recargar (si aplica).

---

## 4. Responsive Design

### 4.1 Desktop (> 1024px)

- Tabla completa con todas las columnas.
- Panel de filtros siempre visible (no colapsado por defecto).
- Modal de detalle centrado, ancho máximo 900px.

### 4.2 Tablet (768px - 1024px)

- Tabla con scroll horizontal.
- Panel de filtros colapsable.
- Modal de detalle casi a pantalla completa.

### 4.3 Móvil (< 768px)

- **Vista de tarjetas:** En lugar de tabla, mostrar cards por factura.
- **Filtros:** Panel completo en modal/drawer lateral.
- **Selector de mes:** Dropdown simple (sin calendario visual si es muy complejo).
- **Modal de detalle:** Pantalla completa con botón "Cerrar" arriba.

**Ejemplo de card móvil:**

```
┌─────────────────────────────────────────────┐
│ DD/MM/YYYY                    $X,XXX.XX    │
│ ─────────────────────────────────────────── │
│ Receptor: Nombre Completo                  │
│ RFC: XXXXXXXXX                             │
│ ─────────────────────────────────────────── │
│ Concepto: Descripción truncada...          │
│ ─────────────────────────────────────────── │
│ [Vigente]  [Ver detalle]                  │
└─────────────────────────────────────────────┘
```

---

## 5. Accesibilidad

### 5.1 Navegación por Teclado

- **Tab:** Navegar entre controles de filtros y tabla.
- **Enter:** Aplicar filtros o abrir modal desde fila seleccionada.
- **Escape:** Cerrar modal o panel de filtros.
- **Flechas:** Navegar entre filas de tabla (opcional, avanzado).

### 5.2 ARIA Labels

- Botones con `aria-label` descriptivos.
- Tabla con `role="table"` y headers con `scope="col"`.
- Modal con `role="dialog"` y `aria-labelledby`.
- Panel de filtros con `aria-expanded` en botón toggle.

### 5.3 Contraste y Legibilidad

- Colores de estatus con contraste suficiente (WCAG AA mínimo).
- Texto truncado con `title` o `aria-label` con texto completo.
- Focus visible en todos los elementos interactivos.

---

## 6. Implementación Técnica (Notas)

### 6.1 Backend

**Nuevos endpoints sugeridos:**

- `GET /api/invoices/[issued|received]/filtered` - Listado con filtros (query params o POST body).
- `GET /api/invoices/[issued|received]/export` - Exportación (PDF/Excel/CSV).
- `GET /api/invoices/{uuid}/detail` - Detalle completo de factura (para modal).

**Query params para filtros:**

```
?ym=2026-02
&status=vigente,cancelada
&rfc_receptor=XXXX123456XX
&min_total=1000
&max_total=50000
&search=concepto o uuid
&page=1
&per_page=50
&sort_by=fecha_emision
&sort_order=desc
```

### 6.2 Frontend

**Componentes sugeridos:**

- `MonthPicker` (mejorado) - Selector de mes con opciones rápidas.
- `FilterPanel` - Panel de filtros colapsable.
- `InvoiceTable` - Tabla con ordenamiento y paginación.
- `InvoiceDetailModal` - Modal de detalle.
- `ExportDropdown` - Dropdown de exportación.

**Estado (si se usa framework o vanilla JS):**

```javascript
{
  invoices: [],
  filters: {
    ym: '2026-02',
    status: [],
    rfc: '',
    search: '',
    min_total: null,
    max_total: null,
    // ...
  },
  pagination: {
    page: 1,
    per_page: 50,
    total: 0
  },
  sorting: {
    column: 'fecha_emision',
    order: 'desc'
  },
  loading: false,
  detailModal: {
    open: false,
    uuid: null
  }
}
```

---

## 7. Priorización

### Fase 1 (MVP Mejorado)
1. ✅ Selector de mes mejorado (navegación rápida)
2. ✅ Panel de filtros básicos (estatus, búsqueda por texto)
3. ✅ Modal de detalle básico
4. ✅ Ordenamiento de columnas

### Fase 2 (Mejoras)
5. ✅ Filtros avanzados (RFC, monto, método de pago)
6. ✅ Paginación
7. ✅ Exportación (PDF/Excel básico)
8. ✅ Vista móvil (cards)

### Fase 3 (Avanzado)
9. ✅ Opciones rápidas en selector de mes (últimos 3 meses, etc.)
10. ✅ Selección múltiple y acciones en lote
11. ✅ Guardar filtros como "vistas guardadas"
12. ✅ Autocompletado en búsqueda

---

## 8. Consideraciones de UX

### 8.1 Feedback Visual

- **Cambios de filtro:** Mostrar badge con cantidad de filtros activos en botón "Filtros".
- **Aplicación de filtros:** Toast/notificación "X facturas encontradas" tras aplicar.
- **Exportación:** Indicador de progreso y notificación al completar.

### 8.2 Performance

- **Lazy loading:** Cargar facturas por páginas (no todas a la vez).
- **Debounce:** En búsqueda de texto, esperar 300ms antes de buscar.
- **Cache:** Cachear resultados de filtros comunes en cliente (opcional).

### 8.3 Consistencia

- **Mismo diseño:** Emitidas y recibidas deben tener la misma estructura y componentes.
- **Nomenclatura:** Usar términos consistentes ("Receptor" vs "Cliente", "Emisor" vs "Proveedor" según contexto).

---

## 9. Próximos Pasos

1. **Revisar este documento** con el equipo.
2. **Validar prioridades** según necesidades del negocio.
3. **Crear mockups** (opcional, usando herramientas como Figma).
4. **Implementar Fase 1** (MVP mejorado).
5. **Testing** con usuarios reales.
6. **Iterar** basado en feedback.

---

**Documento creado:** 2026-02-18  
**Última actualización:** 2026-02-18  
**Versión:** 1.0
