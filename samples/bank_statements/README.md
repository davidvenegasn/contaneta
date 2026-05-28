# Muestras de estados de cuenta bancarios

PDFs públicos descargados desde portales de transparencia gubernamentales mexicanos. Se usan como referencia para desarrollar y testear parsers de PDFs bancarios.

**Los PDFs NO se versionan en git** (ver `.gitignore`). Si los necesitas, descárgalos con el script de abajo o desde las URLs listadas.

## Estado actual

| Banco | Archivos | % Mercado MX aprox | Parser | Notas |
|---|---|---|---|---|
| Banorte | 3 | ~15% | ✅ Implementado | Funciona en producción |
| BBVA | 4 | ~25% | ⏳ Pendiente | **Alta prioridad** — mayor cuota de mercado |
| Santander | 3 | ~13% | ⏳ Pendiente | Alta prioridad |
| Citibanamex | 3 | ~12% | ⏳ Pendiente | Alta prioridad |
| HSBC | 3 | ~7% | ⏳ Pendiente | Media prioridad |
| Scotiabank | 3 | ~5% | ⏳ Pendiente | Media prioridad |
| BanBajío | 3 | ~3% | ⏳ Pendiente | Baja prioridad |
| Inbursa | 1 | ~4% | ⏳ Pendiente | Baja prioridad — solo 1 muestra |
| Banco Azteca | 3 | ~3% | ⏳ Pendiente | Baja prioridad |
| Banregio | 3 | ~1% | ⏳ Pendiente | Baja prioridad |
| Mifel | 1 | <1% | ⏳ Pendiente | Solo 1 muestra |

## Bancos digitales — pendientes (no hay PDFs públicos)

Estos bancos no tienen presencia en portales de transparencia porque el gobierno no usa cuentas digitales. Para soportarlos hay que conseguir PDFs de usuarios reales (anonimizados):

- Hey Banco
- Nubank México
- Stori
- Mercado Pago
- Klar
- Albo
- RappiCuenta

## Cómo re-descargar los PDFs

```bash
bash samples/bank_statements/download.sh
```

(Script abajo, también ejecutable con curl + URLs listadas).

## Fuentes (URLs públicas)

