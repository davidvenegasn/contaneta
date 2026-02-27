# Resumen de cambios recientes (últimas horas)

Resumen simple de lo que se ha arreglado y mejorado.

---

## 1. Login y acceso al portal

- **Problema:** No podías entrar con tu correo y contraseña; salía error o "inválido".
- **Qué se hizo:**
  - Se corrigió que la base de datos no tenía la columna `active` en la tabla `users`. El código ahora funciona aunque esa columna no exista.
  - Se reseteó tu contraseña para el usuario `diegopgza@gmail.com` para que puedas entrar con la contraseña que querías.
  - Si intentabas entrar por `/portal/login` salía "Página no encontrada". Se añadió una redirección: si vas a `/portal/login` te manda automáticamente a `/login` (donde sí está el formulario de login).

**Resultado:** Puedes entrar con tu correo y contraseña en la página de login correcta (`/login`).

---

## 2. Cerrar sesión

- **Problema:** El botón "Cerrar sesión" no hacía nada o no te llevaba a login.
- **Qué se hizo:**
  - Al cerrar sesión, la app ahora te redirige directamente a la página de **login** (antes te mandaba al inicio y a veces no se veía el cambio).
  - El "Cerrar sesión" del menú de usuario se cambió a un formulario que siempre hace la petición a `/logout` y luego te lleva a login, para que no falle por el menú desplegable.
  - Se ajustó el borrado de la cookie de sesión para que se elimine bien (mismos parámetros que al crearla).

**Resultado:** Al hacer clic en "Cerrar sesión" sales de la cuenta y vuelves a la pantalla de login.

---

## 3. Popups de error en listas vacías (Productos, Clientes, Cotizaciones, Proveedores)

- **Problema:** Al entrar a Productos, Clientes, Cotizaciones o Proveedores salía un popup de error tipo "No se pudo cargar productos" aunque solo fuera que no había datos.
- **Qué se hizo:** Si la lista está vacía o hay un fallo al cargar, la API ahora devuelve una lista vacía en lugar de un error. Así la pantalla muestra "Aún no tienes…" o la tabla vacía, sin popup de error.

**Resultado:** Ya no ves ese mensaje de error cuando simplemente no hay productos, clientes, etc.

---

## 4. Sombra verde en botones

- **Problema:** Alrededor de varios botones (menú, cerrar menú, "Contaneta", "Agregar primer proveedor", "Ver facturas recibidas", etc.) se veía una sombra o brillo verde que no querías.
- **Qué se hizo:**
  - Se quitó la sombra verde del hover de **todos** los botones en `form.css`.
  - Se quitó el anillo verde del foco en inputs y selects en `form.css`.
  - En `portal.css` se añadió una regla global: en **cualquier** botón o control (`.btn`, `button`, `.icon-btn`, etc.) no se usa sombra verde en hover, focus ni active. Lo mismo en modo noche.

**Resultado:** Los botones ya no muestran sombra verde; solo cambian de color o borde si hace falta (por ejemplo al pasar el ratón), sin brillo verde.

---

## 5. Error "getattr is undefined" en el portal

- **Problema:** En algunas pantallas del portal salía un error de tipo "getattr is undefined".
- **Qué se hizo:** En los templates se dejó de usar `getattr` y se usó la variable que ya envía el servidor (`is_impersonating`). Además se registró `getattr` en el entorno de plantillas por si se usara en otro sitio.

**Resultado:** Ese error de plantilla ya no debería aparecer.

---

## Resumen en una frase

Se arregló el login (usuario y contraseña, y la ruta correcta), el cierre de sesión (redirige a login y borra bien la sesión), los avisos molestos en listas vacías, y se eliminó la sombra verde de todos los botones y controles.
