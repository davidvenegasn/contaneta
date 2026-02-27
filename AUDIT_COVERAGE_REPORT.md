# Reporte de cobertura de auditoría (estabilidad)

Generado por `scripts/audit_coverage.py`. Revisar patrones que pueden indicar rezagos de Jobs 1-9.

## 1. Resumen

| Categoría | Backend (crítico) | Backend (warning) | Frontend (crítico) | Frontend (warning) |
|-----------|-------------------|-------------------|--------------------|--------------------|
| # issues  | 4 | 4 | 0 | 12 |

## 2. Backend findings

| Archivo | Línea | Match | Extracto |
|---------|-------|-------|----------|
| routers/public.py | 84 | HTMLResponse + status_code=400 | if not token:             return HTMLResponse("<p>Link inválido.</p>", status_co |
| routers/public.py | 86 | HTMLResponse + status_code=400 | if act not in ("accept", "reject", "aceptar", "rechazar"):             return HT |
| routers/portal.py | 64 | subprocess.run sin timeout | try:         proc = subprocess.run(             ["php", php_script, str(issuer_i |
| routers/admin.py | 321 | subprocess.run sin timeout | if script_db.exists():                     r = subprocess.run(                   |
| routers/admin.py | 337 | subprocess.run sin timeout | if script_storage.exists():                     r2 = subprocess.run(             |
| routers/invoicing.py | 64 | HTMLResponse + status_code=400 | if not csrf_service.verify_csrf_token(token_val):                 return HTMLRes |
| routers/invoicing.py | 177 | HTMLResponse + status_code=400 | if fmt not in ("pdf", "xml", "zip"):             return HTMLResponse("Formato in |
| scripts/sat_worker.py | 89 | subprocess.run sin timeout | try:         result = subprocess.run(             cmd, |

## 3. Frontend findings

| Archivo | Línea | Match | Extracto |
|---------|-------|-------|----------|
| static/js/catalog-cache.js | 45 | fetch( sin portalFetchWithTimeout en contexto | : function (u, o) {         return fetch(u, o).then(function (r) {           if  |
| templates/portal_quotations.html | 417 | innerHTML con posible mensaje de error (revisar sanitización) | totalFromApi = undefined;         if (quotLoadErrorMsgEl) quotLoadErrorMsgEl.inn |
| templates/portal_config_sat.html | 152 | innerHTML con posible mensaje de error (revisar sanitización) | resultEl.hidden = false;     resultContent.innerHTML = '<p style="margin:0;">' + |
| templates/portal_config_sat.html | 271 | innerHTML con posible mensaje de error (revisar sanitización) | } else {             if (statusBadge) statusBadge.innerHTML = '<span class="fiel |
| templates/portal_config_sat.html | 272 | innerHTML con posible mensaje de error (revisar sanitización) | if (statusBadge) statusBadge.innerHTML = '<span class="fiel-status-badge fiel-st |
| templates/portal_config_sat.html | 276 | innerHTML con posible mensaje de error (revisar sanitización) | })         .catch(function(){ showResult(false, 'Error de conexión.'); if (statu |
| templates/portal_config_sat.html | 302 | innerHTML con posible mensaje de error (revisar sanitización) | var msg = (msgEl && msgEl.getAttribute('data-message')) ? msgEl.getAttribute('da |
| templates/portal_providers.html | 388 | innerHTML con posible mensaje de error (revisar sanitización) | totalFromApi = undefined;         if (loadErrorMsgEl) loadErrorMsgEl.innerHTML = |
| templates/portal_providers.html | 571 | innerHTML con posible mensaje de error (revisar sanitización) | if (panelError) panelError.hidden = false;           if (panelErrorMsg) panelErr |
| templates/portal_issued.html | 275 | innerHTML con posible mensaje de error (revisar sanitización) | var loadErrMsg401 = document.getElementById('loadErrorStateMsg');         if (lo |
| templates/portal_received.html | 289 | innerHTML con posible mensaje de error (revisar sanitización) | var loadErrMsg401 = document.getElementById('loadErrorStateMsg');         if (lo |
| templates/form/_script_form.html | 14 | fetch( sin portalFetchWithTimeout en contexto | })       : fetch(url, opts); |

## 4. Recomendaciones

1. **Backend 400/500:** Sustituir `return HTMLResponse(str(e), status_code=400)` por `logging.exception(...)` + `raise HTTPException(500, detail='Ocurrió un error. Intenta de nuevo.')` o dejar subir al handler 500.
2. **Backend HTTPException(400):** No usar `detail=str(e)`; usar mensaje fijo para el usuario.
3. **Frontend fetch:** Usar `portalFetchWithTimeout` (o `portalFetchJSON`) en lugar de `fetch()` directo para timeout, 401 y mensajes unificados.
4. **logging.exception:** Tras registrar, relanzar con `raise` o `raise HTTPException(500, ...)` para no ocultar el error.
5. **subprocess.run:** Añadir `timeout=N` para evitar bloqueos.
