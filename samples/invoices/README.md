# Muestras de facturas e invoices

Documentos de muestra para desarrollar y testear parsers de facturas/invoices PDF.

**Los PDFs NO se versionan en git** (ver `.gitignore`). Las URLs están abajo para re-descargar.

## Estructura

```
samples/invoices/
├── cfdi_sat/      # Facturas CFDI mexicanas (formato oficial SAT)
└── foreign/       # Invoices internacionales (vacío — pendiente conseguir samples)
```

## CFDI / Facturas mexicanas (cfdi_sat/)

CFDI = Comprobante Fiscal Digital por Internet. Es el formato oficial obligatorio en México. Tiene 2 componentes:
- **XML** (firmado por SAT, contiene toda la información estructurada — fácil de parsear)
- **PDF** (representación visual del XML — más difícil de parsear)

**Recomendación**: el sistema debería preferir leer el XML cuando esté disponible. El parser PDF es fallback cuando solo hay PDF disponible.

### Archivos descargados (9 PDFs)

| Archivo | Fuente | Tipo |
|---|---|---|
| `sat_honorarios_servicios_contables.pdf` | SAT oficial | Ejemplo de honorarios contables |
| `sat_ejemplo_servicios_profesionales.pdf` | SAT oficial | Ejemplo CFDI 3.3 servicios profesionales |
| `sat_factura_publica_gob.pdf` | gob.mx | CFDI público |
| `cfdi_cfe_pachuca_2024.pdf` | CFE (Transparencia) | CFDI procedimiento contratación |
| `cfdi_inea_2024.pdf` | INEA (Transparencia) | CFDI viáticos 2024 |
| `cfdi_scjn_2024.pdf` | SCJN | CFDI contratación servicios 2024 |
| `cfdi_scjn_dgpasc_2024.pdf` | SCJN | CFDI DGPASC 2024 |
| `cfdi_cenace_2024.pdf` | CENACE | CFDI consolidada CFDI 4.0 2024 |
| `cfdi_seg_guanajuato_2024.pdf` | SEG Guanajuato | CFDI 3er trimestre 2024 |

### URLs originales (para re-descargar)

```bash
# Oficiales SAT
curl -L -o sat_honorarios_servicios_contables.pdf "https://www.sat.gob.mx/minisitio/Factura/documentos/honorarios_servicios_contables.pdf"
curl -L -o sat_ejemplo_servicios_profesionales.pdf "http://m.sat.gob.mx/informacion_fiscal/factura_electronica/Documents/cfdi/Ejemplos%20de%20facturas%2033/ejemplo_serv_profesionales.pdf"
curl -L -o sat_factura_publica_gob.pdf "https://www.gob.mx/cms/uploads/attachment/file/293173/SANCHEZ_ROMEA_LUIS_ALFREDO_DEL_22_AL_23_DE_NOVIEMBRE_COMPROBANTE_9.pdf"

# Transparencia gubernamental (CFDIs reales emitidos a dependencias)
curl -L -o cfdi_cfe_pachuca_2024.pdf "https://portales-transparencia.cfe.mx/distribucion/28%20Procedimientos%20de%20Contratacin/Centro%20Oriente/Pachuca/2024/9400110212_FACTURA.pdf"
curl -L -o cfdi_inea_2024.pdf "http://www.inea.gob.mx/transparencia/sipot/fraccion_IX/2024/80009.pdf"
curl -L -o cfdi_scjn_2024.pdf "https://www.scjn.gob.mx/sites/default/files/fix/2024/04/CCST-007-2024%20VP%20st.pdf"
curl -L -o cfdi_scjn_dgpasc_2024.pdf "https://www.scjn.gob.mx/sites/default/files/fix/2024/02/DGPASCVG-003-2024%20VP%20st.pdf"
curl -L -o cfdi_cenace_2024.pdf "https://www.cenace.gob.mx/Docs/Transparencia/ProcLicPub/2024/GCA%20CENTRO%20ALTERNO/_IA-18-TOM-018TOM999-N-2-2024_partida%204/Archivo%207.pdf"
curl -L -o cfdi_seg_guanajuato_2024.pdf "https://transparencia.seg.guanajuato.gob.mx/2024/3ERTRIM2024/F_28/DA/Facturas4509161604.pdf"
```

## Invoices internacionales (foreign/) — PENDIENTE

**No se encontraron PDFs públicos reales de invoices internacionales.** Razones:
- Los invoices privados de freelancers (Upwork, Fiverr, Toptal, Deel) no son públicos
- Servicios SaaS (AWS, Stripe, GitHub) generan invoices pero solo accesibles desde la cuenta del cliente
- Solo hay templates en blanco online, no datos reales

### Cómo conseguir samples

Para soportar invoices extranjeros vas a necesitar:

1. **Pedirle a tus primeros usuarios** que compartan 2-3 invoices recientes (anonimizando datos sensibles)
2. **Tus propios invoices** si recibes pagos internacionales (Stripe Atlas, Wise, Payoneer, etc.)
3. **GitHub repos públicos** de procesadores de invoices que a veces incluyen samples — buscar `github.com sample invoice pdf`

### Tipos de invoices que vas a recibir

Pensar en variedad antes de empezar el parser:
- **Servicios SaaS US** (Adobe, Notion, Slack, Figma): formato estándar, suele tener tabla simple
- **Hosting** (AWS, Azure, GCP, DigitalOcean): muy diferentes entre sí
- **Marketing tools** (Mailchimp, ConvertKit): formato corto, suele ser solo línea total
- **Freelancers** (USD/EUR): formato muy variable, cada uno hace el suyo
- **Agencies** (multi-línea, detalle por servicio): los más complejos

## Recomendación de enfoque

Antes de hacer parser custom de invoices internacionales, considera:

1. **CFDI primero**: el 90% de tus usuarios mexicanos solo necesitan parsear CFDI. Y el XML lo da casi parseado. Enfócate ahí.
2. **Foreign invoices con OCR + LLM**: como son tan heterogéneos, un parser determinista NO escala. Mejor: usar OCR (pdfplumber/Textract) para extraer texto, mandar a Claude API/GPT con prompt estructurado, USER REVISA antes de guardar. Más costoso pero único enfoque viable para formatos infinitos.
3. **Excel/CSV manual** mientras tanto: para invoices extranjeros, dar opción de subir Excel manual ya existe en el portal.
