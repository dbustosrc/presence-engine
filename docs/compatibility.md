# Compatibilidad verificada

## Versiones

- Home Assistant Core mínimo soportado y probado para esta versión: `2026.9.2`.
- Formularios, selectores y descubrimiento facial verificados también en
  Home Assistant Core `2026.9.3`, mediante pruebas aisladas sin modificar la
  integración instalada.
- Frigate probado: `0.18.0-77a66e7`.
- Contrato de observaciones: `1`.
- Esquema de configuración: `1`.
- Almacenamiento de Home Assistant: `1`.

No se declara retrocompatibilidad con versiones anteriores no probadas. Una
versión futura de Home Assistant o Frigate debe pasar las pruebas y el modo de
comparación antes de ampliar esta matriz.

## Interfaces Home Assistant usadas

- Config entries y options flow con recarga.
- Menús, secciones y selectores nativos para configuración y reconfiguración.
- `async_track_state_change_event` para entidades exactas.
- Registros oficiales de entidades/dispositivos y su evento de actualización.
- `mqtt.async_subscribe` para topics exactos.
- `Store` para persistencia acotada.
- `DataUpdateCoordinator` en modo push.
- Entidades `sensor`, `binary_sensor` y `event`.
- Acciones con respuesta y diagnósticos de config entry.

No se importan internals de integraciones HACS ni se lee su almacenamiento
privado.

## Interfaces Frigate usadas

- `frigate/events`: ID estable por objetivo, `start_time`, `frame_time`,
  `end_time`, `current_zones`, clase y cámara.
- `frigate/tracked_object_update`, tipo `face`: ID del mismo objetivo, nombre,
  puntuación, cámara y timestamp.
- `frigate/available`: sincronización opcional del catálogo al reconectar.
- `/api/faces` y `/api/login`: consulta opcional del catálogo y autenticación,
  sin entrenamiento, altas de rostros ni polling periódico.

Frigate publica intentos faciales incluso bajo el umbral. El adaptador aplica
el umbral configurado y un intento rechazado no borra una identidad ya
confirmada.
