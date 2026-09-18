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

## Límites

- No mueve cámaras ni publica trackers operativos.
- No envía notificaciones.
- No modifica Home Assistant, Frigate ni integraciones instaladas.
- No deduce geometría desconocida ni asocia dispositivos a personas por el
  nombre visible.
- La configuración física de una casa no pertenece al repositorio.

## Estado de la versión

La versión `0.2.0` es una candidata para comparación paralela. Debe instalarse
con `comparison_mode` activo y no debe conectarse todavía a automatizaciones
operativas. El sistema anterior continúa siendo el único responsable de
trackers, notificaciones y movimiento PTZ durante N4.

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
- `docs/rollback.md`: reversión soportada de la candidata.
- `CHANGELOG.md`: notas de la versión candidata.
