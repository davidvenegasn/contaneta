# Migraciones SQLite

El schema de la base de datos se define **únicamente por migraciones** en `migrations/*.sql`. La app ejecuta `apply_migrations(DB_PATH)` al arrancar. No se usa `db_init.py` ni scripts de seed en producción.

**Aliases de desarrollo:** para cargar `migrate`, `checkdb` y `run` en la sesión actual (bash o zsh):
```bash
source scripts/dev_aliases.sh
```
Desde cualquier carpeta: `source /ruta/al/proyecto/scripts/dev_aliases.sh`

---

## Cómo funciona migrations_runner.py

- **Entrada:** `apply_migrations(db_path, migrations_dir=None)` se llama desde `app.py` en el evento de startup.
- **Orden:** Lista archivos `migrations/NNN_nombre.sql` ordenados por prefijo numérico (001, 002, 003…).
- **Control:** La tabla `schema_migrations(version, applied_at)` registra qué versiones ya se aplicaron.
- **Idempotencia:** Si la versión está en `schema_migrations`, se salta (`Skipping NNN (already applied).`).
- **Ejecución:** Para cada migración pendiente:
  - Se abre una transacción (`BEGIN IMMEDIATE`).
  - Se ejecuta el SQL del archivo **o** la lógica especial (p. ej. 003 usa `_apply_003_safe_add_columns()`, 004 usa `_apply_004_optional_columns_and_constraints()`).
  - Se inserta la versión en `schema_migrations` y se hace commit.
- **Pragmas:** Todas las conexiones usan `PRAGMA foreign_keys = ON`, `PRAGMA busy_timeout = 5000`, `PRAGMA journal_mode = WAL`.
- **Helpers:** `_column_exists()`, `_safe_add_column()` permiten ADD COLUMN idempotente para migraciones que lo necesiten.

---

## Cómo crear una migración nueva (004_, 005_, …)

1. **Crear el archivo** en `migrations/` con nombre `NNN_descripcion.sql` (NNN = siguiente número, ej. `004_add_foo.sql`).
2. **Contenido:** SQL válido para SQLite. Usar `CREATE TABLE IF NOT EXISTS`, `CREATE INDEX IF NOT EXISTS` o `ALTER TABLE ... ADD COLUMN` según convenga.
3. **Idempotencia:** Si usas `ALTER TABLE ADD COLUMN` y la columna puede ya existir, en SQLite no hay `IF NOT EXISTS` para columnas; opciones:
   - Usar solo sentencias que no fallen si ya existen (p. ej. `CREATE INDEX IF NOT EXISTS`).
   - O pedir que se añada lógica especial en el runner (como en 003) usando `_safe_add_column()`.
4. **Probar:** Arrancar la app con una DB que no tenga la versión aplicada y comprobar que aplica; volver a arrancar y comprobar que dice `Skipping NNN (already applied).`.

---

## Cómo probar migraciones

### A) DB desde cero

1. Borrar o renombrar la DB para empezar limpio:
   ```bash
   mv invoicing.db invoicing.db.bak   # o rm invoicing.db
   ```
2. Arrancar la app:
   ```bash
   uvicorn app:app --reload
   ```
3. Debe aparecer `Applying 001…`, `Applying 002…`, etc., y al final la app sirve requests. No debe haber errores "no such table" o "no such column".
4. Verificar:
   ```bash
   python scripts/check_db.py
   ```

### B) DB vieja (existente)

1. Usar una copia de una DB ya usada (p. ej. producción o desarrollo):
   ```bash
   cp invoicing.db invoicing_old.db
   export APP_DB_PATH="$(pwd)/invoicing_old.db"
   ```
2. Arrancar la app. Debe aplicar solo las migraciones pendientes (ej. `Skipping 001`, `Skipping 002`, `Applying 003…` si 003 no estaba aplicada).
3. Confirmar que no se re-aplican versiones ya aplicadas y que no hay errores "no such column/table" al usar el portal.
4. Opcional: `python scripts/check_db.py` antes y después.

---

## Prueba manual con una DB existente (detalle)

Sigue estos pasos para validar que las migraciones funcionan correctamente con una base ya existente (por ejemplo una copia de producción o desarrollo).

### 1. Preparar una copia de la DB existente

