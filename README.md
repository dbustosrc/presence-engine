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
- Proximidad posible cerca del AP para dispositivos Wi-Fi personales vinculados,
  de confianza baja y sin confirmar cuerpos ni desplazar un rostro vigente.
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

La [política de evidencia y confianza](docs/evidence-policy.md) acordada distingue
actividad de área, presencia doméstica inferida y proximidad personal estimada
al AP de una habitación corporalmente confirmada. Define corroboración entre
fuentes sin exigir Bermuda; su implementación completa sigue pendiente. Las
notas versionadas siguientes conservan el comportamiento realmente publicado.

`0.5.34` evita que una persona nativa derivada de un GPS configurado prolongue
un fix doméstico antiguo. El dato directo conserva su caducidad; la falta de
comunicación no demuestra una salida. Las referencias BLE débiles comparan
toda la serie reciente y resisten saltos de etiqueta solo mientras sus rangos
siguen respaldándolas. Mantiene alternativas, retiro por invalidación/caducidad,
prioridad corporal inmediata y 90 segundos, sin introducir otra espera fija.

`0.5.29` corrige el reloj de estabilidad de los conteos MTR compuestos y
reevalúa su ventana existente de tres segundos sin polling. Una entrada antigua
no confirma instantáneamente un aumento reciente. Conserva máximos y mediciones,
sin identificar ecos ni descartar objetivos; un conteo que persiste se consolida
y un pulso terminado no deja un temporizador pendiente.

`0.5.31` contrasta la banda de las dos últimas mediciones BLE recientes con
otros receptores físicos elegibles antes de admitir una referencia débil.
Lecturas solapadas no siguen el cambio de etiqueta radio; no se convierte esta
comparación de señal en geometría o confirmación corporal. Un agregado anónimo
de planta mantiene la referencia y su reloj original, sin aumentar el mínimo
como si acreditara otro cuerpo independiente. Cuando BLE no aporta una habitación
elegible, una identidad doméstica puede conservar proximidad Wi-Fi vinculada de
confianza baja. El cuerpo identificado conserva prioridad y el plazo de asociación
de 90 segundos no cambia.

`0.5.28` conserva una habitación posible de confianza baja cuando solo existen
presencia doméstica, área Bermuda configurada y dos mediciones BLE recientes
del receptor correspondiente. No equivale a presencia corporal, reconocimiento
ni teléfono transportado; evidencia corporal, señal perdida o reinicio retiran
esa referencia. No activa ocupación física ni renueva el reloj por cada paquete.
La proyección pública expone por separado la ubicación de los dispositivos y
su conexión Wi-Fi, sin convertir el AP en ubicación de una persona.

`0.5.27` admite una asociación probable antes de cambiar el área Bermuda cuando
existen co-localización previa de un solo cuerpo, mediciones radar nuevas,
vaciado medido del mismo origen, tendencias opuestas de dos receptores y presencia
actual en destino. No convierte distancias en identidad ni en geometría global;
el área original del dispositivo permanece independiente. Conserva los plazos,
prioriza cuerpos identificados y exige respaldo corporal posterior para otra
llegada, sin renovar una llegada por paquetes radio o un contador mantenido.

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
- `docs/evidence-policy.md`: política objetivo de actividad, estimación y confianza.
- `docs/regression-matrix.md`: invariantes y su prueba ejecutable.
- `docs/installation.md`: publicación e instalación por HACS.
- `docs/comparison.md`: protocolo de comparación sin efectos.
- `docs/public-projections.md`: contrato de las entidades públicas.
- `docs/rollback.md`: reversión soportada de la integración.
- `CHANGELOG.md`: notas de cada versión.
