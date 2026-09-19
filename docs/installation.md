# Instalación

## Prerrequisitos de publicación

HACS solo admite repositorios públicos alojados en GitHub. Antes de publicar
esta integración se debe:

1. Confirmar como URL definitiva el repositorio público preparado en el
   manifest: `https://github.com/dbustosrc/presence-engine`.
2. Incorporar el icono de marca requerido por HACS.
3. Publicar una etiqueta y release versionadas después de que las validaciones
   del repositorio pasen.

No deben usarse URLs, usuarios ni assets provisionales para superar la
validación.

## Instalación por HACS

1. En HACS, abrir el menú y seleccionar **Custom repositories**.
2. Agregar la URL pública definitiva y seleccionar **Integration**.
3. Descargar la última versión estable de `Presence Engine`.
4. Reiniciar Home Assistant mediante su mecanismo normal.
5. Agregar la integración desde **Settings > Devices & services**.
6. Pegar la configuración privada validada para la instalación y conservar
   `comparison_mode: true` en las opciones.

No copiar archivos manualmente a `custom_components` ni editar la copia
instalada. Toda corrección se publica como una nueva versión y se actualiza por
HACS.

## Condiciones del modo comparación

- El sistema anterior sigue siendo el único escritor de trackers y el único
  emisor de notificaciones.
- Ninguna automatización operativa escucha `presence_engine_result` durante la
  comparación.
- Las entidades de Presence Engine se usan solo para observación y consulta.
- No se cambia ningún control PTZ ni se publica MQTT Discovery.
- La configuración privada permanece fuera del repositorio.

Antes de instalar se repiten hashes y comparación semántica de los YAML y
dashboards operativos. Si la instalación se realiza otro día, esta referencia
debe renovarse inmediatamente antes de instalar.
