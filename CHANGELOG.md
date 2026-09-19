# Historial de cambios

## 0.3.3 — Proyección de ubicación mantenible

- Retira la proyección candidata basada en nombres libres de ubicación del
  dominio `device_tracker`, deprecada por Home Assistant.
- Mantiene el registro por identidad como contrato canónico para ubicaciones
  interiores y elimina de forma soportada las entidades candidatas obsoletas.
- No modifica trackers heredados ni consumidores existentes durante la
  migración controlada.

## 0.3.2 — Imágenes de eventos accesibles

- Expone las referencias de instantáneas de eventos mediante la ruta
  autenticada proporcionada por la integración de Frigate.
- Mantiene la última imagen confirmada aunque cambie la ubicación o deje de
  existir una hipótesis activa para la identidad.
- Conserva la referencia original y sus metadatos para no confundir la imagen
  histórica con evidencia espacial actual.

## 0.3.1 — Contrato uniforme sin ubicación

- Mantiene el mismo conjunto de atributos en las proyecciones por identidad
  cuando todavía no existe una hipótesis activa.
- Expresa explícitamente como desconocidas las confianzas de identidad y
  ubicación, sin convertir la falta de evidencia en ausencia.

## 0.3.0 — Proyecciones públicas candidatas

- Añade proyecciones deshabilitadas por defecto para presencia general,
  cobertura, trackers por identidad y registros atómicos por identidad.
- Conserva por separado metadatos de identidad, ubicación e imagen en todas
  las proyecciones derivadas de una misma revisión.
- Propaga la clasificación nativa de personas y animales sin perder especies
  conocidas durante la resolución.
- Mantiene las nuevas entidades sin efectos externos: no publican MQTT, no
  llaman servicios y no sustituyen consumidores existentes automáticamente.

## 0.2.5 — Prevención de realimentación indirecta

- Permite excluir fuentes concretas o prefijos de trackers al adaptar entidades
  `person` como evidencia de alcance doméstico.
- Retira la observación anterior cuando la entidad `person` selecciona un
  tracker calculado que no debe volver a entrar al motor.
- Valida los filtros de fuentes como parte del contrato de configuración.

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
- Evita revisiones redundantes cuando los canales auxiliares de un dispositivo
  cambian sin modificar el resultado de presencia.
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

Esta versión está destinada al modo de comparación y no sustituye consumidores
existentes de forma automática.
