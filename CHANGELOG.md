# Changelog

## [Unreleased]

### Fixed

- **DEV_MODE default por entorno:** En entornos que no sean explícitamente desarrollo (`ENV=dev`), el default de `DEV_MODE` es ahora **0**, evitando caer al acceso demo por defecto en producción. Con `ENV=dev` el default sigue siendo `1`. Solo se usa demo cuando `DEV_MODE=1` está explícitamente definido. Ver `config.py` y DECISIONS.md.

- **Fallback de sesión en portal:** Sin cookie válida, las rutas HTML del portal redirigen a `/login` (302) y las API devuelven 401 JSON. El fallback al issuer demo solo ocurre si `ALLOW_DEMO_PORTAL=1` (y `DEV_MODE=1`). Default `ALLOW_DEMO_PORTAL=0`: ya no hay "brincos" al demo al navegar. Ver `routers/deps.py` y DECISIONS.md.
