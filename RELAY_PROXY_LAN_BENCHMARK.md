# Benchmark Enfocado: SSH Bridge/Proxy hacia LAN interna

Este documento compara herramientas que resuelven el mismo problema central de NetSphere Bridge:

- conectarte por SSH
- crear proxy/tunel
- acceder a IPs internas de la LAN remota

---

## Tu propuesta actual (NetSphere Bridge)

Caso de uso cubierto:

- Buscar o indicar IP interna de cliente
- Levantar bridge/proxy por SSH (SOCKS)
- Entrar al rango LAN interno desde navegador local

Ventaja diferencial:

- Flujo operativo empaquetado en UI para soporte tecnico (no solo CLI).

---

## Herramientas realmente comparables

## 1) OpenSSH Dynamic Forward (`ssh -D`)

Que hace:

- SOCKS5 local sobre SSH.

Fortaleza:

- Nativo, robusto, simple, estandar.

Debilidad frente a tu app:

- No trae UI, no trae busqueda/escaneo de hosts, no gestiona sesiones de operadores.

Conclusion:

- Es la base tecnica de referencia, pero no reemplaza tu experiencia operativa.

## 2) sshuttle

Que hace:

- "VPN ligera" sobre SSH, enrutando subredes completas de forma transparente.

Fortaleza:

- Acceso a rangos completos sin configurar cada app a SOCKS.

Debilidad frente a tu app:

- Orientado a CLI; menos amigable para soporte no tecnico.

Conclusion:

- Muy buena referencia para modo "acceso de subred completa".

## 3) Chisel

Que hace:

- Tuneles TCP/UDP sobre HTTP con soporte SOCKS y modo reverse.

Fortaleza:

- Excelente cuando SSH directo no es viable y se necesita atravesar restricciones.

Debilidad frente a tu app:

- Requiere levantar client/server extra y gestionar binarios.

Conclusion:

- Complemento de contingencia para redes hostiles.

## 4) FRP (Fast Reverse Proxy)

Que hace:

- Exposicion/tunel de servicios internos (TCP/UDP/STCP, etc.).

Fortaleza:

- Muy util para topologias con NAT complejo y escenarios de reverse access.

Debilidad frente a tu app:

- Menos directo para workflow diario de "entrar al CPE por IP interna".

Conclusion:

- Buen complemento en escenarios de infraestructura distribuida.

## 5) Ligolo-ng (pivoting avanzado)

Que hace:

- Pivoting de red avanzado con interfaz TUN y acceso interno mas transparente.

Fortaleza:

- Muy potente para movimiento lateral y acceso amplio a red interna.

Debilidad frente a tu app:

- Enfoque mas red-team/avanzado; complejidad operativa mayor.

Conclusion:

- Referencia tecnica alta, pero posiblemente sobredimensionada para soporte diario ISP.

---

## Resumen rapido (para decidir)

- Si quieres robustecer lo actual sin cambiar paradigma: **OpenSSH + mejoras internas**.
- Si quieres "modo subred completa" facil: **inspirarte en sshuttle**.
- Si necesitas evasion/reverse por entornos restringidos: **agregar modo Chisel/FRP opcional**.
- Si buscas pivot avanzado total: **Ligolo-ng** (solo si realmente lo necesitas).

---

## Recomendacion exacta para NetSphere Bridge

No reemplazar tu app. Mejor evolucionarla en 3 bloques:

1. **Core confiable de tuneles**  
   - health-check de tunel
   - reconexion automatica
   - timeout/reintentos configurables

2. **Modo de acceso dual**  
   - modo actual SOCKS por app/navegador
   - modo subred (estilo sshuttle) para herramientas de red

3. **Plan B de conectividad**  
   - plugin opcional de tunel reverse (chisel/frp) para casos donde SSH directo falla

---

## KPIs que si miden mejora real de tu producto

- Tiempo desde "seleccionar cliente" hasta "web interna visible"
- Tasa de conexion exitosa al primer intento
- % de sesiones caidas por hora
- Tiempo promedio de resolucion de soporte remoto
- Cantidad de casos recuperados con modo contingencia

---

## Conclusión

Tu proyecto ya esta en la categoria correcta (remote access bridge por SSH).  
Las herramientas "superiores" no son CRM/OSS en este contexto, sino stacks de tunel/pivot.  
La mejora ideal es agregar modos de conectividad y resiliencia sin perder la UX operativa que ya tienes.
