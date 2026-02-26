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