### BBVA
- [Jalisco 2022-01](https://transparencia.info.jalisco.gob.mx/sites/default/files/8FVX-2022-01-Estado%20de%20cuenta.pdf)
- [Jalisco 2021-05](https://transparencia.info.jalisco.gob.mx/sites/default/files/ESTADOS%20DE%20CTA%20BBVA%20MAYO%202021.pdf)
- [Coahuila 2016](https://www.sefincoahuila.gob.mx/contenido/docs/cuentapublica/2016/07%20Caratulas%20Bancarias%2002/BBVA%20BANCOMER%202016/MAS%20DE%201000/0446533647/ESTADO%20DE%20CUENTA.pdf)
- [BBVA Fondos de Inversión (doc oficial)](https://www.bbva.mx/content/dam/public-web/mexico/documents/empresas/fondos/home-fondos-de-inversion/do_4_Estado_de_cuenta_tcm1344-627429.pdf)

### Banorte
- [Guadalajara 2024](https://transparencia.guadalajara.gob.mx/sites/default/files/8176-BANORTE-2024.pdf)
- [SEAPAL Abril 2024](https://www.seapal.gob.mx/docs/transparencia_opd/Banorte-Abr-2024.pdf)
- [DIF Zapopan Noviembre 2024](https://t.difzapopan.gob.mx/8/V/x/2024/11.-%20Estados%20de%20cuenta%20bancarios%20Noviembre%202024/BANORTE%20CONCENTRADORA%201550%20NOVIEMBRE%202024.pdf)

### Santander
- [Puerto Vallarta Mayo 2024](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/SANTANDER/05.MAY/SANTANDER%20MAYO%202024%20CTA%2065505885624.pdf)
- [Puerto Vallarta Marzo 2025](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2025/SANTANDER/03.MAR/65-50899771-4.pdf)
- [Guadalajara Agosto 2021](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioSantanderAgosto21.pdf)

### Citibanamex
- [Puerto Vallarta Febrero 2024](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/banamex/02.FEB/CITIBANAMEX%20FEBRERO%202024%20002375701454068604.pdf)
- [SEAPAL Febrero 2026](https://www.seapal.gob.mx/docs/transparencia_opd/Banamex-feb.pdf)
- [Puerto Vallarta Abril 2023](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2023/marzo-abril/CUENTA%207005%206913430%20BANAMEX%20Abril.pdf)

### HSBC
- [TriEjal Agosto 2019](https://www.triejal.gob.mx/transparencia/banco/HSBCSP-INST_ago2019.pdf)
- [SEAPAL HSBC](https://www.seapal.gob.mx/docs/transparencia_opd/HSBC.pdf)
- [Tlaquepaque Mayo 2013](https://transparencia.tlaquepaque.gob.mx/wp-content/uploads/2016/01/Estado-de-cuenta-bancario-HSBC-Mayo-2013.pdf.pdf)

### Scotiabank
- [SEAPAL Marzo](https://www.seapal.gob.mx/docs/transparencia_opd/Scotiabank-Marzo.pdf)
- [Puerto Vallarta Enero 2024](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/SCOTIABANK/01.Ene/SCOTIABANK%20ENERO%202024%20044375256032701744.pdf)
- [Guadalajara Agosto 2021](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioScotiabankAgosto21.pdf)

### BanBajío
- [Tlaquepaque Abril 2024](https://apitransparencia.tlaquepaque.gob.mx/assets/biblioteca/c7133d955588468d416d8f0abe5b62fd.pdf)
- [Guadalajara Agosto 2021](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanBajioAgosto21.pdf)
- [Guadalajara Abril 2019](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanBajioAbril19.pdf)

### Inbursa
- [CDMX 2018 (censurado)](http://transparencia.finanzas.cdmx.gob.mx/repositorio/public/upload/repositorio/PLANEACION_FINANCIERA/ART_121/FRACC_XXIX/CRITERIO_22/INBURSA%20MSI%202018_Censurado.pdf)

### Banco Azteca
- [SEAPAL Febrero 2025](https://www.seapal.gob.mx/docs/transparencia_opd/Azteca.pdf)
- [SEAPAL Febrero 2024](https://www.seapal.gob.mx/docs/transparencia_opd/Azteca-Feb-2024.pdf)
- [Guadalajara Abril 2022](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBancoAztecaAbril22.pdf)

### Banregio
- [Guadalajara Octubre 2021](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanregioOctubre21.pdf)
- [Guadalajara Abril 2021](https://transparencia.guadalajara.gob.mx/sites/default/files/EstadoCuentaBancarioBanregioAbril21.pdf)
- [Tlajomulco Junio 2020](https://www.tlajomulco.gob.mx/sites/default/files/transparencia/estados_de_cuenta/133031510015al30junio2020.pdf)

### Mifel
- [Puerto Vallarta Noviembre 2024](https://transparencia.puertovallarta.gob.mx/transparenciaY/art8/V/estados-cuenta/2024/MIFEL/11.NOV/01600738840.pdf)

## Limitaciones a considerar

1. **Son cuentas de gobierno**, no personales. Estructura del PDF debería ser igual (mismo template del banco), pero pueden faltar secciones que sí aparecen en cuentas personales (ej. tarjetas de crédito vinculadas, promociones).
2. **Algunos PDFs son viejos** (2013, 2016, 2018). Los bancos a veces cambian su template — preferir los más recientes para parsers nuevos.
3. **HSBC SEAPAL pesa 17MB** — probablemente es un PDF de muchas páginas con muchos movimientos. Bueno para stress-test.
4. **Inbursa solo tiene 1 muestra** — buscar más antes de hacer parser robusto.

## Cómo usar para desarrollar un parser

1. Abre 1 PDF del banco objetivo y revísalo visualmente para identificar:
   - Encabezados de tabla (Fecha / Concepto / Monto / Saldo)
   - Formato de fecha (DD-MMM-YY vs DD/MM/YYYY)
   - Cómo se separan depósitos vs retiros (¿dos columnas o un solo monto con signo?)
   - Texto fijo que delimita la sección de movimientos
2. Usa pdfplumber para extraer texto y ver cómo queda:
   ```python
   import pdfplumber
   with pdfplumber.open("samples/bank_statements/bbva/bbva_jalisco_2022_01.pdf") as pdf:
       for page in pdf.pages:
           print(page.extract_text())
   ```
3. Diseña regex específicos siguiendo el patrón de `services/bank/bank_statement_parser.py` (parser Banorte existente).
4. Agrega tests con el PDF como fixture.
