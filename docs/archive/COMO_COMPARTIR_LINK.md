# Cómo correr el portal para que cualquiera lo abra con un link

## 1. Arrancar el servidor (accesible en la red)

```bash
./run_server.sh
```

O con otro puerto:

```bash
./run_server.sh 5000
```

Esto hace que la app escuche en **todas las interfaces** (`0.0.0.0`), no solo en tu PC.

---

## 2. Quién puede abrirlo y con qué link

### Opción A: Personas en la **misma red** (misma WiFi / misma oficina)

1. Averigua tu IP local:
   - **Mac:** Preferencias del Sistema → Red, o en terminal: `ipconfig getifaddr en0`
   - **Windows:** `ipconfig` y busca "Dirección IPv4"
   - **Linux:** `hostname -I`

2. El link que les das es:
   ```
   http://TU_IP:8000/portal/home?token=SU_TOKEN
   ```
   Ejemplo: `http://192.168.1.105:8000/portal/home?token=diego`

3. Cada persona usa **su propio token** (el que tienen en `issuer_tokens`).

### Opción B: Cualquiera en **internet** (otra ciudad, otra red)

Tu PC está detrás del router, así que desde fuera no se puede llegar por IP. Necesitas un **túnel** que exponga tu puerto local a una URL pública.

#### Con ngrok (rápido y gratis)

1. Instala ngrok: https://ngrok.com/download  
2. Arranca el portal:
   ```bash
   ./run_server.sh
   ```
3. En otra terminal:
   ```bash
   ngrok http 8000
   ```
4. Ngrok te mostrará una URL pública, por ejemplo:
   ```
   https://abc123.ngrok-free.app
   ```
5. El link que compartes es:
   ```
   https://abc123.ngrok-free.app/portal/home?token=SU_TOKEN
   ```

**Nota:** En plan gratuito la URL cambia cada vez que reinicias ngrok. Si necesitas un link fijo, ngrok tiene planes de pago u otras opciones (Cloudflare Tunnel, etc.).

#### Con Cloudflare Tunnel (link estable y gratis)

1. Instala `cloudflared`: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation  
2. Arranca el portal: `./run_server.sh`  
3. En otra terminal:
   ```bash
   cloudflared tunnel --url http://localhost:8000
   ```
4. Te dará una URL tipo `https://xxxxx.trycloudflare.com`. Esa es la base del link:
   ```
   https://xxxxx.trycloudflare.com/portal/home?token=SU_TOKEN
   ```

---

## 3. Resumen

| Dónde están los demás | Cómo arrancar        | Link que compartes |
|-----------------------|----------------------|--------------------|
| Misma red (WiFi/casa) | `./run_server.sh`    | `http://TU_IP:8000/portal/home?token=TOKEN` |
| Internet (ngrok)      | `./run_server.sh` + `ngrok http 8000` | `https://xxx.ngrok-free.app/portal/home?token=TOKEN` |
| Internet (Cloudflare) | `./run_server.sh` + `cloudflared tunnel --url http://localhost:8000` | `https://xxx.trycloudflare.com/portal/home?token=TOKEN` |

Sustituye `TOKEN` por el token de cada usuario (ej. `diego`, `carolina`, etc.).
