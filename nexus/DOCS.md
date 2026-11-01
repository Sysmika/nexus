# Nexus by Orion

Convierte este Home Assistant en **Nexus by Orion**: marca, PWA, módulo de Soporte con tickets en Orion y dashboard de entrada.

## Uso
1. Pegá el **código de instalación** (lo genera Orion para este cliente).
2. Si ya conocés la dirección HTTPS por la que se accede a este HA (dominio o túnel), pegala en **url_publica**: Orion registra solo el webhook de respuestas.
3. **Iniciá** el add-on y mirá el registro. Al terminar verifica la configuración y reinicia Home Assistant.

## Sin Orion (pruebas)
Dejá `codigo` vacío y completá `cliente_id`, `api_key` y `webhook_id`.

## Pantalla de login con la marca Nexus
El add-on instala el componente `nexus_login` (en `/config/custom_components`) y agrega la línea `nexus_login:` a `configuration.yaml` (con copia de seguridad). La página de inicio de sesión muestra el logo de Nexus by Orion y "Powered by Home Assistant", sin tocar el inicio de sesión en sí. Se instala al iniciar el add-on, también en equipos que ya estaban instalados, y **se activa en el próximo reinicio de Home Assistant**. Si algo falla, el login se ve como el original.

## Tema Nexus (pantallas internas)
El add-on instala el tema **Nexus**: azul marino de la marca para Configuración y el resto de las pantallas internas, con el logo como marca de agua. Se deja como tema por defecto una sola vez; después cada usuario puede elegir otro en su perfil (Perfil > Tema). El dashboard Nexus no se toca. Los cambios de logo y tema llegan con cada actualización del add-on y se activan en el próximo reinicio de Home Assistant.

## Alertas por email de dispositivos caídos
El add-on instala el paquete `packages/orion_alertas.yaml`. Cada 5 minutos revisa los dispositivos con la etiqueta **Orion vigilar** y le informa a Orion los que llevan más de 15 minutos en estado `unavailable`. Orion lleva el estado y manda un email cuando un dispositivo cae y otro cuando se recupera (no repite mientras siga caído). Llega por email (ficha del cliente y administradores de Orion) y también por WhatsApp (celular de la ficha del cliente y número interno de Orion), así que si falla un canal avisa el otro. Usa la misma API key que Soporte: no hay nada que configurar, solo etiquetar los dispositivos. Se instala también en equipos que ya estaban instalados (si tienen el paquete de Soporte) y **se activa en el próximo reinicio de Home Assistant**. Además de este aviso, sigue vigente el ticket automático a las 24 hs sin reportar.

## Modo demo (equipos de demostración para clientes)
Con la opción **`modo_demo`** activada, el add-on deja el Home Assistant "completo" sin ningún dispositivo real, para mostrárselo a los clientes. **No activar en equipos de clientes reales.**
- **Tres entornos**: Hogar, Oficina y Comercio. Cada uno trae sus entidades ficticias (sensores que varían con la hora, luces, persianas, aire acondicionado, cerraduras, alarma, escenas, UPS/internet/NAS en Oficina, ventas y cadena de frío en Comercio) y su dashboard propio.
- **Historial**: se precargan 14 días de estadísticas, así los gráficos y la energía se ven con historia desde el primer día.
- **Usuarios de demostración** (sin permisos de administrador): `juan` ve Hogar, `pedro` Oficina y `maria` Comercio. Todos usan la clave de la opción **`demo_clave`** (mínimo 8 caracteres; la cargás vos). Cada uno entra directo a su dashboard y no ve los demás en el menú (es solo visual, no seguridad). El administrador ve todo.
- **Aviso de caída**: sensores de cada entorno vienen con la etiqueta *Orion Vigilar*; el interruptor "Demo · Simular falla…" de cada rubro deja un sensor sin respuesta para mostrar el aviso por email/WhatsApp.
- Es idempotente y no demora el acceso remoto: corre aparte al iniciar el add-on. Si agrega contenido nuevo, reinicia Home Assistant una vez.
El contenido sale de `payload/demo` y lo genera `tools/gen_demo.py` del repositorio.

## Token de Home Assistant para Orion
Al instalar con un paquete de Orion, el add-on inicia sesión como el usuario administrador del paquete, crea un token de acceso de larga duración ("Orion (automático)") y se lo entrega a Orion, que lo guarda en la ficha de la instalación. Así Orion puede consultar este Home Assistant sin cargar el token a mano. No se muestra en el registro. Solo se hace en instalaciones nuevas o con paquete regenerado (necesita la contraseña que viene en el paquete).

## Acceso remoto (Tailscale)
Si el paquete de Orion incluye **acceso remoto**, después de instalar el add-on le pide a Orion una clave de un solo uso (que vence en 1 hora) y conecta este equipo a la red privada de Orion (`tag:ha`). Orion anota el nodo solo. El add-on queda encendido para mantener esa conexión; el estado se conserva en sus datos y no hace falta volver a autorizar.

Crea la interfaz de red de Tailscale (`/dev/net/tun`, permisos `NET_ADMIN` y `NET_RAW`), igual que el add-on comunitario. No instales además el add-on comunitario de Tailscale en este mismo equipo: se pisarían.

## Después de reiniciar
- Ajustes > Sistema > Red > Servidor HTTP: si se publica con túnel/proxy, activar *Confiar en X-Forwarded-For* y agregar el proxy de confianza.
- Crear la etiqueta **Orion vigilar** (`orion_vigilar`) y asignarla a los dispositivos a monitorear.
- Crear el usuario del cliente **sin permisos de administrador**.

Nexus funciona sobre Home Assistant (Open Home Foundation, Apache 2.0).
