# Guía de facturación (Stripe) — ContaNeta

Configuración de pagos para que el usuario pueda registrarse, pagar y quedar con plan activo.

---

## Variables de entorno

En `.env` (o en el entorno del servidor) configura:

```env
# Stripe (obligatorias para cobro)
STRIPE_SECRET_KEY=sk_live_xxx
STRIPE_WEBHOOK_SECRET=whsec_xxx
STRIPE_PRICE_ID=price_xxx

# URL base del sitio (para success/cancel del Checkout)
SITE_URL=https://tu-dominio.com
```

- **STRIPE_SECRET_KEY:** Clave secreta de la API de Stripe (Dashboard → Developers → API keys). En pruebas usa `sk_test_...`.
- **STRIPE_WEBHOOK_SECRET:** Secreto del webhook (Dashboard → Developers → Webhooks → añadir endpoint → "Signing secret"). Necesario para verificar que los eventos vienen de Stripe.
- **STRIPE_PRICE_ID:** ID del precio de la suscripción (Dashboard → Products → tu producto Pro → precio recurrente). Ej: `price_1ABC...`.
- **SITE_URL:** Base URL del sitio; se usa para redirigir tras el pago o cancelación (`/portal/plan?success=1` o `?canceled=1`).

---

## Pasos en Stripe

1. **Crear producto y precio**
   - Dashboard → Products → Add product.
   - Nombre ej. "ContaNeta Pro", precio recurrente (mensual o anual).
   - Copiar el **Price ID** (`price_...`) a `STRIPE_PRICE_ID`.

2. **Activar Checkout**
   - La app crea sesiones con `stripe.checkout.Session.create(mode='subscription', ...)`.
   - No hace falta configurar nada más en Stripe para Checkout; solo la clave secreta y el Price ID.

3. **Configurar el webhook**
   - Dashboard → Developers → Webhooks → Add endpoint.
   - URL: `https://tu-dominio.com/webhooks/stripe`.
   - Eventos a escuchar:
     - `checkout.session.completed` (activar suscripción al completar pago).
     - `customer.subscription.updated` (actualizar estado/periodo).
     - `customer.subscription.deleted` (marcar cancelada).
   - Copiar el **Signing secret** (`whsec_...`) a `STRIPE_WEBHOOK_SECRET`.

4. **Modo prueba**
   - Usa claves `sk_test_...` y `price_...` de test.
   - Tarjetas de prueba: `4242 4242 4242 4242`.
   - El webhook en local requiere un túnel (ej. ngrok) y apuntar la URL del webhook en Stripe a `https://xxx.ngrok.io/webhooks/stripe`.

---

## Flujo del usuario

1. **Registro** → el usuario se registra y entra al portal (plan gratuito).
2. **Mi plan** → en el portal va a "Mi plan" y pulsa "Actualizar a Pro".
3. **Checkout** → la app llama a `POST /billing/checkout`, crea una sesión de Stripe Checkout y devuelve la URL; el navegador redirige a Stripe.
4. **Pago** → el usuario paga en Stripe; Stripe redirige a `SITE_URL/portal/plan?success=1`.
5. **Webhook** → Stripe envía `checkout.session.completed` a `/webhooks/stripe`; la app actualiza la tabla `subscriptions` (user_id, plan=pro, status=active).
6. **Features** → con `status = active` (o `trialing`) el usuario puede descargar XML y PDF; si no paga, esas acciones devuelven 402 y un mensaje para ir a Mi plan.

---

## Cómo probar en local

1. Crea un producto y precio de prueba en Stripe (Dashboard en modo Test).
2. Pon en `.env`:
   - `STRIPE_SECRET_KEY=sk_test_...`
   - `STRIPE_PRICE_ID=price_...` (del precio de prueba)
   - `SITE_URL=http://127.0.0.1:8000` (o la URL que uses)
3. Para recibir el webhook en local, usa un túnel:
   - `ngrok http 8000`
   - En Stripe → Webhooks → Add endpoint → URL `https://xxx.ngrok.io/webhooks/stripe` → eventos indicados arriba.
   - Copia el Signing secret a `STRIPE_WEBHOOK_SECRET`.
4. Arranca la app y entra con un usuario registrado; ve a Mi plan → Actualizar a Pro; paga con `4242 4242 4242 4242`.
5. Tras el pago, Stripe llama al webhook; si el túnel está activo, la suscripción se marcará activa y podrás descargar XML/PDF.

---

## Gating (qué se limita sin plan activo)

- **Descarga XML** (`/portal/sat/xml/{uuid}`): si el usuario está logueado (user_id > 0) y no tiene suscripción activa, responde **402** con mensaje para ir a Mi plan.
- **Descarga PDF** (`/portal/sat/pdf/{uuid}`): igual que XML.
- El resto del portal (ver facturas, clientes, resumen, etc.) sigue usable; solo se limitan esas dos acciones premium.

Los usuarios que entran solo por **token** (sin cuenta) no se comprueba suscripción; pueden descargar para no romper enlaces legacy.
