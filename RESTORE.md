# Restaurar desde backup

Guía rápida para **restaurar** la base de datos y/o el directorio storage después de una incidencia. Pensada para que pueda seguirla alguien sin ser programador.

---

## Dónde están los pasos detallados

Los **pasos exactos** (comandos que puedes copiar y pegar) están en:

**→ [scripts/restore.md](scripts/restore.md)**

Ahí se explica:

- Cómo **restaurar solo la base de datos**
- Cómo **restaurar solo el storage** (XMLs y credenciales FIEL)
- Cómo **restaurar ambos**
- Qué hacer si algo falla (volver al estado anterior, revisar logs)

---

## Resumen en 4 pasos

1. **Detener la aplicación** (para que no se escriba mientras restauramos).
2. **Guardar una copia del estado actual** (por si hay que volver atrás).
3. **Copiar el archivo o carpeta del backup** al lugar donde la app espera la DB o `storage/`.
4. **Arrancar la aplicación** y comprobar con `curl -s http://localhost:8000/health`.

Sustituye en los comandos las rutas de ejemplo (`PROYECTO`, nombre del archivo de backup) por las tuyas. Todo el detalle está en **scripts/restore.md**.

---

## Referencia rápida

| Qué restaurar | Dónde mirar |
|---------------|-------------|
| Solo base de datos | scripts/restore.md → sección 1 |
| Solo storage (XMLs/FIEL) | scripts/restore.md → sección 2 |
| DB y storage | scripts/restore.md → sección 3 |
| Algo ha fallado | scripts/restore.md → sección 4 |

Más sobre backups y operación diaria: **OPERATIONS.md**.
