# Historial de cambios

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
