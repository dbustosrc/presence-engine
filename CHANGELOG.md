# Historial de cambios

## 0.4.10 — Alias de cámaras de reproducción

- Reconoce los identificadores temporales de Frigate Replay como alias de la
  cámara configurada correspondiente.
- Reutiliza geometría, zonas, disponibilidad y políticas de admisión sin crear
  configuración ni entidades duplicadas.
- Conserva el identificador de origen para imágenes, clips y diagnóstico.

## 0.4.9 — Admisión espacial y replay reproducible

- Añade una política opcional para admitir eventos de cámara únicamente cuando
  una zona actual configurada demuestra que pertenecen al área vigilada.
- Finaliza la evidencia admitida cuando el objetivo abandona esas zonas e
  ignora reconocimientos aislados que no tienen un evento visual admitido.
- Incorpora escenarios de replay deterministas con evidencia sincronizada de
  varias fuentes y conserva las clasificaciones nativas de animales.

## 0.4.8 — Vencimiento autónomo de continuidad

- Programa el vencimiento de ubicaciones conservadas por continuidad aunque
  no se produzcan nuevos eventos de sensores.
- Reevalúa únicamente la continuidad vencida y mantiene intacta la evidencia
  activa e independiente.

## 0.4.7 — Evidencia visual por detección

- Conserva la imagen de cada detección aunque todavía no exista una identidad.
- Proyecta imágenes de presencias anónimas y animales únicamente desde su
  propio evento, evitando asociaciones visuales entre detecciones diferentes.
- Mantiene la evidencia visual al restaurar el estado después de un reinicio.

## 0.4.6 — Proyección autocontenida para presentación

- Expone en cada presencia el método y el instante de identidad ya resueltos.
- Incluye una URL autenticada de imagen junto con sus metadatos históricos.
- Permite que tarjetas y otros consumidores presenten el resultado común sin
  volver a consultar ni correlacionar fuentes de detección.

## 0.4.5 — Acciones visuales por detección

- Conserva el origen genérico de una imagen junto con sus demás metadatos.
- Proyecta, cuando la fuente lo permite, un enlace autenticado al clip del
  mismo evento sin exigir que el consumidor conozca la convención del origen.
- Mantiene compatibilidad al restaurar referencias visuales guardadas por
  versiones anteriores.

## 0.4.4 — Resultados de detección autocontenidos

- Incluye método y puntuación de identidad, fuentes contribuyentes e imagen del
  propio evento en cada resultado de detección.
- Proyecta referencias visuales compatibles a una ruta autenticada consumible
  sin exponer detalles de almacenamiento a la capa de presentación.
- Mantiene separados los instantes de detección, reconocimiento, ubicación e
  imagen durante las revisiones de un mismo evento.

## 0.4.3 — Salud de infraestructura configurable

- Añade fuentes de salud que reflejan la disponibilidad de infraestructura sin
  crear observaciones de presencia.
- Permite declarar estados saludables o estados de fallo para distintos
  contratos de conectividad.
- Valida una entidad por fuente de salud para evitar recuperaciones parciales
  ambiguas.

## 0.4.2 — Evidencia de dispositivos y salud de cobertura

- Distingue la ausencia de un objetivo rastreado de la pérdida de una fuente
  de cobertura, con una política configurable por fuente.
- Mantiene separadas la ubicación de un dispositivo y la ubicación demostrada
  de su propietario; el dispositivo por sí solo respalda únicamente alcance
  doméstico.
- Conserva la clasificación nativa de animales en el snapshot activo y retira
  la presencia cuando finaliza su evidencia directa.
- Impide que un snapshot anterior cree presencia actual sin ninguna evidencia
  vigente.

## 0.4.1 — Aislamiento de cámaras degradadas

- Permite declarar entidades de disponibilidad por cámara sin acoplarlas al
  transporte o fabricante del dispositivo.
- Retira la evidencia activa de una cámara cuando su canal configurado deja de
  estar disponible y expone la degradación sin afectar otras fuentes.
- Ignora nuevos eventos visuales de la cámara degradada hasta observar su
  recuperación; conserva de forma independiente la última imagen confirmada.
- Mantiene degradadas las fuentes compuestas hasta que todos sus canales
  requeridos vuelven a estar disponibles.
- Resuelve renombres de las entidades de disponibilidad mediante identificadores
  estables del registro de Home Assistant.

## 0.4.0 — Contratos públicos estables

- Promueve las proyecciones aceptadas de presencia y registros por identidad a
  identificadores internos estables sin perder la configuración existente del
  registro de entidades.
- Consolida la cobertura en una sola entidad canónica y elimina la proyección
  duplicada utilizada durante la comparación.
- Mantiene separados ubicación actual, identidad, confianza e imagen histórica
  antes de conectar consumidores operativos.

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
