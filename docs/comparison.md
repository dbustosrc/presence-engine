# Protocolo N4 — comparación sin efectos

## Principio

El motor anterior no es la verdad de referencia. Cada diferencia se contrasta
contra una escena física conocida, evidencia original o fixture con expectativa
explícita.

## Preparación

- Registrar versiones de Home Assistant, Frigate e integración.
- Renovar la referencia semántica de YAML y dashboards inmediatamente antes de
  instalar.
- Confirmar que `comparison_mode` está activo.
- Confirmar que ningún consumidor operativo escucha el evento
  `presence_engine_result` ni consulta sus entidades para actuar.

## Verificación de seguridad

Buscar y rechazar cualquier ruta que:

- publique MQTT o MQTT Discovery;
- llame servicios de Home Assistant para notificar, mover PTZ o escribir
  trackers;
- modifique automatizaciones, scripts, templates o dashboards existentes;
- consuma como evidencia una salida pública del motor anterior o del nuevo.

## Muestras

1. Reproducir los fixtures de regresión y registrar revisión, conteo, identidad,
   ubicación, fuentes, conflictos y tiempos.
2. Observar datos normales durante un periodo controlado.
3. Observar una ráfaga de eventos Frigate y cambios rápidos de sensores.
4. Comparar memoria, tiempo de proceso, fallos de adaptador y crecimiento del
   estado persistido.
5. Consultar `presence_engine.get_snapshot` desde un script de prueba sin
   efectos y comparar su `revision` con la entidad diagnóstica de revisión.

## Resultado

El informe de diferencias clasifica cada caso como:

- corrección demostrada por verdad física o fixture;
- diferencia esperada y justificada;
- defecto del candidato;
- evidencia insuficiente, sin convertirla en éxito.

N4 solo se cierra si no reaparece un fallo conocido, no hay cola creciente ni
bloqueo perceptible y no se duplica ningún efecto externo.
