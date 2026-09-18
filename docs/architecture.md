# Arquitectura

## Flujo de datos

1. Home Assistant y MQTT entregan cambios de fuentes originales.
2. Un adaptador por familia produce observaciones del contrato v1.
3. `EvidenceStore` conserva el estado acotado y aplica revisiones
   independientes de tiempo, identidad, ubicación, clase, conteo, ciclo de
   vida e imagen.
4. `PresenceResolver` correlaciona observaciones y produce un snapshot de una
   sola revisión.
5. Entidades, eventos y acciones con respuesta proyectan ese mismo resultado;
   no vuelven a interpretar sensores.

El runtime es el único propietario mutable. Las propiedades de entidades no
hacen I/O. Todas las mutaciones de Home Assistant se serializan con un lock
asíncrono.

## Adaptadores

- `frigate_events`: interpreta `frigate/events`, separa hora inicial, hora
  espacial y fin, y usa solo `current_zones` como zona actual.
- `frigate_face`: acepta intentos sobre el umbral configurado y traduce nombres
  mediante un mapa explícito de identidades.
- Contexto PTZ: conserva un historial acotado de perfil, preset y movimiento.
  Una solicitud no confirma posición física. La zona actual válida tiene
  prioridad; el perfil requiere confirmación de estado estable.
- `bermuda_area`: representa un dispositivo enlazado a una identidad. Nunca lo
  convierte automáticamente en una persona.
- `mtr_count`: trata total y zonas como una fuente compuesta. Publica cada zona
  una vez y solo el remanente no cubierto por ellas.
- `binary_presence`, `count` y `person_home`: fuentes simples con semántica
  declarada en configuración.

Una excepción de un adaptador solo degrada esa fuente. El resto continúa.

## Vigencia y recuperación

La caducidad es opcional por fuente. Se usa para transportes cuyo estado puede
quedar activo si se pierde un mensaje final; no debe asignarse a una entidad de
estado persistente que legítimamente puede no cambiar durante horas.

El runtime calcula el próximo vencimiento y Home Assistant instala un único
timer. Al vencer, la evidencia deja de participar en el snapshot, aumenta la
revisión y permanece disponible como historial. Las imágenes confirmadas se
guardan aparte y no caducan al cambiar Bermuda o la habitación actual.

Al restaurar se aceptan únicamente fuentes aún configuradas. Eliminar una
fuente no resucita su evidencia; renombrar su `entity_id` se resuelve por el ID
estable del registro y provoca una recarga controlada.

## Superficies públicas de N3

- `sensor.presence_engine_snapshot`: snapshot completo de comparación.
- `sensor.presence_engine_revision`: revisión y fallos de adaptadores.
- `binary_sensor.presence_engine_coverage_degraded`: cobertura no disponible.
- `event.presence_engine_detection`: inicio, revisión y fin de una detección.
- `presence_engine.get_snapshot`: consulta estructurada de presencia actual.
- `presence_engine.get_detection`: consulta de un evento por ID.
- Evento de bus `presence_engine_result`: misma proyección de detección.

Estas superficies son propias de la integración y no sustituyen salidas
operativas durante N3. La migración de consumidores pertenece a N5.
