#!/usr/bin/env python3
"""Nexus by Orion · instalador (add-on de Home Assistant).

Hace lo mismo que instalar-nexus.ps1, pero corriendo dentro del HA:
copia la marca/tema/tarjetas, genera el paquete de Soporte con los datos del cliente,
parchea configuration.yaml solo en lo que falta y (si hay supervisor) verifica y reinicia.
Se puede correr varias veces: no duplica nada.
"""
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.request

CONFIG = os.environ.get("NEXUS_CONFIG", "/config")
PAYLOAD = os.environ.get("NEXUS_PAYLOAD", "/payload")
OPTIONS = os.environ.get("NEXUS_OPTIONS", "/data/options.json")
SUPERVISOR = os.environ.get("NEXUS_SUPERVISOR", "http://supervisor")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
SELLO = time.strftime("%Y%m%d-%H%M%S")
AVISOS = []


def info(m):
    print("  " + m, flush=True)


def ok(m):
    print("  [ok] " + m, flush=True)


def aviso(m):
    print("  [!]  " + m, flush=True)
    AVISOS.append(m)


def titulo(m):
    print("\n" + m, flush=True)


def fallo(m):
    print("\n  [ERROR] " + m, flush=True)
    sys.exit(1)


def leer(ruta):
    with open(ruta, encoding="utf-8", newline="") as f:
        return f.read().replace("\r\n", "\n")


def escribir(ruta, texto):
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)


