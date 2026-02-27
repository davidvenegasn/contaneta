## Migraciones (SQLite)

La documentación principal de migraciones vive en `MIGRATIONS.md` (raíz del repo).

Este archivo existe para mantener el índice de docs consistente bajo `docs/`.

### Enlaces
- `MIGRATIONS.md`: cómo funciona `migrations_runner.py`, cómo crear/probar migraciones, y listado de migraciones.

# Migraciones (SQLite)

Este proyecto usa migraciones SQL en `migrations/*.sql` aplicadas automáticamente al arrancar el servidor (startup).

El runner es `migrations_runner.py` y mantiene el estado en la tabla `schema_migrations` dentro de `invoicing.db`.

## Cómo agregar una migración

- **Crea un archivo** en `migrations/` con el formato:
  - `NNN_descripcion.sql` (ej. `024_jobs.sql`)
  - `NNN` debe ser un número incremental (con ceros a la izquierda).
- **Escribe SQL idempotente cuando sea posible**:
  - Usa `CREATE TABLE IF NOT EXISTS ...`
  - Usa `CREATE INDEX IF NOT EXISTS ...`
  - Para columnas nuevas, preferir `ALTER TABLE ... ADD COLUMN ...` (SQLite).
- **No cambies migraciones ya publicadas** si existe la posibilidad de que una DB real ya las haya aplicado.

## Cómo se corren las migraciones

- **Automático**: al arrancar `uvicorn app:app`, se llama `apply_migrations(DB_PATH)` en el evento `startup`.
- **Manual (admin)**: en el panel `admin/ops` existe una acción de “migrations” que vuelve a correr el runner.

## Qué pasa si arrancan 2 procesos a la vez

El runner usa `BEGIN IMMEDIATE` para adquirir un lock de escritura y **evitar condiciones de carrera** (dos procesos aplicando lo mismo).
Si la base está bloqueada, reintenta un par de veces y luego falla con un error claro.

## Rollback (manual)

SQLite no soporta rollback automático de migraciones a nivel “framework” en este proyecto. Si una migración salió mal:

- **Opción preferida**: restaurar desde backup del archivo `invoicing.db`.
- **Si no hay backup**:
  - Identifica el cambio (tabla/columna/índice) introducido por la migración.
  - Aplica un SQL inverso manual (si es posible).
  - Si necesitas “eliminar una columna” (SQLite no lo soporta directamente), normalmente requiere recrear la tabla y copiar datos.

Recomendación operativa: antes de desplegar cambios con migraciones, genera un backup de DB y del storage.

## Qué hacer si falla en producción

1. **Revisa logs**: el error indica el archivo exacto de migración que falló.
2. **No reinicies en bucle**: un restart loop no arregla una migración rota.
3. **Restaura DB desde backup** si la DB quedó en estado inconsistente.
4. **Aplica un hotfix**:
   - Si la migración puede hacerse idempotente, corrígela en una nueva migración (ej. `025_fix_...sql`) en lugar de editar la anterior.
5. **Verifica**:
   - `/health` y `/ready`
   - `SELECT version FROM schema_migrations ORDER BY version;`

# Migraciones — fuente única de verdad

El schema y las migraciones se gestionan **solo** por:

- **`migrations/*.sql`** — archivos numerados (001_, 002_, …) aplicados en orden.
- **`migrations_runner.py`** — aplica las migraciones al arranque de la app y contiene lógica Python inline para versiones que lo requieren (003, 004, 006, 008, 011, 014, 016, 021, 023).

**No** uses scripts `db_migrate_*.py` que estén en `scripts/legacy/`: están deprecados y no forman parte del flujo oficial. Ver `scripts/legacy/README.md`.

---

## Flujo oficial

1. **Aplicar migraciones:** Se ejecutan automáticamente al arrancar la app (`app.py` → `apply_migrations(DB_PATH)`). No hace falta correr ningún script a mano.
2. **Crear una migración nueva:** Ver **[MIGRATIONS.md](../MIGRATIONS.md)** en la raíz del proyecto:
   - Crear `migrations/NNN_descripcion.sql` con el siguiente número.
   - Usar SQL idempotente (`IF NOT EXISTS`, etc.) o coordinar con lógica en `migrations_runner.py` si hace falta `_safe_add_column()`.
3. **Validar:** Arrancar la app con una DB limpia o una copia de DB existente y comprobar que no hay errores; opcionalmente `python scripts/check_db.py`.

---

## Cómo validar que no se dupliquen ni salten migraciones

- La tabla `schema_migrations` registra cada versión aplicada. El runner **nunca** re-ejecuta una versión ya registrada.
- No modificar archivos ya aplicados; solo añadir nuevos `NNN_*.sql` con números consecutivos (o el siguiente disponible).
- Si necesitas lógica que antes estaba en un script legacy, **mígrala** a una nueva migración numerada en `migrations/` (o a una función en `migrations_runner.py` para esa versión) en lugar de ejecutar el script antiguo.
