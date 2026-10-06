# Presence Engine

Integración personalizada de Home Assistant para normalizar evidencia de
presencia, conservar su cronología y publicar una resolución reutilizable y
coherente.

El motor no controla dispositivos ni decide destinatarios de notificaciones.
Consume fuentes originales mediante adaptadores, produce snapshots y
resultados de detección versionados, y deja las políticas de actuación a las
automatizaciones consumidoras.

## Capacidades

- Núcleo determinista independiente de Home Assistant.
- Adaptadores para eventos y rostros de Frigate, contexto PTZ, áreas Bermuda,
  radares binarios, contadores simples, MTR multizona y salud de
  infraestructura.
- Registro acotado con revisiones por dimensión y recuperación mediante
  `Store`.
- Caducidad selectiva programada al próximo vencimiento, sin polling global.
- Descubrimiento conservador mediante registros de entidades y dispositivos.
- Última imagen identificada persistente e independiente de la ubicación
  actual.
- Entidades diagnósticas, eventos y acciones con respuesta para consumidores.
- Proyecciones públicas estables para presencia, cobertura y registros por
  identidad, con un solo escritor por salida.
- Contexto PTZ opcional mediante `telemetry_entity_id`: consume intervalos
  medidos `stable_intervals` con `destination`, `start` y `end`. El destino
  es una clave de `profile_to_area`; cada intervalo cerrado dura como máximo
  tres segundos y no se extrapola. Una confirmación posterior puede refinar
  una captura histórica sin cambiar su hora ni la de otra ubicación actual.
- `active_areas` distingue `current_minimum_count` y
  `last_current_observed_at` de la ubicación continuada para consumidores de
  control; la continuidad general permanece visible por separado.

## Límites

- No mueve cámaras ni publica trackers mediante MQTT. Conectar consumidores o
  transferir entity IDs continúa siendo una migración explícita.
- No envía notificaciones.
- No modifica Home Assistant, Frigate ni integraciones instaladas.
- No deduce geometría desconocida ni asocia dispositivos a personas por el
  nombre visible.
- La configuración física de una casa no pertenece al repositorio.

## Estado de la versión

`0.5.26` conserva como intervalo los agregados de habitación/planta compatibles
aunque sus relojes difieran: un positivo mantenido no demuestra otro individuo.
No elimina fuentes ni reduce el máximo; ámbitos incompatibles y tracks distintos
mantienen su independencia. No cambia los plazos de asociación ni identifica ecos.

`0.5.25` utiliza telemetría radar reciente para corroborar un traslado ya
respaldado por anclaje corporal y tendencias Bluetooth, incluso cuando un
contador positivo conserva su reloj original. Requiere una sola área/población
no ambigua y una serie escalar consistente, con velocidad medida para X/Y/rango
o cambios del canal de distancia de movimiento. No combina marcos, fabrica
fotogramas XY, identifica personas por ranura ni crea cuerpos con telemetría.
Conserva confianza probable, datos originales y plazos fijos de 90 segundos;
diagnósticos identifican el soporte empleado y su reloj, sin nuevas opciones,
entidades, consultas o acciones PTZ. La aceptación física es independiente de
las regresiones y la reconstrucción de capturas.

La versión `0.5.0` incorpora configuración guiada nativa, JSON avanzado opcional
y descubrimiento de identidades por reconocimientos Frigate aceptados. Conserva
los contratos públicos y no sustituye trackers, notificaciones ni controles
existentes automáticamente.

## Pruebas

Desde este directorio:

```powershell
$env:PYTHONPATH = "custom_components"
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
```

Las pruebas usan exclusivamente nombres y geometrías sintéticas.
Las comprobaciones de formularios y ciclo de vida requieren Home Assistant:
se omiten si no está instalado y CI las ejecuta en su contenedor oficial.

## Documentación

- `docs/architecture.md`: capas, propiedad del estado y recuperación.
- `docs/configuration.md`: contrato de configuración y fuentes.
- `docs/compatibility.md`: versiones y APIs verificadas.
- `docs/contract.md`: semántica del contrato v1 y límites entre capas.
- `docs/regression-matrix.md`: invariantes y su prueba ejecutable.
- `docs/installation.md`: publicación e instalación por HACS.
- `docs/comparison.md`: protocolo de comparación sin efectos.
- `docs/public-projections.md`: contrato de las entidades públicas.
- `docs/rollback.md`: reversión soportada de la integración.
- `CHANGELOG.md`: notas de cada versión.
