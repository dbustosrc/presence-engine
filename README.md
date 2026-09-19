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
  radares binarios, contadores simples y MTR multizona.
- Registro acotado con revisiones por dimensión y recuperación mediante
  `Store`.
- Caducidad selectiva programada al próximo vencimiento, sin polling global.
- Descubrimiento conservador mediante registros de entidades y dispositivos.
- Última imagen identificada persistente e independiente de la ubicación
  actual.
- Entidades diagnósticas, eventos y acciones con respuesta para consumidores.
- Proyecciones públicas candidatas deshabilitadas por defecto para migraciones
  con un solo escritor por salida.

## Límites

- No mueve cámaras ni publica trackers mediante MQTT. Los trackers candidatos
  permanecen deshabilitados hasta una migración explícita.
- No envía notificaciones.
- No modifica Home Assistant, Frigate ni integraciones instaladas.
- No deduce geometría desconocida ni asocia dispositivos a personas por el
  nombre visible.
- La configuración física de una casa no pertenece al repositorio.

## Estado de la versión

La versión `0.3.1` incorpora entidades candidatas para una migración
controlada. Se crean deshabilitadas por defecto y no sustituyen trackers,
notificaciones ni controles existentes automáticamente.

## Pruebas

Desde este directorio:

```powershell
$env:PYTHONPATH = "custom_components"
python -m unittest discover -s tests -v
python -m compileall -q custom_components tests
```

Las pruebas usan exclusivamente nombres y geometrías sintéticas.

## Documentación

- `docs/architecture.md`: capas, propiedad del estado y recuperación.
- `docs/configuration.md`: contrato de configuración y fuentes.
- `docs/compatibility.md`: versiones y APIs verificadas.
- `docs/contract.md`: semántica del contrato v1 y límites entre capas.
- `docs/regression-matrix.md`: invariantes y su prueba ejecutable.
- `docs/installation.md`: publicación e instalación por HACS.
- `docs/comparison.md`: protocolo de comparación sin efectos.
- `docs/public-projections.md`: contrato de las entidades candidatas.
- `docs/rollback.md`: reversión soportada de la candidata.
- `CHANGELOG.md`: notas de la versión candidata.