```bash
# Ejemplo: usar una copia como "DB antigua" para no tocar la original
cp invoicing.db invoicing_old.db
```

O bien usa cualquier archivo `.db` existente que quieras probar (por ejemplo `invoicing_old.db`).

### 2. Apuntar la app a esa DB

```bash
export APP_DB_PATH="$(pwd)/invoicing_old.db"
```

En Windows (PowerShell):

```powershell
$env:APP_DB_PATH = "$(Get-Location)\invoicing_old.db"
```

### 3. (Opcional) Verificar el estado de la DB antes de arrancar

```bash
python scripts/check_db.py
```

Deberías ver la lista de tablas críticas, las columnas de `issuers` (incluyendo si existe `facturapi_org_id`) y conteos de filas. Si falta la tabla `schema_migrations` o la columna `facturapi_org_id`, las migraciones las crearán/añadirán al arrancar.

### 4. Arrancar la app

```bash
uvicorn app:app --reload
```

O el comando que uses normalmente (por ejemplo `./run_server.sh` asegurándote de que `APP_DB_PATH` esté definido).

### 5. Confirmar que NO se re-aplica 001 si ya está aplicada

- Si la DB **nunca** tuvo migraciones: en la salida del arranque deberías ver algo como:
  - `Applying 001…`
  - `Applying 001… done.`
- Si la DB **ya** tenía la migración 001 aplicada (existe `schema_migrations` con `version = '001'`): en la salida deberías ver:
  - `Skipping 001 (already applied).`
- **No** debe aparecer dos veces "Applying 001… done." al arrancar dos veces seguidas; la segunda vez debe decir "Skipping 001 (already applied)."

### 6. Confirmar que no hay errores "no such column" / "no such table"

- Abre el portal en el navegador (por ejemplo `/portal/home?token=demo`).
- Navega por las secciones que usan DB: inicio, facturas emitidas/recibidas, cotizaciones, clientes, productos, etc.
- Revisa la consola donde corre uvicorn: **no** debe aparecer errores como:
  - `no such column: facturapi_org_id`
  - `no such table: invoices`
  - `no such table: schema_migrations`
- Si la DB era muy antigua y le faltaban tablas/columnas, la migración 001 las crea al primer arranque; tras eso, no deberían producirse esos errores.

### 7. (Opcional) Verificar el estado de la DB después de arrancar

```bash
python scripts/check_db.py
```

Comprueba que:
- Existe la tabla `schema_migrations` y tiene al menos una fila con `version = '001'`.
- La tabla `issuers` tiene la columna `facturapi_org_id`.
- Las tablas críticas listadas por el script están presentes.

---

## Resumen de validación

| Paso | Qué comprobar |
|------|----------------|
| 1–2 | DB existente y `APP_DB_PATH` apuntando a ella |
| 3 | `check_db.py` muestra tablas/columnas (o avisa lo que falta) |
| 4 | App arranca sin fallo |
| 5 | Según el caso: "Applying 001… done." una vez, o "Skipping 001 (already applied)." si ya estaba aplicada |
| 6 | Uso del portal sin errores "no such column/table" en consola |
| 7 | `check_db.py` confirma `schema_migrations`, `issuers.facturapi_org_id` y tablas críticas |

---

## Cómo funciona el sistema de migraciones

- **Tabla de control:** `schema_migrations(version TEXT PRIMARY KEY, applied_at TEXT)`.
- **Archivos:** `migrations/001_baseline.sql`, `migrations/002_*.sql`, etc., ordenados por prefijo numérico.
- **Idempotencia:** Si la versión ya está en `schema_migrations`, no se vuelve a ejecutar.
- **Ejecución:** Al inicio de la app (`app.py` startup) se llama a `apply_migrations(DB_PATH)`.

---

## Migraciones disponibles

### 001_baseline.sql
Crea todas las tablas necesarias para que la app arranque desde cero. Incluye todas las tablas críticas: `issuers`, `issuer_tokens`, `sat_cfdi`, `sat_credentials`, `customer_profiles`, `supplier_profiles`, `issuer_products`, `quotations`, `quotation_items`, `invoices`, `invoice_items`, `payment_relations`, etc.

