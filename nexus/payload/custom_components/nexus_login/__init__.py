"""Nexus by Orion: agrega la marca Nexus a la pantalla de login de Home Assistant.

Inserta antes de </body>, solo en GET /auth/authorize (la página de login), el logo de Nexus
(/local/nexus/logo.png, que instala el add-on) y la leyenda "Powered by Home Assistant". El logo de
Home Assistant de la propia página no se toca. Es a prueba de fallos: ante cualquier error devuelve la
página original sin cambios, así que nunca puede impedir el acceso.

Cuando se cargan los componentes propios el servidor HTTP de HA ya arrancó y su lista de middlewares está
congelada (no se puede agregar uno): por eso se envuelve el handler de la ruta del login.
"""
from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import make_mocked_request

from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

DOMAIN = "nexus_login"
CONFIG_SCHEMA = cv.empty_config_schema(DOMAIN)
_LOGGER = logging.getLogger(__name__)

RUTA_LOGIN = "/auth/authorize"
MARCA = """
<style>
#nexus-login-brand{position:fixed;top:14px;left:0;right:0;display:flex;justify-content:center;
  pointer-events:none;z-index:5}
#nexus-login-brand .nl-caja{background:#fff;border-radius:14px;padding:8px 18px;
  box-shadow:0 2px 14px rgba(0,0,0,.35)}
#nexus-login-brand img{display:block;height:92px;max-width:78vw;width:auto;object-fit:contain}
#nexus-login-powered{position:fixed;bottom:10px;left:0;right:0;text-align:center;
  font:12px/1.3 Roboto,Arial,sans-serif;color:#fff;opacity:.7;pointer-events:none;z-index:5}
@media (max-height:620px){#nexus-login-brand img{height:56px}}
</style>
<div id="nexus-login-brand"><div class="nl-caja"><img src="/local/nexus/logo.png" alt="Nexus by Orion"></div></div>
<div id="nexus-login-powered">Powered by Home Assistant</div>
"""


def _inyectar(html: str) -> str | None:
    """Devuelve el HTML con la marca, o None si no corresponde tocarlo."""
    if "nexus-login-brand" in html or "</body>" not in html:
        return None
    return html.replace("</body>", MARCA + "</body>", 1)


async def _modificar(hass: HomeAssistant, request: web.Request, resp):
    """Devuelve la respuesta del login con la marca, o la original si algo no corresponde o falla."""
    try:
        if request.method != "GET" or request.path != RUTA_LOGIN:
            return resp
        texto = None
        if isinstance(resp, web.FileResponse):
            ruta = getattr(resp, "_path", None)
            if ruta:
                texto = await hass.async_add_executor_job(Path(ruta).read_text, "utf-8")
        elif isinstance(resp, web.Response) and resp.body is not None:
            cuerpo = resp.body
            texto = cuerpo.decode("utf-8") if isinstance(cuerpo, (bytes, bytearray)) else str(cuerpo)
        if texto is None:
            return resp
        nuevo = _inyectar(texto)
        if nuevo is None:
            return resp
        salida = web.Response(body=nuevo.encode("utf-8"), content_type="text/html", charset="utf-8")
        for cab in ("Cache-Control", "X-Content-Type-Options", "Referrer-Policy"):
            if cab in resp.headers:
                salida.headers[cab] = resp.headers[cab]
        return salida
    except Exception:  # noqa: BLE001 - nunca romper el login
        _LOGGER.debug("nexus_login: no se pudo modificar el login, se sirve el original", exc_info=True)
        return resp


def _envolver(hass: HomeAssistant, original):
    async def nexus_login_handler(request: web.Request):
        resp = await original(request)
        return await _modificar(hass, request, resp)

    nexus_login_handler._nexus_login = True  # type: ignore[attr-defined]
    return nexus_login_handler


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Engancha la marca a la ruta del login."""
    try:
        info = await hass.http.app.router.resolve(make_mocked_request("GET", RUTA_LOGIN))
        ruta = getattr(info, "route", None)
        if ruta is None or info.http_exception is not None:
            _LOGGER.warning("nexus_login: no encontré la ruta %s; el login queda como el original", RUTA_LOGIN)
        elif not getattr(ruta.handler, "_nexus_login", False):
            ruta._handler = _envolver(hass, ruta.handler)
            _LOGGER.debug("nexus_login: marca Nexus activada en %s", RUTA_LOGIN)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("nexus_login: no se pudo activar; el login queda como el original", exc_info=True)
    return True