def opciones():
    with open(OPTIONS, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- Orion
def pedir_a_orion(o, webhook_id):
    """Canjea el código de instalación por los datos del cliente y registra el webhook."""
    # El código de instalación son 12 letras/números (XXXX-XXXX-XXXX). Se valida antes de enviar
    # nada: así, si alguien pega otra cosa (por ejemplo una API key), no sale de este equipo.
    if len(re.sub(r"[^A-Za-z0-9]", "", o["codigo"])) != 12:
        fallo("Lo que hay en 'codigo' no es un código de instalación (formato XXXX-XXXX-XXXX, 12 letras y números). "
              "No se envió nada a Orion. Borrá ese campo y pegá el código que genera la llave del panel de Orion; "
              "no pegues acá claves ni contraseñas.")
    url = o["servidor"].rstrip("/") + "/api/tickets/ha/instalar.php"
    cuerpo = {"codigo": o["codigo"].strip(), "webhook_id": webhook_id}
    if o.get("url_publica"):
        cuerpo["url_publica"] = o["url_publica"].strip().rstrip("/")
    req = urllib.request.Request(
        url,
        data=json.dumps(cuerpo).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "nexus-addon/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # El servidor de Orion reemplaza los errores 4xx por una página HTML: si no hay JSON,
        # se traduce el código HTTP.
        try:
            det = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:
            det = {
                400: "los datos enviados no son válidos (revisá el código y la url_publica)",
                403: "código inválido, vencido o ya utilizado (generá uno nuevo en Orion)",
                405: "la dirección del servidor no es la de Orion",
                404: "no se encontró el endpoint de instalación en el servidor",
            }.get(e.code, "")
        fallo("Orion rechazó el código (HTTP %s): %s" % (e.code, det))
    except Exception as e:
        fallo("No pude hablar con Orion (%s): %s" % (url, e))
    if not resp.get("ok"):
        fallo("Orion respondió con error: %s" % resp.get("error", resp))
    d = resp["data"]
    return int(d["cliente_id"]), d["api_key"], d.get("nombre", "")


# ---------------------------------------------------------------- configuration.yaml
def rango_bloque(lineas, clave):
    ini = None
    for i, l in enumerate(lineas):
        if re.match(r"^" + re.escape(clave) + r":(\s|$)", l):
            ini = i
            break
    if ini is None:
        return None
    fin = len(lineas)
    for j in range(ini + 1, len(lineas)):
        if re.match(r"^\S", lineas[j]) and not lineas[j].startswith("#"):
            fin = j
            break
    return ini, fin


def anexar(lineas, bloque):
    if lineas and lineas[-1].strip() != "":
        lineas.append("")
    lineas.extend(bloque)


def parchear_config(ruta):
    lineas = leer(ruta).split("\n")
    if lineas and lineas[-1] == "":
        lineas.pop()
    cambios = 0
    texto = "\n".join(lineas)

    # frontend: módulos JS
    modulos = []
    if "nexus-branding.js" not in texto:
        modulos.append("/local/nexus/nexus-branding.js?v=1")
    if "card-mod.js" not in texto:
        modulos.append("/local/community/lovelace-card-mod/card-mod.js")
    if modulos:
        r = rango_bloque(lineas, "frontend")
        if r is None:
            anexar(lineas, ["frontend:", "  extra_module_url:"] + ["    - " + m for m in modulos])
        else:
            pos = next((i for i in range(r[0] + 1, r[1]) if re.match(r"^\s+extra_module_url:", lineas[i])), None)
            if pos is not None:
                for k, m in enumerate(modulos):
                    lineas.insert(pos + 1 + k, "    - " + m)
            else:
                lineas.insert(r[0] + 1, "  extra_module_url:")
                for k, m in enumerate(modulos):
                    lineas.insert(r[0] + 2 + k, "    - " + m)
        ok("frontend: módulos de Nexus")
        cambios += 1
    else:
        info("frontend: ya estaba")

    # homeassistant: packages
    r = rango_bloque(lineas, "homeassistant")
    if r is None:
        anexar(lineas, ["homeassistant:", "  packages: !include_dir_named packages"])
        ok("homeassistant: packages")
        cambios += 1
    else:
        tiene = [l for l in lineas[r[0] + 1:r[1]] if re.match(r"^\s+packages:", l)]
        if not tiene:
            lineas.insert(r[0] + 1, "  packages: !include_dir_named packages")
            ok("homeassistant: packages")
            cambios += 1
        elif any("include_dir_named" in l and "packages" in l for l in tiene):
            info("homeassistant: packages ya estaba")
        else:
            aviso("homeassistant ya define 'packages' de otra forma. Integrá a mano: packages: !include_dir_named packages")

    # http: ya no va en YAML (desde HA 2026.8)
    if rango_bloque(lineas, "http") is not None:
        aviso("configuration.yaml tiene un bloque 'http:' (HA lo ignora desde 2026.8). Confirmá los valores en Ajustes > Sistema > Red y borralo.")

    # lovelace: dashboard Nexus
    snippet = [
        "    dashboard-nexus:", "      mode: yaml", "      filename: dashboards/nexus.yaml",
        "      title: Nexus", "      icon: mdi:hub-outline", "      show_in_sidebar: true",
    ]
    r = rango_bloque(lineas, "lovelace")
    if r is None:
        anexar(lineas, ["lovelace:", "  dashboards:"] + snippet)
        ok("lovelace: dashboard Nexus")
        cambios += 1
    elif "dashboard-nexus:" in "\n".join(lineas[r[0]:r[1]]):
        info("lovelace: dashboard Nexus ya estaba")
    else:
        pos = next((i for i in range(r[0] + 1, r[1]) if re.match(r"^\s+dashboards:", lineas[i])), None)
        if pos is None:
            aviso("lovelace existe sin 'dashboards:'. Agregá el dashboard Nexus a mano.")
        else:
            for k, s in enumerate(snippet):
                lineas.insert(pos + 1 + k, s)
            ok("lovelace: dashboard Nexus agregado")
            cambios += 1

    if cambios:
        escribir(ruta, "\n".join(lineas) + "\n")
    return cambios


# ---------------------------------------------------------------- supervisor
def supervisor(ruta, esperar=60):
    req = urllib.request.Request(
        SUPERVISOR + ruta, data=b"", method="POST",
        headers={"Authorization": "Bearer " + TOKEN},
    )
    with urllib.request.urlopen(req, timeout=esperar) as r:
        return json.loads(r.read().decode("utf-8") or "{}")


# ---------------------------------------------------------------- principal
def main():
    titulo("Nexus by Orion · instalador (add-on)")
    o = opciones()

    titulo("1. Datos de la instalación")
    webhook_id = (o.get("webhook_id") or "").strip()
    if (o.get("codigo") or "").strip():
        if not webhook_id:
            webhook_id = "orion_respuesta_" + secrets.token_hex(16)
        cliente_id, api_key, nombre = pedir_a_orion(o, webhook_id)
        ok("Código canjeado en Orion%s" % ((" (" + nombre + ")") if nombre else ""))
        if not (o.get("url_publica") or "").strip():
            aviso("Sin url_publica: cargá la Webhook URL (…/api/webhook/%s) en Orion para recibir respuestas." % webhook_id)
    else:
        cliente_id = int(o.get("cliente_id") or 0)
        api_key = (o.get("api_key") or "").strip()
        if cliente_id <= 0 or not api_key or not webhook_id:
            fallo("Falta el código de instalación (o cliente_id, api_key y webhook_id para el modo manual).")
        ok("Datos tomados de la configuración del add-on")

    titulo("2. Copias de seguridad")
    for n in ("configuration.yaml", "secrets.yaml"):
        r = os.path.join(CONFIG, n)
        if os.path.exists(r):
            shutil.copy2(r, r + ".bak-nexus-" + SELLO)
            ok("%s.bak-nexus-%s" % (n, SELLO))
    if not os.path.exists(os.path.join(CONFIG, "configuration.yaml")):
        fallo("No encuentro configuration.yaml en %s" % CONFIG)

    titulo("3. Archivos")
    for src, dst in (("www/nexus", "www/nexus"), ("www/community", "www/community"), ("themes/ios_glass", "themes/ios_glass")):
        shutil.copytree(os.path.join(PAYLOAD, src), os.path.join(CONFIG, dst), dirs_exist_ok=True)
    ok("Marca Nexus, tarjetas (card-mod, button-card) y tema")
    paquete = leer(os.path.join(PAYLOAD, "config/packages/orion_soporte.yaml"))
    paquete = paquete.replace("CLIENTE_ID_AQUI", str(cliente_id)).replace("WEBHOOK_ID_AQUI", webhook_id)
    for ph in ("CLIENTE_ID_AQUI", "WEBHOOK_ID_AQUI", "API_KEY_AQUI"):
        if ph in paquete:
            fallo("El paquete tiene el dato '%s' sin completar." % ph)
    escribir(os.path.join(CONFIG, "packages/orion_soporte.yaml"), paquete)
    escribir(os.path.join(CONFIG, "dashboards/views/soporte.yaml"), leer(os.path.join(PAYLOAD, "config/dashboards/views/soporte.yaml")))
    ok("Paquete de Soporte y vista de Soporte")
    dash = os.path.join(CONFIG, "dashboards/nexus.yaml")
    if os.path.exists(dash):
        info("dashboards/nexus.yaml ya existe: se respeta")
    else:
        escribir(dash, leer(os.path.join(PAYLOAD, "config/dashboards/nexus.yaml")))
        ok("Dashboard Nexus")

    titulo("4. configuration.yaml")
    cambios = parchear_config(os.path.join(CONFIG, "configuration.yaml"))

    titulo("5. secrets.yaml")
    sec = os.path.join(CONFIG, "secrets.yaml")
    texto = leer(sec) if os.path.exists(sec) else ""
    if re.search(r"(?m)^orion_tickets_api_key:", texto):
        info("orion_tickets_api_key ya estaba (no se pisa)")
    else:
        if texto and not texto.endswith("\n"):
            texto += "\n"
        escribir(sec, texto + "orion_tickets_api_key: %s\n" % api_key)
        ok("orion_tickets_api_key agregada")

    titulo("6. Verificación y reinicio")
    if not TOKEN:
        info("Sin supervisor (modo local): verificá y reiniciá HA a mano.")
    else:
        try:
            res = supervisor("/core/check")
            if res.get("result") != "ok":
                aviso("La verificación de configuración devolvió: %s" % res)
                o["reiniciar"] = False
            else:
                ok("La configuración es válida")
        except Exception as e:
            aviso("No pude verificar la configuración: %s" % e)
            o["reiniciar"] = False
        if o.get("reiniciar", True):
            try:
                supervisor("/core/restart")
                ok("Home Assistant se está reiniciando")
            except Exception as e:
                aviso("No pude reiniciar HA: %s. Reinicialo a mano." % e)
        else:
            info("Reinicio omitido. Reiniciá HA a mano cuando quieras.")

    titulo("Listo")
    if AVISOS:
        print("  Revisá estos avisos:")
        for a in AVISOS:
            print("   - " + a)
    print(
        "\n  Próximos pasos (en el Home Assistant):\n"
        "   1. Ajustes > Áreas, etiquetas y zonas > Etiquetas: crear 'Orion vigilar' (id orion_vigilar)\n"
        "      y asignarla a los dispositivos que deben abrir un ticket si caen 24 hs.\n"
        "   2. Crear un usuario SIN permisos de administrador para el cliente.\n"
        "   3. Abrir el dashboard Nexus > Soporte y mandar una consulta de prueba.\n"
        "   4. Si el HA se publica detrás de un túnel o proxy: Ajustes > Sistema > Red > Servidor HTTP >\n"
        "      'Confiar en X-Forwarded-For' y agregar el proxy de confianza (add-on Cloudflared: 172.30.33.0/24)."
    )


if __name__ == "__main__":
    main()
