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
`expires_after_seconds`. `availability_role` separa infraestructura de
observaciones: `coverage` degrada cobertura si el canal no está disponible;
`observation` retira únicamente la evidencia del objetivo. `auto` aplica el
valor propio del adaptador: áreas Bermuda y entidades `person` son
observaciones, mientras radares, contadores y transportes de detección son
cobertura. Cuando se proporcionan IDs de registro, debe existir uno por cada
entidad. Las salidas de Presence Engine están prohibidas como entradas.

## Ejemplo neutro

`configuration.example.json` contiene una cámara PTZ ficticia, Frigate,
Bermuda, MTR y radar. El archivo forma parte de las pruebas y debe continuar
siendo aceptado por el parser.

Cada cámara puede declarar `availability_entity_ids`. Todos los canales
declarados deben tener un estado distinto de `unknown`, `unavailable`, `none`
o vacío para aceptar evidencia nueva de esa cámara. Cuando alguno deja de
estar disponible, el motor retira únicamente la evidencia visual de esa
cámara, marca la cobertura degradada y conserva las demás fuentes. La última
imagen confirmada se mantiene separada de la evidencia activa.

`admission_mode` controla qué detecciones de una cámara pertenecen al dominio
de presencia. El valor predeterminado `any_detection` conserva toda detección
y resuelve su ubicación con zonas, perfil, área fija o alcance de cámara.
`mapped_current_zone` exige exactamente una zona actual incluida en
`zone_to_area`: una detección fuera de esas zonas no crea presencia ni un
resultado aislado de reconocimiento. Si un evento admitido abandona la zona,
su evidencia se finaliza; puede reactivarse si el mismo objetivo vuelve a una
zona válida. Este modo requiere un `zone_to_area` no vacío.

`availability_registry_ids` puede emparejarse uno a uno con esas entidades para
resolver renombres mediante el registro soportado de Home Assistant.
`availability_unavailable_states` permite ampliar los estados no fiables para
dispositivos que publiquen valores propios; por defecto incluye estados
desconocidos, desconectados, `off` y `down`.

Las fuentes compuestas, como un contador total con varios contadores de zona,
solo recuperan su cobertura cuando todos sus canales configurados vuelven a
tener un estado utilizable. La recuperación parcial no reactiva observaciones
anteriores.

Un teléfono o tracker ausente no implica una avería de sus receptores ni
ausencia de su propietario. Los receptores deben configurarse como fuentes de
salud separadas cuando la instalación expone una entidad fiable para esa
capacidad.

El adaptador `source_health` acepta exactamente una entidad y nunca produce
presencia. Con `options.healthy_states` solo esos estados representan una
fuente operativa; cualquier otro estado degrada esa capacidad. Como
alternativa, `options.unhealthy_states` enumera únicamente los estados de fallo
y cualquier otro valor se considera saludable. Si no se configura ninguna de
las dos listas, `unknown`, `unavailable`, `none` y el estado vacío son fallos.
No se pueden combinar ambas listas. Debe crearse una fuente independiente por
dispositivo para que una reconexión no oculte la caída de otro.

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
