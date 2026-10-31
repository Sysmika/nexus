#!/usr/bin/env python3
"""Nexus by Orion · acceso remoto (Tailscale).

Si el instalador dejó /data/nexus_remoto.json (el paquete de Orion pidió acceso Tailscale), este
módulo levanta tailscaled, le pide a Orion una clave de un solo uso (tag:ha) y conecta el equipo a
la tailnet. Después avisa a Orion para que anote el nodo y se queda corriendo mientras el add-on
esté encendido. El estado de Tailscale vive en /data/tailscale: sobrevive a reinicios y a
actualizaciones del add-on, y la clave nunca se guarda ni se escribe en el registro.

Modo "userspace networking": no crea interfaz de red ni necesita permisos privilegiados. Con
host_network, quien entra por la IP de Tailscale llega al Home Assistant (puerto 8123) del equipo.
"""
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

DATOS = os.environ.get("NEXUS_DATA", "/data")
REMOTO = os.path.join(DATOS, "nexus_remoto.json")
ESTADO_TS = os.path.join(DATOS, "tailscale")
SOCKET = os.environ.get("NEXUS_TS_SOCKET", "/var/run/tailscale/tailscaled.sock")
LOG_TS = os.path.join(DATOS, "tailscaled.log")
CLAVE_TMP = "/run/nexus_ts_key"
ESPERA_MAX = 600  # entre reintentos: de 30 s a 10 min


def info(m):
    print("  " + m, flush=True)


def ok(m):
    print("  [ok] " + m, flush=True)


def aviso(m):
    print("  [!]  " + m, flush=True)


def ts(*args, timeout=30):
    """Corre `tailscale ...` contra nuestro tailscaled. Devuelve (código, salida)."""
    try:
        p = subprocess.run(["tailscale", "--socket=" + SOCKET] + list(args),
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as e:
        return 1, str(e)


def estado_backend():
    c, out = ts("status", "--json", timeout=15)
    try:
        return json.loads(out).get("BackendState")
    except Exception:
        return None


def llamar_orion(cfg, ruta):
    """POST autenticado con la API key de la instalación. Devuelve el JSON o None."""
    url = cfg["servidor"].rstrip("/") + "/api/tickets/ha/" + ruta
    req = urllib.request.Request(
        url, data=b"{}", method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": cfg["api_key"], "User-Agent": "nexus-addon/1.2"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        aviso("Orion respondió HTTP %s en %s" % (e.code, ruta))
    except Exception as e:
        aviso("No pude hablar con Orion (%s): %s" % (ruta, e))
    return None


def avisar_a_orion(cfg):
    """Le dice a Orion que el nodo está conectado (para que anote su IP). Reintenta unos segundos."""
    for _ in range(6):
        r = llamar_orion(cfg, "tailscale_listo.php")
        if r and r.get("ok") and r.get("conectado"):
            ok("Orion anotó el nodo (IP %s)" % r.get("ip", "?"))
            return True
        if r and not r.get("ok"):
            aviso("Orion no aceptó el aviso: %s" % r.get("error", r))
            return False
        time.sleep(10)
    aviso("Orion todavía no ve el nodo en la tailnet; se vuelve a intentar al próximo arranque.")
    return False


def conectar(cfg):
    """Pide una clave a Orion y conecta a la tailnet. True si quedó conectado."""
    r = llamar_orion(cfg, "tailscale_clave.php")
    if not r:
        return False
    if not r.get("ok"):
        if r.get("error") == "ya_conectado":
            aviso("Orion ya tiene registrado un nodo para esta instalación y este equipo no conserva su sesión "
                  "(reinstalación). En Orion, volvé a generar el paquete de la instalación para habilitar una clave nueva.")
        else:
            aviso("Orion no entregó la clave: %s" % (r.get("mensaje") or r.get("error")))
        return False
    host = r.get("hostname") or cfg.get("hostname") or "nexus"
    fd = os.open(CLAVE_TMP, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(r["authkey"])
    try:
        c, out = ts("up", "--reset", "--auth-key=file:" + CLAVE_TMP, "--hostname=" + host,
                    "--advertise-tags=" + ",".join(r.get("tags") or ["tag:ha"]),
                    "--accept-dns=false", "--timeout=90s", timeout=120)
    finally:
        try:
            os.remove(CLAVE_TMP)
        except OSError:
            pass
    if c != 0:
        aviso("tailscale up falló: " + out.strip().replace(r["authkey"], "***")[-300:])
        return False
    ok("Conectado a la tailnet como '%s'" % host)
    return True


def main():
    print("\nNexus by Orion · acceso remoto", flush=True)
    if not os.path.exists(REMOTO):
        info("Sin acceso remoto configurado. Fin.")
        return 0
    with open(REMOTO, encoding="utf-8") as f:
        cfg = json.load(f)
    if not cfg.get("servidor") or not cfg.get("api_key"):
        aviso("nexus_remoto.json incompleto (falta servidor o api_key).")
        return 1

    os.makedirs(ESTADO_TS, exist_ok=True)
    os.makedirs(os.path.dirname(SOCKET), exist_ok=True)
    logf = open(LOG_TS, "a")
    proc = subprocess.Popen(
        ["tailscaled", "--tun=userspace-networking", "--state=" + os.path.join(ESTADO_TS, "tailscaled.state"),
         "--socket=" + SOCKET],
        stdout=logf, stderr=subprocess.STDOUT,
    )

    def parar(*_):
        proc.terminate()
        try:
            proc.wait(15)
        except Exception:
            proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, parar)
    signal.signal(signal.SIGINT, parar)

    for _ in range(30):  # espera a que tailscaled responda
        if proc.poll() is not None:
            aviso("tailscaled se cerró al arrancar (ver %s)." % LOG_TS)
            return 1
        if estado_backend() is not None:
            break
        time.sleep(1)

    espera = 30
    avisado = False
    while proc.poll() is None:
        estado = estado_backend()
        if estado == "Running":
            if not avisado:
                ok("Tailscale conectado")
                avisar_a_orion(cfg)
                avisado = True  # si Orion no llegó a verlo, se reintenta en el próximo arranque
            espera = 300
        elif estado in ("NeedsLogin", "Stopped"):
            info("Tailscale sin sesión: pidiendo clave a Orion...")
            if conectar(cfg):
                avisado = False  # el próximo ciclo avisa a Orion
                espera = 5
            else:
                espera = min(espera * 2, ESPERA_MAX)
        else:
            espera = 10  # Starting / NoState / sin respuesta todavía
        time.sleep(espera)

    aviso("tailscaled terminó (código %s)." % proc.returncode)
    return 1


if __name__ == "__main__":
    sys.exit(main())
