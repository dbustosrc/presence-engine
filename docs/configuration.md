# Configuración

La entrada de configuración contiene un objeto JSON con `schema_version: 1`.
El flujo valida el objeto antes de guardarlo y las opciones permiten activar el
modo comparación, limitar registros y ajustar el retraso de persistencia.

## Secciones

- `areas`: mapa `area_id → floor_id`.
- `adjacency`: habitaciones físicamente contiguas; no expresa cobertura de un
  sensor.
- `identities`: asociaciones explícitas para descubrimiento estable.
- `cameras`: geometría, zonas, perfiles y entidades de contexto PTZ.
- `sources`: entradas originales y su adaptador.

Cada fuente puede indicar `entity_ids`, `entity_registry_ids`, `topics`, área,
planta, identidad, calidad espacial, grupos de dependencia/cobertura y
`expires_after_seconds`. Cuando se proporcionan IDs de registro, debe existir
uno por cada entidad. Las salidas de Presence Engine están prohibidas como
entradas.

## Ejemplo neutro

`configuration.example.json` contiene una cámara PTZ ficticia, Frigate,
Bermuda, MTR y radar. El archivo forma parte de las pruebas y debe continuar
siendo aceptado por el parser.

## Descubrimiento

El descubrimiento lee los registros oficiales de Home Assistant al cargar o
ante cambios del registro. Solo activa automáticamente familias conocidas si
los metadatos demuestran semántica suficiente. Ejemplos:

- Un radar con área asignada puede activarse como presencia binaria.
- Un área Bermuda necesita una asociación de identidad estable.
- Una zona MTR sin modelo físico permanece pendiente.
- Entidades desconocidas se ignoran.

No se escanean todos los estados en cada evento. Las suscripciones finales son
la unión exacta de entidades y topics configurados/activados.

## Política de expiración

Utilizar caducidad para eventos push que podrían perder el mensaje de fin. No
usarla por defecto en `person.*`, radares o contadores de estado: Home Assistant
ya mantiene su valor actual aunque no cambie.
