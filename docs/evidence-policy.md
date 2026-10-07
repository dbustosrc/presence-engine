# Política de evidencia, estimación y confianza

Política acordada para la siguiente implementación. Este documento define el
comportamiento objetivo; no afirma que esté disponible en una versión publicada.
La estimación AP débil está implementada en 0.5.30. Desde 0.5.32, GPS se
normaliza como posición del dispositivo y la actividad auxiliar se expone
separada del conteo corporal. Combinaciones de corroboración adicionales
y su aceptación física siguen en la matriz, no se dan por completadas aquí.
Los contratos versionados, fixtures y pruebas existentes describen sus versiones
reales. La implementación y aceptación pendientes se mantienen en el plan actual.

## Actividad, presencia y ubicación no son lo mismo

- **Actividad de área:** una luz encendida, TV activo o altavoz reproduciendo
  aportan contexto positivo de actividad, de confianza muy baja pero no nula.
  Mostrar actividad en el área, sin nombre, especie ni número de personas.
- **Presencia doméstica inferida:** un teléfono/dispositivo personal conectado
  y explícitamente vinculado a una persona aporta evidencia positiva de esa
  persona en casa. No descartarla por falta de Bermuda, rostro o radar.
- **Proximidad estimada:** el AP puede justificar «cerca del AP del área», con
  confianza baja. No demuestra que el propietario esté dentro de esa habitación,
  ni mide metros; asociación Wi-Fi, roaming y cobertura pueden cruzar paredes.
- **Presencia corporal:** cámara, radar o detector físico aportan evidencia
  corporal en su cobertura. El radar/PIR no identifica persona ni especie.
- **Identidad reconocida:** un rostro aceptado identifica al sujeto; su ubicación
  requiere zona/contexto espacial válidos para el instante observado.

Un teléfono abandonado o equipos programados pueden seguir activos sin personas.
Por eso la evidencia doméstica positiva se conserva como inferencia, no como
certeza física. No convertir cada dispositivo en una persona ni cada actividad
en un cuerpo. Las inferencias no aumentan por sí solas el mínimo corporal
confirmado; el conteo conserva incertidumbre y solapamiento con otros sensores.

## Selección de dispositivos y actividad

Solo un dispositivo revisado como personal y con propietario explícito puede
respaldar una hipótesis de esa persona. Nombre, fabricante, IP, MAC o estar en
Google Wi-Fi no bastan para clasificarlo como personal. Routers, televisores,
tablets compartidas, altavoces, equipos fijos y dispositivos sin vínculo no
generan propietarios o individuos. Varios dispositivos del mismo dueño no son
varias personas. Una MAC sirve para reconciliar un vínculo confirmado, no para
adivinar quién es el dueño.

Revisar luces, TV y multimedia por capacidad y área conocidas. Distinguir
reproducción, pausa, encendido y disponibilidad; `unknown` no es actividad.
Conservar procedencia automática/remota y dependencia: una luz activada por el
propio resultado no devuelve otro voto independiente al motor. Puede mostrarse
como estado de actividad, pero no corroborar circularmente presencia. Varias
señales débiles no se convierten por cantidad en identidad o cuerpo confirmado.

## Grados y combinaciones

Separar confianza de identidad, ubicación, asociación persona–dispositivo y
conteo. «Muy baja» es contexto dentro del nivel bajo; «alta reforzada» y «máxima
corroboración» describen respaldo adicional dentro del nivel alto. No son nuevas
probabilidades ni nuevos valores del enum del contrato. No sumar porcentajes
faciales, RSSI, metros y contadores como si fueran la misma magnitud.

