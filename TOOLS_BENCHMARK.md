# Benchmark de Herramientas Similares/Superiores

Objetivo: identificar en que plataformas vale la pena inspirarse para mejorar NetSphere Bridge sin perder lo que hoy funciona.

---

## Tu punto de partida actual (NetSphere Bridge)

Fortalezas actuales:

- Flujo operativo enfocado y rapido para acceso remoto de clientes.
- Conexion SSH + tunel SOCKS + apertura de navegador integrada.
- UI de escritorio simple para operaciones diarias.
- Integracion de clientes por hoja de calculo (pragmatica y util).

Limitaciones actuales:

- Monolito en un archivo grande.
- Sin observabilidad avanzada ni monitoreo continuo de red.
- Sin inventario/CRM/ticketing completo de ISP.
- Sin aprovisionamiento masivo de CPE (TR-069).

---

## Comparativa resumida

## 1) UISP (Ubiquiti) - Plataforma ISP integrada

Tipo:

- Comercial (ecosistema Ubiquiti).

Aporta:

- CRM/billing integrado y automatizaciones de ISP.
- Integraciones y flujos operativos listos para escalar.

Cuándo usarlo como referencia:

- Si quieres evolucionar hacia OSS/BSS mas integral sin construir todo desde cero.

Riesgo:

- Dependencia de ecosistema/proveedor y menos control fino que un desarrollo propio.

## 2) Splynx - ISP Billing + Network Management

Tipo:

- Comercial especializado en ISP/WISP.

Aporta:

- Billing robusto, CRM, ticketing, field service, inventario.
- Integracion fuerte con MikroTik (RADIUS + API).
- Incluye TR-069 ACS en su propuesta.

Cuándo usarlo como referencia:

- Si tu objetivo mediano es "operacion completa ISP" (no solo acceso tecnico).

Riesgo:

- Coste recurrente y curva de adopcion de procesos.

## 3) Sonar Software - Enfoque enterprise ISP

Tipo:

- Comercial enterprise.

Aporta:

- Billing/finanzas avanzado, dispatch, inventario, reporting fuerte.
- Herramientas para operaciones multi-equipo y crecimiento organizacional.

Cuándo usarlo como referencia:

- Si visualizas crecimiento empresarial fuerte con procesos mas formales.

Riesgo:

- Complejidad y costo mayor que una solucion tecnica puntual.

## 4) GenieACS - Open source TR-069 (superior en provisioning CPE)

Tipo:

- Open source (AGPL), especializado.

Aporta:

- Provisionamiento masivo de CPE, scripts, firmware, gestion remota.
- Escalabilidad alta para flotas grandes.

Cuándo usarlo como referencia/adopcion:

- Si quieres controlar CPEs de forma estandarizada y escalable.

Riesgo:

- Requiere stack adicional (Node/Mongo) y conocimiento TR-069.

## 5) LibreNMS - Open source monitoreo/red

Tipo:

- Open source monitoreo.

Aporta:

- Descubrimiento automatico de red, alertas, graficas, API.
- Muy util para observabilidad que hoy no tienes integrada.

Cuándo usarlo como referencia/adopcion:

- Si quieres visibilidad continua de estado/performance de red.

Riesgo:

- No reemplaza CRM/billing; complementa, no sustituye tu app.

---

## Recomendacion estrategica para tu caso

Dado que ya tienes algo que funciona al 100%, la mejor ruta no es reemplazar de golpe, sino **arquitectura hibrida por capas**:

1. **Conservar NetSphere Bridge** como herramienta de operacion tecnica diaria.
2. **Agregar capacidades externas puntuales**:
   - LibreNMS para monitoreo/alertas
   - GenieACS para provisioning CPE (si tu parque lo requiere)
3. **Inspirarte en Splynx/Sonar/UISP** para roadmap de negocio:
   - inventario
   - ticketing
   - historial operativo
   - automatizacion de cobros/provisioning

---

## Backlog priorizado basado en benchmark

Prioridad alta (impacto inmediato):

1. Logs operativos consultables (quien entro, a que equipo, cuanto duro).
2. Inventario basico de equipos y estados.
3. Dashboard de sesiones activas + errores comunes.

Prioridad media:

4. Alertas de disponibilidad (inspirado en LibreNMS).
5. API interna para integrar con otras herramientas.

Prioridad alta de escalamiento:

6. Evaluar PoC de GenieACS para CPEs TR-069.
7. Definir si conviene integrarse con OSS/BSS comercial (Splynx/Sonar) o seguir in-house.

---

## Fuentes consultadas (sitios oficiales)

- [UISP Software](https://uisp.com/software)
- [Splynx](https://www.splynx.com/)
- [Sonar Software](https://www.sonar.software/)
- [GenieACS](https://genieacs.com/)
- [LibreNMS](https://www.librenms.org/)
