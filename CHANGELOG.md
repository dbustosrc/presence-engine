# Historial de cambios

## 0.2.4 — Limpieza de cobertura retirada

- Descarta durante la restauración las fuentes indisponibles que ya no forman
  parte de la configuración efectiva.
- Evita que una fuente retirada deliberadamente quede marcada para siempre
  como cobertura degradada después de una actualización.
- Conserva el estado indisponible únicamente para fuentes que siguen
  configuradas y, por tanto, continúan siendo cobertura esperada.

## 0.2.3 — Descubrimiento por dispositivo

- Evita que los canales auxiliares de un dispositivo ya configurado de forma
  explícita se activen otra vez como fuentes independientes mediante el
  descubrimiento automático.
- Elimina las revisiones redundantes observadas cuando los canales internos de
  movimiento, quietud y zonas del MSR-2 de Office alternaban sin cambiar el
  resultado de presencia.
- Añade una regresión para conservar una sola representación canónica por
  dispositivo explícitamente modelado.

## 0.2.2 — Actualizaciones multidimensionales atómicas

- Aplica en una sola operación las dimensiones aceptadas de una observación,
  evitando estados intermedios inválidos al finalizar contadores y sensores
  binarios (`count=0` junto con ciclo de vida finalizado).
- Añade una regresión que reproduce el fallo observado durante el arranque de
  Home Assistant.

## 0.2.1 — Correcciones de comparación

- Refina una presencia genérica `person.home` con la habitación del dispositivo
  registrado sin permitir que el dispositivo sobrescriba evidencia espacial de
  cámara, radar u otra fuente directa.
- Expone los identificadores exactos de las fuentes indisponibles en el
  snapshot y en el diagnóstico de cobertura.
- Usa `last_changed` para la semántica de entidades cuyo adaptador consume el
  estado, evitando revisiones nuevas por cambios exclusivos de atributos.

## 0.2.0 — Candidata de comparación

- Añade la integración de Home Assistant con config entry, opciones y descarga
  limpia.
- Adapta Frigate, contexto PTZ, Bermuda, radares, contadores y MTR al contrato
  normalizado v1.
- Conserva por separado tiempo de detección, reconocimiento, ubicación y
  procesamiento.
- Publica únicamente entidades diagnósticas, eventos propios y consultas con
  respuesta; no actúa sobre cámaras, trackers ni notificaciones.
- Persiste evidencia acotada e imágenes identificadas, con revisiones
  monotónicas y recuperación tras reinicio.
- Mantiene zonas MTR solapadas como ubicación ambigua y limita la población por
  el total físico del radar.
- Añade validación de paquete, matriz de regresión y procedimiento de
  comparación/reversión.

Esta versión no sustituye todavía ningún consumidor operativo. Su propósito es
ejecutarse como observadora durante N4.
