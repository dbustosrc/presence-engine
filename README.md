# Presence Engine Core

Motor determinista y agnóstico de plataforma para normalizar evidencia de
presencia, mantener sus revisiones y producir resultados reutilizables.

Este repositorio contiene únicamente el núcleo de dominio. No importa Home
Assistant, MQTT, Frigate ni clientes de red; tampoco contiene nombres de
entidades, dispositivos, cámaras, habitaciones o personas de una instalación
real. Los adaptadores pertenecen a una etapa posterior.

## Responsabilidades

- Contratos inmutables para observaciones, identidad, ubicación, conteo,
  imágenes y tiempos.
- Registro idempotente por fuente/observación con revisiones independientes por
  dimensión.
- Interpretación geométrica explícita de zonas actuales y contexto PTZ.
- Resolución de detecciones históricas sin confundir hora del hecho con hora de
  reconocimiento/localización.
- Snapshot actual que mantiene separados persona, dispositivo y animal, y usa
  intervalos cuando la evidencia no permite un conteo exacto.

## Fuera de alcance

- Suscripciones y entidades de Home Assistant.
- Transporte MQTT o REST.
- Texto, destino y política de entrega de notificaciones.
- Movimiento físico PTZ.
- Persistencia de largo plazo o reemplazo de Recorder.

## Pruebas

Desde este directorio:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Las pruebas usan exclusivamente nombres y geometrías sintéticas.

## Documentación

- `docs/contract.md`: semántica del contrato v1 y límites entre capas.
- `docs/regression-matrix.md`: invariantes y su prueba ejecutable.
