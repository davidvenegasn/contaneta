# Mapa de scripts legacy → migraciones equivalentes

Los scripts `db_migrate_*.py` que estaban en la raíz del proyecto han sido **deprecados** y movidos a `scripts/legacy/`. No deben ejecutarse: la única fuente de verdad para el schema y las migraciones es:

- **`migrations/*.sql`** (aplicadas en orden por `migrations_runner.apply_migrations()`)
- **Lógica Python** inline en `migrations_runner.py` (versiones 003, 004, 006, 008, 011, 014, 016)

Este documento indica qué migración o comportamiento cubre cada script legacy.

---

## Script → equivalencia

| Script legacy | Ubicación actual | Equivalente |
|---------------|------------------|-------------|
| `db_migrate_001_sat_xml.py` | `scripts/legacy/` | **001_baseline.sql** + runner: columnas `sat_cfdi` (xml_sha256, xml_downloaded_at, parsed_at, parse_version), tabla `sat_jobs` e índices. |
| `db_migrate_002_add_xml_path.py` | `scripts/legacy/` | **001_baseline.sql**: columna `sat_cfdi.xml_path` ya en baseline. |
| `db_migrate_003_sat_requests.py` | `scripts/legacy/` | **001_baseline.sql**: tabla `sat_requests`; lógica idempotente en **migrations_runner** (003). |
| `db_migrate_004_add_cfdi_fields.py` | `scripts/legacy/` | **001_baseline.sql** + **migrations_runner** (004): columnas serie, folio, forma_pago, metodo_pago, uso_cfdi, subtotal, descuento, impuestos, lugar_expedicion, condiciones_pago, xml_status; índices. |
| `db_migrate_005_merge_cfdi_duplicates.py` | `scripts/legacy/` | **Solo datos (one-off)**. Merge de duplicados por UUID y copia de subtotal/impuestos/xml_path. No hay migración equivalente; ejecutar manualmente solo si se necesita en una DB existente. |
| `db_migrate_006_add_buga_mobj.py` | `scripts/legacy/` | **Solo datos (one-off)**. Inserta issuers BUGA/MOBJ, sat_credentials, issuer_tokens. No reemplazable por migraciones de schema. |
| `db_migrate_006_add_concepto.py` | `scripts/legacy/` | **001_baseline.sql** + **migrations_runner** (006): columna `sat_cfdi.concepto`. |
| `db_migrate_007_customer_supplier_profiles.py` | `scripts/legacy/` | **001_baseline.sql**: tablas `customer_profiles` y `supplier_profiles` (zip, tax_system nullable). |
| `db_migrate_008_issuer_regimen_fiscal.py` | `scripts/legacy/` | **001_baseline.sql**: columna `issuers.regimen_fiscal`. Los UPDATE por RFC (GAZD, BUGA, MOBJ) son **solo datos**; no están en migraciones. |
| `db_migrate_008_products.py` | `scripts/legacy/` | **001_baseline.sql**: tabla `issuer_products` e índice. |
| `db_migrate_008_retenciones.py` | `scripts/legacy/` | **001_baseline.sql**: columna `sat_cfdi.retenciones`. |
| `db_migrate_009_sat_cfdi_list_indexes.py` | `scripts/legacy/` | **001_baseline.sql** tiene `idx_sat_cfdi_issuer_dir_fecha`; **017_sat_cfdi_issuer_uuid_index.sql** añade `idx_sat_cfdi_issuer_uuid` (issuer_id, uuid). |
| `db_migrate_add_david_venegas.py` | `scripts/legacy/` | **Solo datos (one-off)**. Inserta issuer David Venegas (VEND980918UR1) y token. |
| `db_migrate_customer_profiles_nullable.py` | `scripts/legacy/` | **001_baseline.sql**: `customer_profiles` ya define zip y tax_system como nullable. |
| `db_migrate_set_sat_ok_diego_carolina.py` | `scripts/legacy/` | **Solo datos (one-off)**. Pone `validation_ok = 1` en sat_credentials para GAZD y BUGA. Columnas validation_* están en **migrations/014** y runner. |

---

## Resumen

- **Schema:** Todo el schema de estos scripts está cubierto por **migrations/001_baseline.sql** (y, donde aplica, por la lógica idempotente en **migrations_runner.py** para 003, 004, 006, 008, 011, 014, 016).
- **Índice adicional:** El índice `(issuer_id, uuid)` que añadía el script 009 está cubierto por **migrations/017_sat_cfdi_issuer_uuid_index.sql**.
- **Datos one-off:** 005 (merge duplicados), 006_add_buga_mobj, add_david_venegas, set_sat_ok_diego_carolina y los UPDATE por RFC de 008_issuer_regimen_fiscal son **solo datos**; no forman parte del sistema de migraciones. Si se necesitan en un entorno concreto, ejecutar manualmente (o adaptar) los scripts en `scripts/legacy/` con cuidado.