### 002_add_facturapi_org_id.sql
Asegura que la tabla `issuers` tenga la columna `facturapi_org_id TEXT`. Usa un workaround seguro (crear tabla nueva, copiar datos, renombrar) porque SQLite no soporta `ADD COLUMN ... IF NOT EXISTS`.

### 003_ensure_columns_crash.sql
Asegura columnas críticas que causan "no such column" si faltan en DBs antiguas. **Ejecutada con lógica Python segura** que verifica existencia antes de agregar:

- **sat_cfdi** (12 columnas): `serie`, `folio`, `forma_pago`, `metodo_pago`, `uso_cfdi`, `subtotal`, `descuento`, `impuestos`, `concepto`, `retenciones`, `tipo_comprobante`, `xml_status`
- **invoices** (1 columna): `issue_date`

Todas las columnas se agregan como nullable para no romper datos existentes. La migración es completamente idempotente: si una columna ya existe, se omite sin error.

### 004_optional_columns_and_constraints.sql
Asegura compatibilidad y calidad sin romper DBs viejas. **Ejecutada con lógica Python** (`_apply_004_optional_columns_and_constraints`):

- **A) invoices:** Añade si faltan: `export_code`, `tipo_comprobante`, `series`, `folio_number`, `order_ref`, `notes`, `status`, `cancelled` (INTEGER DEFAULT 0).
- **B) invoice_items:** Añade si faltan: `unit_key TEXT`, `discount REAL`.
- **C) customer_profiles:** Si `zip` o `tax_system` son NOT NULL, reconstruye la tabla con ambas nullable (sin perder datos). Tabla temporal `customer_profiles_new` se limpia al inicio con `DROP TABLE IF EXISTS` para reintentos.
- **D) Índices:** `CREATE INDEX IF NOT EXISTS` para `idx_invoices_issuer_uuid`, `idx_invoices_issuer_payment_method`, `idx_invoices_issuer_issue_date`.

Idempotente y reintentable; compatible con DB nueva y vieja.

---

## Hardening SQLite (timeout, pragmas, WAL)

Para reducir errores de tipo "disk I/O" y "database is locked":

- **Conexiones:** Todas usan `sqlite3.connect(DB_PATH, timeout=30)` (o equivalente en `migrations_runner.py`).
- **Pragmas al abrir:** En cada conexión se ejecutan:
  - `PRAGMA foreign_keys = ON;`
  - `PRAGMA busy_timeout = 5000;` (esperar hasta 5 s antes de fallar por lock)
  - `PRAGMA journal_mode = WAL;` (modo Write-Ahead Logging: mejor concurrencia, menos bloqueos).
- **Migraciones:** En `apply_migrations` se usa `BEGIN IMMEDIATE` para adquirir el lock de escritura de inmediato y evitar carreras con otras conexiones.

Con WAL activo, SQLite crea junto al archivo `.db` los archivos **`.db-wal`** (log de escrituras) y **`.db-shm`** (índice compartido). Son normales y no deben borrarse con la app en marcha.

### Qué hacer si aparece error WAL/SHM

Si ves "database is locked", "disk I/O error" o "database disk image is malformed" y sospechas de los archivos WAL:

1. **Detener la app** por completo.
2. **Mover** (no borrar sin respaldo) los auxiliares para que SQLite arranque solo con el `.db`:
   ```bash
   mv invoicing.db-wal invoicing.db-wal.off 2>/dev/null || true
   mv invoicing.db-shm invoicing.db-shm.off 2>/dev/null || true
   ```
3. **Reiniciar** la app; se recrearán `.db-wal` y `.db-shm` vacíos.
4. Si usas `APP_DB_PATH`, sustituye `invoicing` por el nombre de tu archivo (ej. `invoicing_old.db-wal`).

Si el `.db` principal está corrupto, restaura desde un backup. Ver sección siguiente para más detalle.

---

## Recuperación si .db-wal / .db-shm están dañados

Si aparecen errores de "disk I/O" o "database disk image is malformed" y sospechas que los archivos WAL están dañados:

1. **Detener la aplicación** por completo (no debe haber ningún proceso leyendo/escribiendo la DB).
2. **Hacer copia de seguridad** de la base y de los archivos WAL:
   ```bash
   cp invoicing.db invoicing.db.bak
   cp invoicing.db-wal invoicing.db-wal.bak 2>/dev/null || true
   cp invoicing.db-shm invoicing.db-shm.bak 2>/dev/null || true
   ```
