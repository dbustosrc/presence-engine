# Reversión de la candidata

La versión `0.2.0` se instala como observadora y no reemplaza al sistema
operativo. Por eso la reversión no exige restaurar automatizaciones, scripts,
templates, trackers ni dashboards.

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

Si durante N4 se hubiera conectado accidentalmente un consumidor operativo al
evento propio, se deshabilita primero ese consumidor y solo después se elimina
la entrada.
