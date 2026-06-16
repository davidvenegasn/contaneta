# Research: CFDI 4.0 Portal Completeness
Date: 2026-06-11
Scope: All invoice types, flows, and edge cases needed to run a production-grade Mexican invoicing portal.

---

## Priority Matrix (summary)

| Area | Priority | Status en ContaNeta |
|---|---|---|
| CFDI Ingreso (full field set CFDI 4.0) | CRITICAL | Parcial — faltan ObjetoImp, ExportacionField |
| PPD flow + REP (Complemento de Pago 2.0) | CRITICAL | No implementado |
| Receptor validation (RFC/CP/regime/UsoCFDI) | CRITICAL | Parcial |
| Cancelación (4 motivos + receptor acceptance) | CRITICAL | Parcial |
| CFDI Egreso / nota de crédito | CRITICAL | No implementado |
| GlobalCFDI (PUBLICO EN GENERAL) | CRITICAL | No implementado |
| Factura al extranjero (XEXX) | CRITICAL | Mal hecho — faltan ResidenciaFiscal, NumRegIdTrib |
| PDF representación impresa (Anexo 20) | CRITICAL | Implementado (WeasyPrint, jun 2026) |
| CSD management + expiry alerts | CRITICAL | Parcial — falta alerta de vencimiento |
| Catalogs sync (c_UsoCFDI, c_ClaveProdServ, etc.) | CRITICAL | Parcial |
| IVA rates / exento / tasa 0% | CRITICAL | Parcial |
| CFDI de Retenciones 2.0 | IMPORTANT | No implementado |
| Moneda/TipoCambio + Banxico FIX API | IMPORTANT | Parcial |
| Nómina + Complemento 1.2 Rev E | IMPORTANT | No implementado |
| Comercio Exterior complement 1.1 | IMPORTANT | No implementado |
| Carta Porte 3.1 | IMPORTANT | No implementado |
| Addendas | NICE-TO-HAVE | No implementado |

---

## 1. CFDI Ingreso — Campos nuevos en 4.0 que el portal puede estar omitiendo

- `Exportacion` — requerido en TODOS los CFDI: 01=no exportación, 02=definitiva, 03=temporal, 04=retorno
- `ObjetoImp` por concepto — reemplazó el catch-all viejo. Valores:
  - `01` = no sujeto (sin nodo de impuestos)
  - `02` = sí objeto, debe desglosar impuestos
  - `03` = sí objeto, no obligado a desglosar
  - `04` = sí objeto pero no causa impuesto
