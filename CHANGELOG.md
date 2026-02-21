# Changelog

## [Unreleased]

### Fixed

- **DEV_MODE default por entorno:** En entornos que no sean explícitamente desarrollo (`ENV=dev`), el default de `DEV_MODE` es ahora **0**, evitando caer al acceso demo por defecto en producción. Con `ENV=dev` el default sigue siendo `1`. Solo se usa demo cuando `DEV_MODE=1` está explícitamente definido. Ver `config.py` y DECISIONS.md.
