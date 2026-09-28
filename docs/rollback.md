# Reversión de una actualización

Si una versión nueva falla, selecciona en HACS la última versión validada de
Presence Engine y reinicia Home Assistant. Conserva la entrada de configuración:
el motor restaurará solo la evidencia compatible con el contrato y las fuentes
actuales. Comprueba después que la integración carga, que sus sensores responden
y que las suscripciones MQTT no se duplican.

Antes de volver a una versión anterior a un cambio de esquema, guarda una copia
local de la configuración y verifica su compatibilidad. Si la reversión requiere
retirar la integración, desactiva primero los consumidores que dependen de sus
entidades y eventos. No borres manualmente archivos de Home Assistant ni restaures
el procesador anterior en paralelo: podría crear resultados duplicados.
