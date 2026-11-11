#!/usr/bin/env python3
"""Nexus by Orion · Orion SysGestion (acceso al sistema de gestión web del cliente).

Dos pasos, independientes:
  1. Repositorio: agrega el repositorio de Orion SysGestion a la tienda de add-ons, SIN instalar nada.
     Así el add-on queda listo en el Marketplace para cuando el cliente lo contrate. Se hace una sola vez
     por equipo; si después alguien quita el repositorio, no se vuelve a agregar. Se desactiva con
     `sysgestion: false`.
  2. Activación: solo si se carga la opción `sysgestion_url` (la dirección del sistema de gestión del
     cliente) y `sysgestion_api_key` (la API key de Gestión de la instalación, que se genera en Orion AR).
     Ahí instala Orion SysGestion, le carga esa dirección y esa key y lo inicia. Si después cambia la dirección o la API key,
     actualiza la configuración y lo reinicia. Si el cliente lo desinstala, no se vuelve a instalar.
Corre aparte (en segundo plano), porque la primera instalación construye la imagen y puede tardar.
"""
import json
import os
import sys
import time
import urllib.error

import instalar as I
from replicator import _mismo_repo, _pedir

REPO = os.environ.get("NEXUS_SYSGESTION_REPO", "https://github.com/Sysmika/orion-sysgestion")
SLUG_BASE = "orion_sysgestion"  # slug del add-on dentro de su repositorio
DATOS = os.path.dirname(I.OPTIONS)  # /data, privado del add-on
MARCA_REPO = os.path.join(DATOS, "nexus_sysgestion_repo.json")
MARCA_ADDON = os.path.join(DATOS, "nexus_sysgestion.json")


def slug_repositorio(agregar):
    """Slug del repositorio en la tienda; si no está y `agregar`, lo agrega. None si no está."""
    repos = _pedir("GET", "/store/repositories")
    for r in repos if isinstance(repos, list) else []:
        if _mismo_repo(r.get("source") or r.get("url"), REPO):
            return r.get("slug", "")
    if not agregar:
        return None
    _pedir("POST", "/store/repositories", {"repository": REPO}, esperar=180)
    I.ok("Repositorio de Orion SysGestion agregado a la tienda (sin instalar)")
    for r in _pedir("GET", "/store/repositories") or []:
        if _mismo_repo(r.get("source") or r.get("url"), REPO):
            return r.get("slug", "")
    raise RuntimeError("la tienda no muestra el repositorio después de agregarlo")


def buscar_addon(repo_slug):
    for a in (_pedir("GET", "/store/addons").get("addons") or []):
        if a.get("repository") == repo_slug and a.get("slug", "").endswith("_" + SLUG_BASE):
            return a
    return None


def api_key_gestion(o):
    """La API key de Gestión de esta instalación (Orion AR → ficha de la instalación → Orion Gestión → Rotar API key).
    Es distinta de la de Soporte: se carga en la opción `sysgestion_api_key`."""
    return (o.get("sysgestion_api_key") or "").strip()


def leer_marca(ruta):
    try:
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return None


def guardar_marca(ruta, datos):
    I.escribir(ruta, json.dumps(datos))
    os.chmod(ruta, 0o600)


def configurar(slug, url, api_key, reiniciar):
    _pedir("POST", "/addons/%s/options" % slug,
           {"options": {"sistema_url": url, "api_key": api_key, "apertura": "marco"}})
    I.ok("Orion SysGestion configurado para %s" % url)
    _pedir("POST", "/addons/%s/%s" % (slug, "restart" if reiniciar else "start"), esperar=300)
    I.ok("Orion SysGestion %s (aparece en el menú lateral como SysGestion)" % ("reiniciado" if reiniciar else "iniciado"))


def instalar(slug):
    try:
        _pedir("POST", "/store/addons/%s/install" % slug, esperar=1800)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        _pedir("POST", "/addons/%s/install" % slug, esperar=1800)  # Supervisor viejo
    I.ok("Orion SysGestion instalado")


def paso(o):
    url = (o.get("sysgestion_url") or "").strip().rstrip("/")
    quiere_repo = o.get("sysgestion") is not False
    marca = leer_marca(MARCA_ADDON)

    # 1. Repositorio en la tienda, sin instalar (una sola vez por equipo).
    repo_slug = None
    if quiere_repo and not os.path.exists(MARCA_REPO):
        repo_slug = slug_repositorio(agregar=True)
        guardar_marca(MARCA_REPO, {"agregado": I.SELLO})
    if not url:
        return

    # 2. Activación para este cliente.
    if not url.startswith("https://"):
        I.aviso("sysgestion_url tiene que empezar con https:// (no se activó Orion SysGestion)")
        return
    api_key = api_key_gestion(o)
    if not api_key:
        I.aviso("Orion SysGestion: falta sysgestion_api_key (Orion AR → ficha de la instalación → Orion Gestión → Rotar API key)")
        return
    repo_slug = repo_slug or slug_repositorio(agregar=True)
    addon = buscar_addon(repo_slug)
    if not addon:
        raise RuntimeError("no encuentro Orion SysGestion en el repositorio %s" % repo_slug)
    slug = addon["slug"]
    huella = {"url": url, "key_fin": api_key[-4:]}

    if not addon.get("installed"):
        if marca and marca.get("slug") == slug:
            I.info("Orion SysGestion fue desinstalado en este equipo: no se vuelve a instalar")
            return
        instalar(slug)
        configurar(slug, url, api_key, reiniciar=False)
    elif not marca or {k: marca.get(k) for k in huella} != huella:
        configurar(slug, url, api_key, reiniciar=True)
    else:
        return  # ya instalado y con la misma configuración
    guardar_marca(MARCA_ADDON, dict(huella, slug=slug, instalado=I.SELLO))


def main():
    if not I.TOKEN:
        return
    try:
        o = I.opciones()
    except Exception:  # noqa: BLE001
        o = {}
    if o.get("sysgestion") is False and not (o.get("sysgestion_url") or "").strip():
        return
    if os.path.exists(MARCA_REPO) and not (o.get("sysgestion_url") or "").strip():
        return  # nada nuevo que hacer: no se consulta la tienda
    I.titulo("Orion SysGestion (sistema de gestión)")
    for intento in range(3):
        try:
            paso(o)
            return
        except Exception as e:  # noqa: BLE001
            I.aviso("Orion SysGestion: intento %d sin éxito: %s" % (intento + 1, e))
            time.sleep(60 * (intento + 1))
    I.aviso("Orion SysGestion no quedó listo; se reintenta en el próximo inicio del add-on.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("  [!]  Orion SysGestion: %s" % e, flush=True)
        sys.exit(0)
