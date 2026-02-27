## `storage/` (no se versiona)

Este directorio contiene archivos **generados** por la app (por ejemplo XML/PDF descargados, exportaciones, etc.).

- **Desarrollo**: puedes usar `storage/` localmente (se ignora en git).
- **Producción**: monta `storage/` como **volumen fuera del repo** (por ejemplo en `/var/lib/...` o un bucket/FS) y asegúrate de que el proceso tenga permisos de lectura/escritura.

Notas:
- No guardar aquí llaves/certificados. Eso va en `keys/` (también fuera de git).
