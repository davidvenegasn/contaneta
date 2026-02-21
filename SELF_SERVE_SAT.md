# Conectar SAT (FIEL) — Paso a paso para el usuario

Guía para que un usuario final configure su FIEL y sincronice sus CFDI desde el portal, sin ayuda del administrador.

---

## 1. Entrar a “Conectar SAT”

1. Inicia sesión en el portal.
2. En el menú (ícono de usuario o menú lateral), entra a **“Conectar SAT”** o **“FIEL / Credenciales SAT”** (ruta: `/portal/config/sat`).

---

## 2. Subir archivos FIEL

1. **Certificado (.cer):** Arrastra o selecciona el archivo `.cer` que descargaste del SAT (e.firma).
2. **Clave privada (.key):** Arrastra o selecciona el archivo `.key` correspondiente.
3. **Contraseña:** Escribe la contraseña que te entregó el SAT al emitir tu FIEL (la que usas para abrir el archivo .key).

Requisitos:

- Solo archivos `.cer` y `.key` (máximo 2 MB cada uno).
- La FIEL debe ser **e.firma vigente** (no CSD de facturación electrónica).

---

## 3. Guardar y validar

1. Pulsa **“Guardar y validar”**.
2. El sistema guarda los archivos y ejecuta la validación en ese momento.
3. En el panel **Estado** (lateral o debajo) verás:
   - **Configurado** si hay archivos guardados.
   - **FIEL válida ✓** y la fecha de la última validación si todo es correcto.
   - **Error** y un mensaje si la contraseña es incorrecta, el certificado está vencido o no es e.firma.

Si aparece error, corrige (contraseña, archivos o renovación de FIEL) y vuelve a pulsar **“Guardar y validar”** o **“Validar de nuevo”**.

---

## 4. Sincronizar con el SAT

Cuando el estado muestre **FIEL válida ✓**:

1. Ve a **Inicio**, **Facturas emitidas** o **Facturas recibidas**.
2. Verás un bloque o barra con **“Último sync”** y un botón **“Sync SAT”**.
3. Pulsa **“Sync SAT”**.
4. El sistema encola la sincronización (emitidas y recibidas). Verás **“Sincronizando…”** mientras el worker procesa los jobs.
5. Al terminar, se actualizará **“Último sync: fecha y hora”** y el estado pasará a **OK** (o **Error** con un mensaje si algo falló).

La sincronización se ejecuta en segundo plano (worker/cron). No hace falta mantener la página abierta; puedes volver más tarde y comprobar el estado.

---

## 5. Si algo falla

- **“Configura y valida tu FIEL en Ajustes primero”**  
  → Entra en **Conectar SAT**, sube .cer y .key, escribe la contraseña y guarda/valida hasta ver **FIEL válida ✓**.

- **“Valida tu FIEL en Ajustes antes de sincronizar”**  
  → La FIEL no está validada. Pulsa **“Validar de nuevo”** en la página Conectar SAT.

- **“Ya hay una sincronización en curso”**  
  → Espera a que termine (puedes refrescar la página para ver si ya cambió el estado).

- **Estado “Error” con mensaje**  
  → Revisa el mensaje (contraseña, certificado vencido, SAT no disponible). Si quieres, entra en **Conectar SAT** y usa **“Ver detalle / Revalidar FIEL”** para revisar o volver a validar.

---

## Resumen

| Paso | Dónde | Acción |
|------|--------|--------|
| 1 | Menú → Conectar SAT | Entrar a la página de FIEL. |
| 2 | Conectar SAT | Subir .cer, .key y contraseña. |
| 3 | Conectar SAT | Pulsar “Guardar y validar”; comprobar “FIEL válida ✓”. |
| 4 | Inicio / Emitidas / Recibidas | Pulsar “Sync SAT”; esperar a “Último sync” actualizado. |
| 5 | Si hay error | Revisar mensaje y, si aplica, revalidar en Conectar SAT. |
