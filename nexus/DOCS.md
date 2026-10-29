# Nexus by Orion

Convierte este Home Assistant en **Nexus by Orion**: marca, PWA, módulo de Soporte con tickets en Orion y dashboard de entrada.

## Uso
1. Pegá el **código de instalación** (lo genera Orion para este cliente).
2. Si ya conocés la dirección HTTPS por la que se accede a este HA (dominio o túnel), pegala en **url_publica**: Orion registra solo el webhook de respuestas.
3. **Iniciá** el add-on y mirá el registro. Al terminar verifica la configuración y reinicia Home Assistant.

## Sin Orion (pruebas)
Dejá `codigo` vacío y completá `cliente_id`, `api_key` y `webhook_id`.

## Después de reiniciar
- Ajustes > Sistema > Red > Servidor HTTP: si se publica con túnel/proxy, activar *Confiar en X-Forwarded-For* y agregar el proxy de confianza.
- Crear la etiqueta **Orion vigilar** (`orion_vigilar`) y asignarla a los dispositivos a monitorear.
- Crear el usuario del cliente **sin permisos de administrador**.

Nexus funciona sobre Home Assistant (Open Home Foundation, Apache 2.0).
