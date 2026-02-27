## Desarrollo en 5 minutos (setup reproducible)

### Requisitos
- macOS/Linux
- `python3` instalado

### Setup

```bash
bash scripts/setup_dev.sh
```

### Arrancar el servidor

```bash
./run_server.sh
```

Abre: `http://127.0.0.1:8000/`

### Smoke rápido

```bash
bash scripts/smoke_api.sh || true
```

### Tests (tenant isolation)

```bash
.venv/bin/pytest -q
```

### Reset de DB local (dev)

```bash
bash scripts/reset_db.sh
```

### Notas importantes
- **No versionar datos sensibles**: `.env`, `keys/`, `storage/`, `invoicing.db*`.
- `keys/` y `storage/` deben montarse fuera del repo en producción (ver `storage/README.md` y `keys/README.md`).

