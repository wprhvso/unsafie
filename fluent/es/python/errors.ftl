err-trace = [trace_id=<code>{ $trace_id }</code>]

err-generic = Algo salió mal por nuestra parte. Inténtalo de nuevo
err-empty = El modelo devolvió una respuesta vacía. Inténtalo de nuevo
err-timeout = La respuesta tardó demasiado y se cortó. Prueba con una petición más corta
err-storage = No se pudo guardar la conversación: la base de datos no está disponible

err-gateway-unreachable = La pasarela de IA no responde. Inténtalo dentro de un minuto
err-gateway-auth = El bot no está autorizado en la pasarela de IA
err-gateway-capacity = Todas las sesiones del modelo están ocupadas o caducadas. Inténtalo dentro de unos minutos

err-rate-limit = El proveedor del modelo está limitando ahora mismo nuestra frecuencia de peticiones. Inténtalo dentro de un minuto
err-upstream-auth = La pasarela no pudo autenticarse ante el proveedor del modelo
err-upstream-unavailable = El proveedor del modelo no está disponible temporalmente. Inténtalo dentro de unos minutos
err-upstream-timeout = El modelo no respondió a tiempo. Prueba con una petición más corta
err-upstream-unreachable = No se pudo contactar con el proveedor del modelo: la petición de red falló
err-upstream-rejected = El proveedor del modelo rechazó la petición por no ser válida

err-context-length = La conversación es más larga de lo que el modelo puede leer. Empieza otra o envía un texto más corto
err-content-filter = El modelo se detuvo: sus filtros de seguridad bloquearon la respuesta
err-prompt-blocked = El modelo se negó a responder: sus filtros de seguridad bloquearon la petición
err-model-not-found = El modelo elegido no está disponible. Elige otro: /gemini31 o /gemini3f
err-unsupported-content = Este formato de archivo adjunto no es compatible

err-retry = 🔄 Reintentar
err-retry-gone = Ya no queda nada que reintentar — envía el mensaje de nuevo

chat-unsupported = Solo se admiten mensajes de texto

chat-document-unreadable = No he podido leer ese archivo