| Fuentes vigentes y compatibles | Resultado permitido | Confianza de ubicación personal |
|---|---|---|
| Luz, TV o reproducción multimedia | Actividad del área, sin individuo | Muy baja para contexto; identidad desconocida |
| Dispositivo de red sin propietario personal confirmado | Hecho del dispositivo; no persona | Desconocida para una persona |
| Teléfono personal conectado, sin AP mapeado | Presencia doméstica inferida, sin habitación | Baja, alcance casa |
| Teléfono personal + AP mapeado | Propietario posiblemente cerca del AP | Baja; no habitación exacta |
| GPS exterior reciente con precisión/reloj válidos | Posición geográfica del dispositivo | Alta/media para el dato del dispositivo; ubicación del propietario no confirmada |
| GPS doméstico | Contexto de casa, nunca habitación | Baja; evidencia corporal/radio interior prevalece |
| AP + radar compatible y asociación no ambigua | Estimación personal corroborada por presencia corporal | Media; si es ambiguo, conservar alternativas |
| Bermuda de un dispositivo personal | Estimación del propietario basada en ubicación del dispositivo | Media como máximo; bajar si cobertura/asociación son débiles |
| Varios proxies Bermuda consistentes | Mejor aproximación del dispositivo; no varios cuerpos | Mejora espacial del dispositivo, no identidad facial |
| Bermuda + mmWave con asociación temporal consistente | Ubicación probable de la persona | Alta si no hay actores/contradicciones que impidan la asociación |
| Cámara anónima + Bermuda + radar asociados | Ubicación corporal y personal corroboradas | Alta para ubicación; identidad sigue inferida |
| Rostro aceptado + zona actual válida | Persona identificada y localizada | Alta |
| Rostro + Bermuda o radar coincidentes | Identidad/ubicación con apoyo independiente | Alta reforzada |
| Rostro + Bermuda + radar coincidentes | Identidad, dispositivo y cuerpo compatibles | Máxima corroboración |

Son condiciones, no una suma automática ni una tabla que identifique a un
visitante por eliminación. Cámara anónima/radar y AP con dueño conocido pueden
describir actores distintos. Con varias personas o mascotas, conservar los
candidatos y disminuir confianza si el vínculo no está resuelto.

## Prioridades, contradicciones y tiempos

1. Usar la mejor evidencia disponible con el grado que merece. No exigir
   asociación corporal/movimiento para mostrar una estimación débil; sí exigir
   corroboración para elevarla o declarar un traslado personal fiable.
2. Reconocimiento corporal identificado y espacialmente válido prevalece sobre
   dispositivo/AP contradictorio. Un rostro en una cámara con área incierta
   confirma identidad, no una habitación que esa cámara no pudo medir.
3. Si persona y teléfono se contradicen, mantener sus ubicaciones separadas.
   Quietud del dispositivo más evidencia corporal del dueño en otro lugar puede
   apoyar separación; quietud sola no prueba abandono.
4. Estimar movimiento con series recientes de receptores identificados, rangos
   compatibles y trayectorias. Un área sin cambios o una única distancia no
   demuestran inmovilidad; un salto de etiqueta no demuestra movimiento.
5. Combinar evidencias del mismo período y cobertura, con relojes separados.
   Reconocimiento tardío/foto histórica no desplaza una ubicación actual posterior.
   La continuidad existente de 90 s es un máximo, no una espera obligatoria.
6. Un negativo requiere fuente sana, cobertura efectiva y medición válida.
   Ausencia de recepción, cámara orientada a otro sitio o salida del teléfono
   no demuestran ausencia del propietario.
7. No duplicar votos: rostro/objeto/contador de una cámara, zonas/telemetría de un
   radar, y área/distancias derivadas de los mismos anuncios BLE están relacionados.
   Proxies distintos aportan comparación espacial, no presencia humana múltiple.
8. Evidencia mejor puede corregir la estimación inmediatamente; cambios débiles
   y ruidosos requieren consistencia. Al perder soporte, rebajar a la siguiente
   evidencia válida sin conservar indefinidamente una certeza anterior.

## Presentación y fronteras

Mostrar por separado actividad, presencia inferida, proximidad estimada y
ubicación corporal corroborada. Explicar fuente, hora, confianza, contradicciones
y alternativas. «Cerca del AP de Area Alpha» no debe renderizarse como «Area
Alpha confirmada». La ausencia de una hipótesis personal no elimina la actividad
conocida del área. No convertir estas inferencias en reconocimiento facial,
notificaciones de detección ni votos de control físico sin respaldo suficiente.

La normalización mantiene hechos de dispositivos separados de cuerpos. La
fusión, no el dashboard, calcula la estimación y la corroboración. Ninguna parte
de esta política convierte distancia BLE en coordenadas exactas, inventa
geometría, compensa una limitación física con certeza falsa o exige Bermuda a
personas que solo tienen Wi-Fi.

## Validación pendiente, no funcionalidad ya acreditada

Usar las pruebas/corpus existentes para propietario con solo AP, dispositivo
compartido/fijo, teléfono abandonado, AP frente a rostro, combinación con radar,
actividad sin personas, realimentación, múltiples actores y caída de fuentes.
Añadir o actualizar expectativas solo junto a la implementación correspondiente;
no reescribir originales históricos ni ejecutar otra suite completa por estos
cambios documentales. Evaluar geometría opcional después, sin ampliar el plan
por versión ni exigir una nueva caminata cuando la evidencia conservada baste.
