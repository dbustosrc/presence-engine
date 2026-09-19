# Reversión de la candidata

La integración no reemplaza consumidores automáticamente. Las proyecciones
públicas candidatas se crean deshabilitadas por defecto. Mientras ninguna haya
sido conectada a consumidores, la reversión no exige restaurar automatizaciones,
scripts, templates, trackers ni dashboards.

## Procedimiento

1. Eliminar la entrada `Presence Engine` desde **Settings > Devices &
   services**.
2. Reiniciar Home Assistant y confirmar que no quedan entidades cargadas del
   dominio `presence_engine`.
3. Desinstalar `Presence Engine` desde HACS.
4. Reiniciar Home Assistant una vez más si HACS lo solicita.
5. Confirmar que el sistema anterior mantiene exactamente sus escritores y
   consumidores operativos.

La eliminación de la entrada descarga listeners, suscripciones MQTT, timer de
caducidad, entidades y coordinador. El almacenamiento privado que Home
Assistant conserve deja de ser consumido y puede retirarse mediante los
mecanismos soportados si fuera necesario; nunca se borra manualmente desde el
servidor.

Si una proyección o evento propio se hubiera conectado a un consumidor, se
deshabilita primero ese consumidor y solo después se elimina la entrada.
