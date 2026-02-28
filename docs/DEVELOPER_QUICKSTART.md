# Developer Quickstart — ContaNeta

Pasos mínimos para levantar el proyecto, correr migraciones, smoke tests y tests.

---

## 1. Entorno

```bash
cd /ruta/al/proyecto
python3 -m venv .venv
source .venv/bin/activate   # o .venv\Scripts\activate en Windows
pip install -r requirements.txt
```

Copia `.env.example` a `.env` y ajusta variables. Para desarrollo local suele bastar con `ENV=dev` y opcionalmente `SESSION_SECRET` (si no, se usa un valor aleatorio por sesión).

---

## 2. Arrancar el servidor

```bash
./run_server.sh
# o
uvicorn app:app --reload --host 0.0.0.0 --port 8000
```

Las migraciones se aplican solas al arranque. La app estará en `http://127.0.0.1:8000`.

---

## 3. Migraciones

- **Fuente oficial:** `migrations/*.sql` y lógica en `migrations_runner.py`. No uses scripts en `scripts/legacy/`.
- **Crear una nueva:** Añade `migrations/NNN_descripcion.sql` (siguiente número). Ver `MIGRATIONS.md` en la raíz y `docs/MIGRATIONS.md`.
- **Probar:** Arrancar con una DB vacía o una copia de DB existente y comprobar que no hay errores.

---

## 4. Smoke tests

```bash
# Servidor ya corriendo en 8000
./scripts/smoke_portal.sh

# Opcional: levantar servidor en background y probar
START_SERVER=1 ./scripts/smoke_portal.sh
```

```bash
python -m tests.test_import
```

---

## 5. Test de aislamiento tenant (descargas)

```bash
SESSION_SECRET=test-secret python scripts/test_tenant_downloads.py
```

Si tienes pytest:

```bash
pip install pytest
pytest tests/test_tenant_isolation_downloads.py -v
```

---

## 6. Auditoría subprocess (timeouts)

```bash
python scripts/find_subprocess_without_timeout.py
```

Debe salir "OK"; si no, revisar las líneas indicadas.

---

## 7. Documentación de contexto

- **Para IAs / onboarding:** `docs/README_FOR_AI.md`
- **Arquitectura:** `docs/ARCHITECTURE.md`
- **Dev local (5 min + golden paths):** `docs/LOCAL_DEV.md`
- **Frontend (Jinja/CSS/JS):** `docs/FRONTEND_GUIDE.md`
- **Auditoría y mejoras:** `docs/AUDIT_REPORT.md`, `docs/AUDITORIA_PARA_ANALISIS_IA.md`
- **Changelog hardening:** `docs/CHANGELOG_HARDENING.md`
