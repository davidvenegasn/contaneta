# Scripts legacy (deprecados)

Estos scripts estaban en la raíz del proyecto como `db_migrate_*.py` y han sido deprecados.

**⚠️ WARNING: No ejecutar en producción ni como fuente de schema.** La única fuente de verdad para el schema y migraciones es:

- `migrations/*.sql` (aplicadas en orden por `migrations_runner.apply_migrations()`)
- Lógica Python inline en `migrations_runner.py` (versiones 003, 004, 006, 008, 011, 014, 016)

Ver **MIGRATION_LEGACY_MAP.md** en la raíz del proyecto para la relación script → migración equivalente.
