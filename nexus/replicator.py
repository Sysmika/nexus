#!/usr/bin/env python3
"""Nexus by Orion · Replicator (stock y compras de la casa).

Agrega el repositorio de Replicator a la tienda de add-ons, lo instala y lo inicia, una sola vez por equipo.
Corre aparte (en segundo plano) al iniciar el add-on, porque la primera instalación construye la imagen en el
equipo y puede llevar varios minutos: así no demora el acceso remoto.
  · Lo hace en equipos nuevos y también en los que ya estaban instalados (llega con la actualización del add-on).
  · Si el cliente desinstala Replicator después, no se vuelve a instalar (queda anotado en /data).
  · No carga ninguna clave de IA: la IA se da solo si el cliente la pide, y la clave se carga en el panel de
    Replicator.
  · Se desactiva con la opción `replicator: false`.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import instalar as I

REPO = os.environ.get("NEXUS_REPLICATOR_REPO", "https://github.com/Sysmika/replicator")
SLUG_BASE = "replicator"  # slug del add-on dentro de su repositorio
MARCA = os.path.join(os.path.dirname(I.OPTIONS), "nexus_replicator.json")  # /data, privado del add-on


def _pedir(metodo, ruta, cuerpo=None, esperar=60):
    datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else (b"" if metodo == "POST" else None)
    req = urllib.request.Request(
        I.SUPERVISOR + ruta, data=datos, method=metodo,
        headers={"Authorization": "Bearer " + I.TOKEN, "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=esperar) as r:
        return json.loads(r.read().decode("utf-8") or "{}").get("data") or {}


def _mismo_repo(a, b):
    n = lambda u: (u or "").strip().lower().rstrip("/").removesuffix(".git")  # noqa: E731
    return n(a) == n(b)


def asegurar_repositorio():
    """Agrega el repositorio de Replicator a la tienda si no está. Devuelve su slug (ej. 91648bc2)."""
    repos = _pedir("GET", "/store/repositories")
    for r in repos if isinstance(repos, list) else []:
        if _mismo_repo(r.get("source") or r.get("url"), REPO):
            return r.get("slug", "")
    _pedir("POST", "/store/repositories", {"repository": REPO}, esperar=180)
    I.ok("Repositorio de Replicator agregado a la tienda")
    for r in _pedir("GET", "/store/repositories") or []:
        if _mismo_repo(r.get("source") or r.get("url"), REPO):
            return r.get("slug", "")
    raise RuntimeError("la tienda no muestra el repositorio después de agregarlo")


def buscar_addon(repo_slug):
    for a in (_pedir("GET", "/store/addons").get("addons") or []):
        if a.get("repository") == repo_slug and a.get("slug", "").endswith("_" + SLUG_BASE):
            return a
    return None


def instalar_y_arrancar(slug):
    try:
        _pedir("POST", "/store/addons/%s/install" % slug, esperar=1800)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        _pedir("POST", "/addons/%s/install" % slug, esperar=1800)  # Supervisor viejo
    I.ok("Replicator instalado")
    _pedir("POST", "/addons/%s/start" % slug, esperar=300)
    I.ok("Replicator iniciado (aparece en el menú lateral)")


def main():
    if not I.TOKEN:
        return
    try:
        o = I.opciones()
    except Exception:  # noqa: BLE001
        o = {}
    if o.get("replicator") is False or os.path.exists(MARCA):
        return
    I.titulo("Replicator (stock y compras)")
    for intento in range(3):
        try:
            repo_slug = asegurar_repositorio()
            addon = buscar_addon(repo_slug)
            if not addon:
                raise RuntimeError("no encuentro el add-on Replicator en el repositorio %s" % repo_slug)
            slug = addon["slug"]
            if addon.get("installed"):
                I.info("Replicator ya estaba instalado")
            else:
                instalar_y_arrancar(slug)
            I.escribir(MARCA, json.dumps({"instalado": I.SELLO, "slug": slug}))
            return
        except Exception as e:  # noqa: BLE001
            I.aviso("Replicator: intento %d sin éxito: %s" % (intento + 1, e))
            time.sleep(60 * (intento + 1))
    I.aviso("Replicator no se instaló; se reintenta en el próximo inicio del add-on.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # noqa: BLE001
        print("  [!]  Replicator: %s" % e, flush=True)
        sys.exit(0)
