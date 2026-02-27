# Auditoría CSRF (diagnóstico)

**Objetivo:** Garantizar que todo POST que modifica estado valida CSRF (Form `csrf_token` o header `X-CSRF-Token`).

**Alcance:** Rutas POST en `routers/*`. Solo diagnóstico; no se ha modificado código.

---

## Resumen

| Estado  | Significado |
|---------|-------------|
| **OK**      | Verifica token CSRF (Form y/o X-CSRF-Token). |
| **MISSING** | Modifica estado y no verifica CSRF. |
| **N/A**     | No aplica CSRF (p. ej. webhook externo con firma). |

---

## Tabla por ruta

| Ruta | Tipo | Estado | Fix sugerido |
|------|------|--------|--------------|
| **routers/api.py** | | | |
| POST /api/customers/create | API | MISSING | Exigir header `X-CSRF-Token` cuando la sesión sea por cookie; o documentar que el cliente debe enviar el token en cada POST. Incluir token en respuestas/contexto del portal para que el front lo envíe. |
| POST /api/customers/delete | API | MISSING | Igual que arriba. |
| POST /api/products/create | API | MISSING | Igual que arriba. |
| POST /api/quotations/create | API | MISSING | Igual que arriba. |
| POST /api/quotations/update-status | API | MISSING | Igual que arriba. |
| POST /api/quotations/respond | API | MISSING | Endpoint público por `public_token`. Opciones: (1) Añadir CSRF en el formulario público (generar token en GET de la página de cotización); (2) Mantener protección por secreto de enlace (`public_token`) y documentar. |
| POST /api/providers/create | API | MISSING | Exigir `X-CSRF-Token` cuando la sesión sea por cookie (mismo criterio que el resto de /api). |
| **routers/portal.py** | | | |
| POST /portal/sat/sync | API (JSON) | MISSING | Aceptar `csrf_token` en body (JSON) o header `X-CSRF-Token` y llamar a `csrf_service.verify_csrf_token()` antes de encolar jobs. |
| POST /portal/config/sat | HTML/API | OK | — |
| POST /portal/config/sat/validate | API (JSON) | MISSING | Aceptar `csrf_token` en body o header `X-CSRF-Token` y verificar antes de ejecutar validación FIEL. |
| **routers/public.py** | | | |
| POST /public/cotizacion/respond | HTML | MISSING | Formulario público. Añadir campo oculto `csrf_token` generado al renderizar la página GET de la cotización y validar en POST; o documentar que la protección es por secreto de enlace (`public_token`). |
| **routers/invoicing.py** | | | |
| POST /submit | HTML | OK | — |
| **routers/admin.py** | | | |
| POST /admin/ops | HTML | OK | — |
| POST /admin/impersonate | API (JSON) | MISSING | Body JSON. Exigir `X-CSRF-Token` en header (o campo en body) y verificar con `csrf_service.verify_csrf_token()`. |
| POST /admin/impersonate/{issuer_id} | HTML/Redirect | MISSING | Añadir `csrf_token` en Form o header y verificar antes de `_do_impersonate`. |
| POST /admin/impersonate-form | HTML | OK | — |
| POST /admin/stop-impersonate | HTML | OK | — |
| **routers/auth.py** | | | |
| POST /login | HTML | OK | — |
| POST /auth/signup | HTML | OK | — |
| POST /auth/register | HTML | OK | — |
| POST /forgot | HTML | OK | — |
| POST /reset-password | HTML | OK | — |
| POST /choose-issuer | HTML | OK | — |
| POST /logout | HTML | MISSING | Aceptar `csrf_token` (Form o header) y verificar antes de invalidar sesión; o mantener GET/POST sin CSRF documentando que logout solo borra cookie (riesgo limitado si SameSite=Lax). |
| POST /signup | HTML | OK | — |
| POST /confirmar-perfil | HTML | OK | — |
| POST /onboarding | HTML | OK | — |
| **routers/billing.py** | | | |
| POST /billing/checkout | API (JSON) | MISSING | Llamada desde navegador con sesión por cookie. Exigir `X-CSRF-Token` en header y verificar antes de crear sesión Stripe. |
| POST /webhooks/stripe | Webhook | N/A | Llamada por Stripe; autenticación por `Stripe-Signature`. CSRF no aplica. |