- `RegimenFiscalReceptor` — obligatorio, debe coincidir con SAT
- `DomicilioFiscalReceptor` — solo CP postal, debe coincidir exacto con constancia SAT
- `Nombre` receptor — debe coincidir carácter a carácter con SAT (sin sufijos de régimen)
- `P01` (UsoCFDI "por definir") ELIMINADO en 4.0 — usar `S01` como default seguro
- Error más frecuente: `CFDI40147` — CP fiscal no coincide (causa #1 de rechazos)

---

## 2. PPD + Complemento de Pago 2.0 (REP) — CRÍTICO, NO IMPLEMENTADO

### Flujo completo:
1. Emisión de factura original con `MetodoPago=PPD`, `FormaPago=99`
   - PPD si el pago llega en mes diferente a la emisión; PUE si mismo mes
2. Al recibir el pago: emitir CFDI tipo P con Complemento de Pagos 2.0
   - Fecha límite: día 10 del mes siguiente al pago

### Estructura del REP:
```
Comprobante (tipo P)
  └── Complemento
        └── Pagos (ver 2.0)
              ├── Totales (resumen de impuestos)
              └── Pago (un nodo por evento de pago)
                    ├── FechaPago — datetime exacto
                    ├── FormaDePagoP — forma real: 03=transferencia, 02=cheque...
                    ├── MonedaP — moneda del pago
                    ├── TipoCambioP — si MonedaP ≠ MXN
                    ├── Monto — total pagado en MonedaP
                    ├── NumOperacion — referencia bancaria
                    └── DoctoRelacionado (uno por factura a liquidar)
                          ├── IdDocumento — UUID del Ingreso original
                          ├── MonedaDR — moneda de la factura relacionada
                          ├── EquivalenciaDR — tipo de cambio (ver abajo)
                          ├── NumParcialidad — 1ra, 2da, 3ra... parcialidad
                          ├── ImpSaldoAnt — saldo pendiente antes de este pago
                          ├── ImpPagado — monto abonado a esta factura
                          ├── ImpSaldoInsoluto — ImpSaldoAnt − ImpPagado
                          ├── ObjetoImpDR — igual que ObjetoImp del original
                          └── ImpuestosDR — si ObjetoImpDR=02: copiar IVA proporcional
```

### EquivalenciaDR (fórmula crítica):
- Si MonedaDR = MonedaP: EquivalenciaDR = 1
- Si difieren: `EquivalenciaDR = ImpSaldoAnt(MonedaDR) ÷ equivalente_en_MonedaP`
- Usar tipo de cambio Banxico FIX del DÍA DEL PAGO
- Mínimo 4 decimales; error más frecuente de rechazo

### Lo que los portales hacen mal:
1. No guardar el estado (ImpSaldoInsoluto) entre pagos parciales
2. Forzar un REP por factura — se pueden liquidar múltiples facturas en un REP
3. No alertar del plazo día 10 del mes siguiente
4. Emitir REP en facturas PUE
5. No replicar IVA proporcional en ImpuestosDR
6. Usar tipo de cambio de la fecha de factura en lugar de la fecha de pago

### Errores SAT frecuentes en REP:
- `CFDI40181` — UUID no existe o cancelado
- `CFDI40182` — ImpPagado > ImpSaldoAnt
- `CFDI40183` — NumParcialidad fuera de secuencia
- `CFDI40184` — ImpSaldoAnt no coincide con ImpSaldoInsoluto previo

---

## 3. Factura al Extranjero (XEXX) — CAMPOS QUE FALTAN

| Campo | Valor | Nota |
|---|---|---|
| RFC receptor | `XEXX010101000` | RFC genérico extranjero |
| RegimenFiscalReceptor | `616` | Siempre para XEXX |
| **ResidenciaFiscal** | Código ISO país (USA, ESP, CAN) | **OBLIGATORIO cuando RFC=XEXX** |
| **NumRegIdTrib** | EIN / VAT / ID fiscal extranjero | Obligatorio si el cliente lo tiene |
| UsoCFDI | `S01` | Siempre para extranjeros |
| DomicilioFiscalReceptor | CP del EMISOR | Extranjero no tiene CP mexicano |
| **Exportacion** | `02` (definitiva) para bienes; `01` para servicios puros | |
| Moneda | USD/EUR/etc. | TipoCambio requerido |
| TipoCambio | FIX Banxico fecha de factura | |

### Complemento de Comercio Exterior 1.1:
- Requerido cuando Exportacion=02
- Campos: TipoOperacion, ClaveDePedimento, Incoterm, TipoCambioUSD, TotalUSD
- Por concepto: FraccionArancelaria, UnidadAduana, ValorUnitarioAduana, ValorDolares

### Error común: mezclar XEXX con XAXX
- XAXX = Público en general MEXICANO (sin RFC)
- XEXX = extranjero — NUNCA poner ResidenciaFiscal con XAXX

---

## 4. CFDI Egreso (Nota de Crédito) — NO IMPLEMENTADO

- Tipo de comprobante `E`
- `CfdiRelacionados` con `TipoRelacion=01` apuntando al UUID del Ingreso original
- IVA debe replicar la tasa del original
- MetodoPago obligatorio: PUE (no se puede emitir Egreso con PPD)
- El Ingreso original NO se cancela; ambos coexisten
- Un Egreso puede relacionar múltiples Ingresos
- Si el Ingreso era PPD: el ImpSaldoInsoluto del siguiente REP debe restar el crédito

---

## 5. Cancelación CFDI 4.0 — FLUJO COMPLETO

### 4 Motivos:
| Código | Cuándo | ¿UUID sustitución? |
|---|---|---|
| `01` | Errores con sustitución | SÍ — emitir reemplazo PRIMERO, luego cancelar |
| `02` | Errores sin sustitución | No |
| `03` | Operación no realizada | No |
| `04` | Nominativa a partir de global | No |

### Motivo 01 — flujo crítico:
1. Emitir NUEVO CFDI con TipoRelacion=04 (sustitución) apuntando al UUID a cancelar
2. LUEGO solicitar cancelación del original con el UUID del nuevo como sustituto

### Cuándo NO se requiere aceptación del receptor:
- Facturas ≤ $1,000 MXN
- Nómina, Egreso, Traslado, Retenciones
- Canceladas dentro de **1 día hábil** de emisión (no 72 horas)
- Ventas a XAXX (PUBLICO EN GENERAL)

### Cuándo SÍ se requiere (3 días hábiles, luego auto-cancelado):
- B2B estándar

### Restricción: solo se puede cancelar dentro del mismo año fiscal

### Lo que los portales hacen mal:
- Mostrar cancelación como "lista" cuando está pendiente de aceptación
- No trackear estado: pendiente → aceptado/rechazado/vencido
- No alertar cuando el receptor rechaza la cancelación
- Cancelar primero en motivo 01 (debe ser al revés)

---

## 6. GlobalCFDI (PUBLICO EN GENERAL) — NO IMPLEMENTADO

- Requerido para consolidar ventas B2C donde el cliente no pide factura nominativa
- Emisión obligatoria; no se puede simplemente no facturar ventas al público

### Nodo InformacionGlobal:
```xml
<cfdi:InformacionGlobal Periodicidad="01" Meses="06" Año="2026"/>
```
- Periodicidad: 01=diaria (recomendada si ventas > $5,000/día), 02=semanal, 03=quincenal, 04=mensual
- Plazo: dentro de 24 horas de que cierra el período

### Cuando un cliente pide su factura nominativa:
1. Cancelar el Global (motivo 04) o restar el monto del siguiente global
2. Emitir Ingreso nominativo con RFC real del cliente

---

## 7. IVA — Casos especiales

- **Tasa 0%:** Nodo Traslado con TipoFactor=Tasa, TasaOCuota=0.000000, Importe=0.00
- **Exento:** Nodo Traslado con TipoFactor=Exento, sin TasaOCuota ni Importe
- Ambos requieren el nodo Traslados — omitirlo causa `CFDI40206`
- **IVA Fronterizo 8%:** para negocios en los 43 municipios fronterizos
- **IEPS:** impuesto 003, TipoFactor=Cuota (fijo por unidad) o Tasa (porcentaje)
- **Retención IVA personas físicas:** 2/3 del IVA (10.666667%)
- **Retención ISR honorarios:** 10%
- **Retención ISR RESICO:** 1.25% cuando persona moral paga a persona física RESICO (626)

---

## 8. Errores SAT más frecuentes

| Código | Causa | Mensaje usuario recomendado |
|---|---|---|
| `CFDI40143` | RFC no activo en SAT | "RFC del receptor no activo. Verifica con tu cliente." |
| `CFDI40145` | Nombre no coincide con SAT | "El nombre no coincide con el SAT. Pide Constancia actualizada." |
| `CFDI40147` | CP fiscal incorrecto | "El código postal fiscal no coincide. El cliente debe actualizarlo." |
| `CFDI40148` / `40173` | UsoCFDI incompatible con régimen | "Uso de CFDI no válido para el régimen fiscal del receptor." |
| `CFDI40106` | CSD vencido | "Tu Certificado de Sello Digital venció. Renuévalo en el SAT." |
| `CFDI40126` | Clave producto inválida | "La clave de producto/servicio no existe en el catálogo SAT." |
| `CFDI40130` | Falta InformacionGlobal para XAXX | "Facturas al público general requieren información global." |
| `CFDI40181` | UUID de REP no existe | "La factura relacionada no existe o fue cancelada." |
| `CFDI40182` | Monto REP > saldo | "El monto pagado supera el saldo pendiente." |
| `CFDI40184` | Saldo anterior incorrecto | "El saldo anterior no coincide con el complemento previo." |

---

## 9. Gestión de CSD — CRÍTICO OPERACIONALMENTE

- Vigencia: 4 años
- Almacenar .cer y .key cifrados en reposo
- Alertar 60 y 30 días antes del vencimiento
- Si CSD revocado por SAT: fallo al timbrar — superficie claramente, no error genérico
- Renovación requiere FIEL — el portal no puede automatizarlo; dar guía paso a paso

---

## 10. Lo que NO vale la pena implementar (por ahora)

- **Carta Porte 3.1** — 100+ campos, solo para transportistas. Recomendar PAC especializado.
- **Nómina** — producto separado, complejidad propia (IMSS, ISR tables, INFONAVIT)
- **Addendas** (Walmart, OXXO) — nicho muy específico, cientos de formatos
- **Retenciones 2.0** — solo para dividendos, intereses, arrendamiento — IMPORTANT pero no urgente

---

## Fuentes clave
- SAT Anexo 20 Guía de llenado CFDI 4.0
- SAT Guía llenado Complemento de Pagos 2.0
- SAT Preguntas frecuentes CFDI 4.0
- SAT GlobalCFDI Guía de llenado
- Facturapi docs, Facturama blog, MySuiteMex blog
- fiscalapi.com, contadormx.com, iacontable.mx
