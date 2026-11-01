"""Nexus demo · restricciones para los usuarios de demostración.

Home Assistant no tiene permisos por servicio ni por pantalla para un usuario que no es administrador. Este componente
(solo se instala en equipos con el modo demo activo) los agrega del lado del servidor, para los usuarios que figuran en
/config/www/nexus/entornos.json (por ejemplo juan -> dashboard-hogar) y que NO son administradores:

  · no pueden cambiar su contraseña, crear tokens de larga duración, borrar sesiones ni tocar la verificación en dos pasos
  · solo pueden abrir su propio dashboard (aunque escriban la dirección de otro)
  · solo pueden ejecutar servicios de dispositivos (luces, persianas, cerraduras, alarma, aire acondicionado...);
    nada de servicios del sistema, de Orion (rest_command), notificaciones, copias de seguridad, etc.

El administrador no se ve afectado. Si algo de esto falla al aplicarse, se deja registrado y Home Assistant sigue normal.
"""
from __future__ import annotations

import json
import logging
import os

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.exceptions import Unauthorized
from homeassistant.helpers.typing import ConfigType

DOMAIN = "nexus_demo"
_LOGGER = logging.getLogger(__name__)

ENTORNOS = "www/nexus/entornos.json"

# Servicios permitidos a los usuarios demo: solo dominios de dispositivos y escenas de la demo.
DOMINIOS_PERMITIDOS = {
    "light", "switch", "cover", "lock", "climate", "alarm_control_panel", "fan", "humidifier", "media_player",
    "scene", "script", "input_boolean", "input_number", "input_select", "input_button", "button", "number",
    "select", "siren", "valve", "vacuum", "water_heater", "lawn_mower", "todo", "shopping_list",
}
SERVICIOS_BLOQUEADOS = {("script", "reload"), ("scene", "reload"), ("scene", "apply"), ("scene", "create"),
                        ("input_boolean", "reload"), ("input_number", "reload"), ("input_select", "reload"),
                        ("input_button", "reload")}

# Comandos del websocket que un usuario demo no puede usar (autenticación y sesiones propias).
WS_BLOQUEADOS = (
    "config/auth_provider/homeassistant/change_password",
    "auth/long_lived_access_token",
    "auth/delete_refresh_token",
    "auth/delete_all_refresh_tokens",
    "auth/refresh_token_set_expiry",
    "auth/setup_mfa",
    "auth/depose_mfa",
)


def _cargar_usuarios(hass: HomeAssistant) -> dict[str, str]:
    ruta = hass.config.path(ENTORNOS)
    try:
        with open(ruta, encoding="utf-8") as f:
            return {k.lower(): v for k, v in (json.load(f).get("usuarios") or {}).items()}
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("nexus_demo: no pude leer %s (%s): sin restricciones hasta que exista", ruta, err)
        return {}


def _dashboard_del_usuario(usuarios: dict[str, str], user) -> str | None:
    """Dashboard (url_path) del usuario si es de demostración (no administrador y figura en entornos.json)."""
    if user is None or user.is_admin or not user.name:
        return None
    return usuarios.get(user.name.lower())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    usuarios = await hass.async_add_executor_job(_cargar_usuarios, hass)
    estado = {"usuarios": usuarios}

    # --- servicios: lista blanca por dominio (cubre websocket, REST y scripts lanzados por el usuario) ---
    # (ServiceRegistry usa __slots__: no se puede reemplazar en la instancia, se parchea la clase)
    try:
        clase = type(hass.services)
        if not getattr(clase, "_nexus_demo_parche", False):
            original = clase.async_call

            async def async_call_con_guardia(self, domain, service, *args, **kwargs):
                contexto: Context | None = kwargs.get("context") or (args[2] if len(args) > 2 else None)
                if contexto is not None and contexto.user_id:
                    user = await hass.auth.async_get_user(contexto.user_id)
                    if _dashboard_del_usuario(estado["usuarios"], user) is not None and (
                        domain not in DOMINIOS_PERMITIDOS or (domain, service) in SERVICIOS_BLOQUEADOS
                    ):
                        _LOGGER.warning("nexus_demo: bloqueado %s.%s para el usuario demo %s", domain, service, user.name)
                        raise Unauthorized(context=contexto, permission="demo", user_id=contexto.user_id)
                return await original(self, domain, service, *args, **kwargs)

            clase.async_call = async_call_con_guardia
            clase._nexus_demo_parche = True
    except Exception:  # noqa: BLE001
        _LOGGER.exception("nexus_demo: no pude proteger los servicios")

    # --- websocket: comandos de autenticación y dashboards ajenos ---
    async def proteger_websocket(_evento=None) -> None:
        try:
            comandos = hass.data.get("websocket_api")
            if not isinstance(comandos, dict):
                _LOGGER.error("nexus_demo: no encuentro la tabla de comandos del websocket")
                return
            estado["usuarios"] = await hass.async_add_executor_job(_cargar_usuarios, hass)

            def envolver(tipo, permitir):
                if tipo not in comandos:
                    return
                handler, schema = comandos[tipo]

                @callback
                def guardia(hass_, connection, msg):
                    dashboard = _dashboard_del_usuario(estado["usuarios"], connection.user)
                    if dashboard is not None and not permitir(dashboard, msg):
                        _LOGGER.warning("nexus_demo: bloqueado %s para el usuario demo %s", tipo, connection.user.name)
                        connection.send_error(msg["id"], "unauthorized", "No disponible en la demostración")
                        return
                    handler(hass_, connection, msg)

                comandos[tipo] = (guardia, schema)

            for tipo in WS_BLOQUEADOS:
                envolver(tipo, lambda dashboard, msg: False)
            # la configuración de un dashboard solo se entrega si es el del propio usuario
            envolver("lovelace/config", lambda dashboard, msg: msg.get("url_path") == dashboard)
            _LOGGER.info("nexus_demo: restricciones activas para %s", ", ".join(sorted(estado["usuarios"])) or "nadie")
        except Exception:  # noqa: BLE001
            _LOGGER.exception("nexus_demo: no pude proteger el websocket")

    # los comandos los registran otros componentes: se envuelven cuando ya arrancó todo
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, proteger_websocket)
    return True
