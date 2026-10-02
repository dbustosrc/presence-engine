# Configuración

La integración se configura mediante formularios nativos. Para editar una
instalación existente, abrir **Ajustes → Dispositivos y servicios → Presence
Engine → ⋮ → Reconfigurar**. El menú separa áreas, identidades, cámaras, fuentes,
descubrimiento y Frigate. «Configurar» mantiene las opciones de ejecución:
modo comparación, límite de registros y retraso de persistencia.

Los cambios son un borrador hasta confirmar «Guardar». Abrir, navegar o cancelar
no altera la instalación activa. Los IDs existentes son estables; quitar un área
o una cámara todavía referenciada produce un error en lugar de romper sus
fuentes. Una fuente deshabilitada permanece como excepción explícita al
autodescubrimiento.

Los formularios conservan campos no editados y extensiones del JSON existente.
Las secciones desplegables permiten configurar contexto PTZ, disponibilidad y
opciones avanzadas sin una interfaz propia ni pérdida de funcionalidad.

## JSON avanzado opcional

El menú avanzado permite copiar o importar la representación canónica
`schema_version: 1`. No es necesario escribir JSON para configurar la integración.
La validación es la misma para formularios e importación; importar solo modifica
el borrador y también requiere «Guardar».

La representación mostrada omite la contraseña de Frigate. Al reimportar se
conserva la contraseña guardada únicamente si URL y usuario no han cambiado y
no se suministra otra contraseña. Un JSON importado puede contener información
privada de la instalación: no debe publicarse.

## Rostros e identidades

El descubrimiento facial está habilitado de forma predeterminada. Un
reconocimiento recibido por MQTT crea el registro diagnóstico de identidad
solo cuando el adaptador lo acepta con su umbral y las políticas existentes de
la cámara. No se crean registros duplicados por los siguientes reconocimientos;
los registros observados sobreviven a los reinicios.

En «Identidades» se asocian explícitamente nombres reconocidos, entidades
`person` y sensores de área Bermuda a un ID canónico. No se vinculan personas
por parecido de nombres. Un rostro sin asociación conserva la identidad
devuelta por Frigate, sin inventar una asociación con un teléfono.

### Catálogo Frigate opcional

La escucha de reconocimientos MQTT funciona sin URL de API. Configurar una URL
en «Frigate» permite ofrecer los nombres registrados como opciones del formulario.
El catálogo por sí solo no crea entidades ni evidencia de presencia.

La consulta ocurre únicamente al marcar «Actualizar el catálogo de rostros»
en Reconfigurar → Frigate y enviar el formulario. No hay consultas al iniciar,
ante reconocimientos MQTT, tras reconexiones ni periódicas. Si cambian los datos
de conexión, primero guardarlos y volver a abrir Frigate para actualizar el
catálogo. La UI informa de un fallo y conserva los nombres anteriores. Las
solicitudes manuales simultáneas comparten una consulta.

Se admite la API sin autenticación o inicio de sesión mediante usuario y
contraseña sobre HTTPS. `cookie_name` permite usar un nombre de cookie distinto
de `frigate_token`. El antiguo campo `availability_topic` ya no se utiliza para
sincronizar el catálogo. No se siguen
redirecciones ni se incluyen credenciales en exportaciones o diagnósticos.

Cada petición tiene un límite de 10 segundos y el catálogo admite hasta 1 MiB.
Un fallo conserva el catálogo anterior, no impide procesar MQTT ni degrada por
sí solo la cobertura de los sensores. Se guardan nombres y asociaciones acotados
por el límite de registros, no imágenes del catálogo. Eliminar un rostro del
catálogo no borra el registro histórico ni demuestra ausencia de la persona.
La carpeta de entrenamiento `train` no se presenta como nombre de persona.

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

### Señales BLE por receptor

La fuente `bermuda_signal` captura cambios de una entidad de sensor por
dispositivo, receptor y métrica. Se configura en **Fuentes → Añadir → Señal de
receptor BLE**, sin JSON obligatorio. Seleccionar exactamente una entidad,
indicar `device_id`, `receiver_id` y `metric` (`rssi`, `distance` o
`distance_unfiltered`). Usar el mismo dispositivo/receptor para sus distintos
canales; el área opcional describe dónde está el **receptor**, no el dueño.
La asociación `identity` es opcional y nunca demuestra ubicación personal.

Solo se admiten valores finitos con unidad compatible: RSSI `dBm`, distancias
`m`, `cm` o `mm`. Se conserva la unidad original; no hay conversión o
trilateración implícita. Cero válido, valor desconocido, desconexión, unidad
incompatible y ausencia de muestras recientes son estados distintos.
No asignar el RSSI del receptor más cercano a un receptor fijo cuando la
entidad cambia de observador: configurar únicamente canales cuya procedencia
sea conocida. No se descubren ni adivinan automáticamente dispositivos,
receptores o propietarios por el nombre de una entidad.

`options.history_seconds` (1–3600, predeterminado 120) y `history_limit`
(1–256, predeterminado 32) acotan cada serie. Además hay un máximo global de
1024 muestras, o `max_records` si es menor, y una marca `truncated` cuando se
descartan muestras por cantidad. Una última firma por fuente evita que un
refresco de atributos resucite un valor idéntico después de caducar/reiniciar.
El historial restaurado conserva sus horas y valida contra la configuración.
Estos límites son de memoria; no cambian la continuidad personal de 90 s.

La hora es `last_updated` del estado HA cuando existe (`ha_state_update`),
distinta de recepción; no se presenta como hora de un anuncio BLE crudo. Sin
esa metadata se utiliza el reloj del envelope. Los duplicados, datos fuera de
orden y refrescos sin cambio de valor/unidad/estado no renuevan las muestras.
Conservar un único valor no demuestra inmovilidad ni que el teléfono acompañe
a su propietario; detectar esa asociación corresponde a la fusión temporal.

Las señales se guardan mediante la persistencia existente, pero no producen
observaciones de personas, detecciones, revisiones o atributos del sensor de
presencia. `presence_engine.get_snapshot` incluye un resumen
`device_signal_histories`; `include_signal_samples: true` solicita las series
acotadas. Los diagnósticos descargables incluyen el resumen, sin payloads
originales, direcciones BLE ni imágenes. Un teléfono no observado no prueba
avería del receptor: configurar su salud mediante `source_health` si hay una
entidad que represente esa capacidad.

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