3. **Mover los archivos WAL dañados** (para que SQLite deje de usarlos y arranque "en frío" con solo el `.db`):
   ```bash
   mv invoicing.db-wal invoicing.db-wal.off 2>/dev/null || true
   mv invoicing.db-shm invoicing.db-shm.off 2>/dev/null || true
   ```
   Si prefieres no mover, puedes borrarlos **solo** tras haber detenido la app; SQLite intentará recuperar el estado desde el `.db` (puede haber pérdida de transacciones recientes no volcadas).
4. **Reiniciar la aplicación.** Al abrir la DB de nuevo se recrearán `.db-wal` y `.db-shm` vacíos.
5. Si el `.db` principal también está corrupto, tendrás que restaurar desde un backup anterior (por ejemplo `invoicing.db.bak` o tu copia de respaldo habitual).

**Nota:** Si usas `APP_DB_PATH`, sustituye `invoicing.db` por el path que tengas configurado (por ejemplo `invoicing_old.db`).

---

## Uso de los scripts de utilidad

Para evitar caos con `.db-wal`/`.db-shm` y para cambiar de DB sin borrar nada (solo renombrar/mover):

- **Limpiar auxiliares WAL/SHM** (mueve `invoicing.db-wal` e `invoicing.db-shm` a `sqlite_aux_backup/` con timestamp):
  ```bash
  ./scripts/sqlite_cleanup_aux.sh
  ```

- **Activar la DB antigua** (la app usará lo que estaba en `invoicing_old.db`; antes ejecuta el cleanup):
  ```bash
  ./scripts/switch_db.sh --use-old
  ```

- **Revertir a la DB nueva** (volver a usar la DB que estaba como `invoicing.db` antes de `--use-old`):
  ```bash
  ./scripts/switch_db.sh --use-new
  ```

Ejecuta los scripts desde la raíz del proyecto. No borran nada; solo crean `sqlite_aux_backup/` y renombran/mueven archivos.

---

## Cómo correr migraciones en producción (modo manual)

En producción, puedes aplicar migraciones **sin levantar uvicorn** usando el script `run_migrations.py`:

### 1. Ejecutar migraciones manualmente

```bash
# Con DB por defecto (invoicing.db en la raíz del proyecto)
python scripts/run_migrations.py

# Con DB personalizada (usando APP_DB_PATH)
APP_DB_PATH=/ruta/a/produccion.db python scripts/run_migrations.py
```

El script aplica todas las migraciones pendientes y muestra qué versiones se aplicaron o se saltaron. Si hay errores, el script termina con código de salida 1.

### 2. Verificar estado antes/después

```bash
# Verificar estado de la DB
python scripts/check_db.py

# O con DB personalizada
APP_DB_PATH=/ruta/a/produccion.db python scripts/check_db.py
```

### 3. Aliases útiles para desarrollo

Para facilitar el uso durante desarrollo, puedes cargar los aliases (funciona con `source` en **bash** y **zsh**; ejecuta desde la raíz del proyecto):

```bash
# Cargar aliases temporalmente (solo en esta sesión)
source scripts/dev_aliases.sh

# Luego usar:
migrate    # Ejecutar migraciones
checkdb    # Verificar estado de la DB
run        # Arrancar servidor de desarrollo
```

O copiar el contenido de `scripts/dev_aliases.sh` a tu `~/.bashrc` o `~/.zshrc` para uso permanente.

### Flujo recomendado en producción

1. **Detener la aplicación** (asegúrate de que no haya procesos usando la DB).
2. **Hacer backup de la DB**:
   ```bash
   cp invoicing.db invoicing.db.backup.$(date +%Y%m%d_%H%M%S)
   ```
3. **Limpiar auxiliares WAL/SHM** (opcional pero recomendado):
   ```bash
   ./scripts/sqlite_cleanup_aux.sh
   ```
4. **Ejecutar migraciones**:
   ```bash
   python scripts/run_migrations.py
   ```
5. **Verificar estado**:
   ```bash
   python scripts/check_db.py
   ```
6. **Reiniciar la aplicación**.
