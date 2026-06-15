# Contributing Guide

Gracias por contribuir a NetSphere Bridge.

## Objetivo del proyecto

NetSphere Bridge es una app de escritorio para soporte tecnico ISP que permite:

- descubrir/indicar IPs internas
- crear puente SOCKS sobre SSH
- acceder a equipos dentro de LAN remota

## Principios de contribucion

- No romper flujo operativo existente.
- Priorizar compatibilidad multiplataforma (Windows, Linux, macOS).
- Evitar cambios no relacionados en el mismo PR.
- Mantener UX simple para operadores tecnicos.

## Flujo de trabajo recomendado

1. Crear rama por cambio (`feat/...`, `fix/...`, `refactor/...`).
2. Hacer cambios pequenos y comprobables.
3. Ejecutar validaciones locales.
4. Actualizar documentacion si cambia comportamiento.
5. Abrir PR con contexto tecnico y plan de prueba.

## Convenciones de codigo

- Python 3.12+
- Formato: `black`
- Lint: `ruff`
- Tests: `pytest` (cuando aplique)
- No usar `except:` generico sin justificacion.
- No hardcodear rutas de sistema cuando haya alternativas portables.

## Checklist minimo de PR

- [ ] El flujo login -> conexion -> acceso LAN sigue funcionando.
- [ ] No se rompio manejo de tuneles activos.
- [ ] Se probaron casos de error comunes (credenciales, timeout, host invalido).
- [ ] Se actualizo documentacion relevante.

## Politica de cambios sensibles

- Seguridad/autenticacion: requiere revision extra.
- Proxy/hosts/sistema operativo: validar en al menos 2 plataformas.
- Cambios en UI principal: incluir evidencia visual o descripcion precisa.
