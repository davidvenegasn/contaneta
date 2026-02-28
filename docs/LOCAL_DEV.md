## Desarrollo local — ContaNeta (setup en 5 minutos)

Este documento está pensado para que un dev nuevo **arranque, pruebe y entienda los flujos principales** en ~1 hora.

### Requisitos
- **Python 3.10+**
- **PHP** en PATH (solo si vas a usar Sync SAT real)
- (Opcional) `sqlite3` CLI

### Setup rápido

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Crear `.env`:

```bash
cp .env.example .env
```

Valores recomendados en local:
- **`ENV=dev`**
- **`COOKIE_SECURE=0`** (porque local es HTTP)
- (Opcional) **`ALLOW_DEMO_PORTAL=1`** si quieres entrar sin login en HTML

### Arrancar servidor

```bash
./run_server.sh
# o
uvicorn app:app --reload --port 8000
```

Endpoints útiles:
- `GET /health`
- `GET /ready`
- `GET /status`

### Comando único de verificación (lo que debe correr cualquier PR)

```bash
bash scripts/check_all.sh
```

Notas:
- Si **ya tienes el server arriba**, `check_all` corre `smoke_api`.
- Si no, puedes pedir que lo levante:

```bash
START_SERVER=1 bash scripts/check_all.sh
```

### Reset de DB local (dev)

```bash
bash scripts/reset_db.sh
```

### Golden paths (lo importante del producto)

#### A) Emitir factura
1) Entra al portal (`/login` o `/signup`).
2) Ve a **Nueva factura** (formulario HTML) o usa **Factura rápida** desde Home.
3) La construcción de payload se centraliza en `services/invoices_service.py` y las rutas viven en:
   - `routers/invoicing.py` (flujo HTML submit + descargas `/download/*`)
   - `routers/api.py` (`POST /api/invoices/quick`, bulk, catálogos SAT)
4) Verifica que puedes descargar:
   - XML/PDF por UUID (rutas `/download/xml/{uuid}`, `/download/pdf/{uuid}`)

#### B) Sync SAT (descarga de emitidas/recibidas)
1) En portal: **Ajustes → FIEL / Credenciales SAT** (`/portal/config/sat`)
2) Sube `.cer` y `.key` + contraseña.
   - Se guardan **cifrados at-rest** en `storage/credentials/{issuer_id}/*.enc`.
3) Valida FIEL (botón “Validar”): corre `sat_sync/check_fiel.php` vía subprocess.
4) Inicia sync desde UI: `POST /portal/sat/sync`
5) Procesamiento:
   - Cron: `sat_sync/cron_sat_sync.sh`
   - Worker: `scripts/sat_worker.py` (cola `sat_jobs`)

Si no tienes SAT/PHP en local, igual puedes desarrollar UI usando `DEV_FIXTURES=1` para listados (ver `config.py`).

#### C) Bank PDF preview (estado de cuenta)
1) Portal: **Bancos → Convertir Edo. de Cuenta (PDF→Excel)** (`/portal/bank/pdf-to-excel`)
2) Sube un PDF:
   - Parsing/preview pipeline en `services/bank_preview_pipeline.py` y relacionados `services/bank_*`.
3) Descarga Excel generado (y revisa que respete tenant):
   - `GET /portal/bank/pdf-to-excel/download/{file_id}`

### Dónde leer para entender arquitectura en 15 minutos
- `docs/ARCHITECTURE.md` (mapa de módulos + DB + jobs + SAT)
- `docs/FRONTEND_GUIDE.md` (Jinja/CSS/JS)
- `OPERATIONS.md` + `RECOVERY_PLAYBOOK.md` (backups/restore/cron)

