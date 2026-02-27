# Catálogos SAT (opcional)

El formulario de **Generar factura** usa catálogos del SAT (Uso CFDI, Régimen fiscal, Clave ProdServ, Unidad, etc.).

- **Sin `catalogs.db`:** La app usa listas estáticas para Uso CFDI, Régimen fiscal, Forma de pago, Moneda y Unidad. Los desplegables funcionan. La **búsqueda de Clave ProdServ** no tendrá resultados; puedes escribir la clave a mano (ej. `81112100`).
- **Con `catalogs.db`:** Coloca aquí el archivo `catalogs.db` con las tablas SAT (p. ej. `cfdi_40_usos_cfdi`, `cfdi_40_regimenes_fiscales`, `cfdi_40_productos_servicios`, `cfdi_40_claves_unidades`, etc.). Así la búsqueda de ProdServ y el autocompletado tendrán el catálogo completo.

El archivo **no viene en el repo**. Puedes generarlo a partir de los catálogos oficiales del SAT o de repositorios comunitarios que publiquen una base SQLite con esas tablas. Las columnas esperadas por tabla son tipo `clave`/`key`/`id` y `texto`/`descripcion`/`label`/`value`.

**Nota:** Esto no tiene relación con Facturapi ni con el periodo de prueba. Los catálogos son solo datos de referencia del SAT; el timbrado sí depende de tu cuenta Facturapi.
