# Cómo volver a la versión anterior (rollback)

Guía para el dueño del proyecto: revertir a una versión anterior usando **git tags** después de un lanzamiento problemático.

---

## 1. Crear un tag antes de cada lanzamiento

Siempre que vayas a desplegar una versión nueva, crea un tag. Así podrás volver a ese punto exacto.

**Comandos (copy/paste):**
```bash
cd /ruta/del/proyecto
git tag -a v1.0-20260218 -m "Lanzamiento 18 feb 2026"
git push origin v1.0-20260218
```

Sustituir `v1.0-20260218` por un nombre que identifique la versión (ej. `v1.0-pre`, `v1.1-20260301`). Si no usas remoto, basta con:
```bash
git tag -a v1.0-20260218 -m "Lanzamiento 18 feb 2026"
```

---

## 2. Listar tags existentes

Para ver a qué versión quieres volver:
```bash
git tag -l -n1
```

Ejemplo de salida:
```
v1.0-20260201  Lanzamiento estable enero
v1.0-20260218  Lanzamiento 18 feb 2026
```

---

## 3. Volver a la versión anterior (rollback)

**Opción A — Solo cambiar el código al tag (recomendado para rollback urgente)**  
El historial de git no se modifica; solo se deja el directorio como estaba en ese tag.

```bash
cd /ruta/del/proyecto
git fetch --tags
git checkout v1.0-20260201
```

Sustituir `v1.0-20260201` por el nombre del tag al que quieras volver.

Luego **reiniciar la aplicación** (systemd, supervisor o el proceso que uses):
```bash
sudo systemctl restart conta-invoicing
# o
supervisorctl restart conta
```

**Opción B — Crear un nuevo commit que deshace cambios (trazable)**  
Útil si quieres dejar registrado en el historial que se hizo un rollback.

```bash
cd /ruta/del/proyecto
git checkout main
git revert HEAD --no-edit
git push origin main
```

Esto deshace solo el **último commit** en `main`. Para deshacer hasta un tag concreto, hay que revertir varios commits (o usar `git revert` hacia un commit anterior); en ese caso pide ayuda a alguien técnico o usa la Opción A.

---

## 4. Volver a la rama actual después de un checkout a tag

Si hiciste `git checkout v1.0-20260201` y luego quieres volver a desarrollar en `main`:
```bash
git checkout main
```

---

## 5. Resumen rápido (copy/paste)

| Objetivo | Comando |
|----------|--------|
| Crear tag antes de lanzar | `git tag -a v1.0-$(date +%Y%m%d) -m "Pre-lanzamiento"` |
| Ver tags | `git tag -l -n1` |
| Volver al tag X | `git checkout v1.0-20260201` y reiniciar la app |
| Volver a trabajar en main | `git checkout main` |

**Importante:** El rollback solo afecta al **código**. No borra la base de datos ni los archivos en `storage/` o `backup/`. Si el problema fue por datos o configuración (`.env`), hay que corregir eso aparte.