---

## Detalle por categoría

### Rutas que ya verifican CSRF (OK)

- **Portal:** `/portal/config/sat` — Form `csrf_token` + header `X-CSRF-Token`.
- **Invoicing:** `/submit` — Form `csrf_token` o `X-CSRF-Token`.
- **Admin:** `/admin/ops`, `/admin/impersonate-form`, `/admin/stop-impersonate` — Form y/o header.
- **Auth:** `/login`, `/auth/signup`, `/auth/register`, `/forgot`, `/reset-password`, `/choose-issuer`, `/signup`, `/confirmar-perfil`, `/onboarding` — Form y/o header.

### Rutas API (JSON) sin CSRF (MISSING)

- Todas las POST bajo **/api/** modifican estado (crear/borrar clientes, productos, cotizaciones, proveedores) y dependen de sesión o token de portal (cookie). Un atacante podría montar un CSRF desde otro sitio si el usuario tiene sesión activa. **Fix:** Que el front del portal obtenga un CSRF token (p. ej. desde una respuesta o un endpoint GET) y lo envíe en header `X-CSRF-Token` en cada POST; en el backend, validar ese token en un middleware o en cada handler.
- **/portal/sat/sync** y **/portal/config/sat/validate** son JSON desde el portal; mismo enfoque: enviar y validar `X-CSRF-Token`.
- **/admin/impersonate** (JSON) y **/admin/impersonate/{id}** (POST): solo requieren rol admin; añadir verificación CSRF para evitar que un admin sea engañado a hacer impersonate desde un link/form externo.
- **/billing/checkout**: mismo patrón que el resto de POSTs con sesión por cookie; exigir `X-CSRF-Token`.

### Rutas públicas / especiales

- **/public/cotizacion/respond**: Modifica estado (aceptar/rechazar cotización). La URL incluye un `public_token` que actúa como secreto de enlace. Para CSRF estricto: incluir en el formulario un `csrf_token` generado al cargar la página (GET) y validarlo en POST.
- **/api/quotations/respond**: Equivalente por API; mismo criterio (token público vs CSRF).
- **POST /logout**: Invalida sesión. Riesgo bajo si la cookie tiene SameSite=Lax; opcionalmente exigir CSRF para consistencia.
- **POST /webhooks/stripe**: Llamada externa; autenticación por firma Stripe → **N/A** para CSRF.

---

## Recomendación general

1. **API bajo /api/**  
   Definir un middleware o dependency que, para cualquier POST (o PUT/PATCH/DELETE) con sesión por cookie, exija el header `X-CSRF-Token` y llame a `csrf_service.verify_csrf_token()`. El portal debe obtener el token (p. ej. en el HTML o con un GET) y enviarlo en todas las peticiones POST al API.

2. **Portal JSON (/portal/sat/sync, /portal/config/sat/validate)**  
   Aceptar `X-CSRF-Token` (o campo en body) y verificar en el handler.

3. **Admin**  
   Añadir CSRF a POST `/admin/impersonate` y POST `/admin/impersonate/{issuer_id}` (Form o header).

4. **Billing**  
   Exigir `X-CSRF-Token` en POST `/billing/checkout`.

5. **Público**  
   En `/public/cotizacion/respond`, incluir `csrf_token` en el formulario (generado en el GET) y validarlo en POST; o documentar explícitamente que la protección se basa en el secreto del enlace.

6. **Logout**  
   Opcional: exigir CSRF en POST `/logout` para alineación con el resto de acciones que modifican estado.
