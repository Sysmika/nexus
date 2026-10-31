#!/usr/bin/env python3
"""Nexus by Orion · instalador (add-on de Home Assistant).

Hace lo mismo que instalar-nexus.ps1, pero corriendo dentro del HA:
copia la marca/tema/tarjetas, genera el paquete de Soporte con los datos del cliente,
parchea configuration.yaml solo en lo que falta y (si hay supervisor) verifica y reinicia.
Se puede correr varias veces: no duplica nada.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import asyncio

CONFIG = os.environ.get("NEXUS_CONFIG", "/config")
PAYLOAD = os.environ.get("NEXUS_PAYLOAD", "/payload")
OPTIONS = os.environ.get("NEXUS_OPTIONS", "/data/options.json")
SUPERVISOR = os.environ.get("NEXUS_SUPERVISOR", "http://supervisor")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
AUTO = os.path.join(CONFIG, "nexus_instalar.json")
ESTADO = os.path.join(CONFIG, ".nexus_estado.json")
REMOTO = os.path.join(os.path.dirname(OPTIONS), "nexus_remoto.json")  # /data, privado del add-on
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
def version_addon():
    """Versión de este add-on según el supervisor (para que Orion la anote en la instalación)."""
    if not TOKEN:
        return ""
    try:
        req = urllib.request.Request(SUPERVISOR + "/addons/self/info", headers={"Authorization": "Bearer " + TOKEN})
        with urllib.request.urlopen(req, timeout=10) as r:
            return str(json.loads(r.read().decode("utf-8")).get("data", {}).get("version", ""))
    except Exception:
        return ""


def pedir_a_orion(o, webhook_id):
    """Canjea el código de instalación por los datos del cliente y registra el webhook."""
    # El código de instalación son 12 letras/números (XXXX-XXXX-XXXX). Se valida antes de enviar
    # nada: así, si alguien pega otra cosa (por ejemplo una API key), no sale de este equipo.
    if len(re.sub(r"[^A-Za-z0-9]", "", o["codigo"])) != 12:
        fallo("Lo que hay en 'codigo' no es un código de instalación (formato XXXX-XXXX-XXXX, 12 letras y números). "
              "No se envió nada a Orion. Borrá ese campo y pegá el código que genera la llave del panel de Orion; "
              "no pegues acá claves ni contraseñas.")
    url = o["servidor"].rstrip("/") + "/api/tickets/ha/instalar.php"
    cuerpo = {"codigo": o["codigo"].strip(), "webhook_id": webhook_id, "version": version_addon()}
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



# ---------------------------------------------------------------- accesos (etiqueta y usuarios)
def esperar_core(maximo=420, pausa=40):
    """Espera a que el core de HA vuelva a responder por la API del supervisor."""
    time.sleep(pausa)  # deja pasar la caída por el reinicio
    t0 = time.time()
    while time.time() - t0 < maximo:
        try:
            req = urllib.request.Request(SUPERVISOR + "/core/api/config", headers={"Authorization": "Bearer " + TOKEN})
            with urllib.request.urlopen(req, timeout=10) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(5)
    return False


def ws_correr(comandos):
    """Manda comandos al websocket de HA (token del supervisor). Cada item: callable(resultados)->dict|None."""
    import websockets

    async def _run():
        async with websockets.connect("ws://supervisor/core/websocket", max_size=None) as ws:
            await ws.recv()  # auth_required
            await ws.send(json.dumps({"type": "auth", "access_token": TOKEN}))
            if json.loads(await ws.recv()).get("type") != "auth_ok":
                raise RuntimeError("el websocket de HA rechazó el token del supervisor")
            n = [0]

            async def cmd(c):
                n[0] += 1
                await ws.send(json.dumps(dict(c, id=n[0])))
                while True:
                    r = json.loads(await ws.recv())
                    if r.get("id") == n[0]:
                        return r
            await comandos(cmd)
    asyncio.run(_run())


def crear_accesos(datos, pausa=40):
    """Etiqueta 'Orion Vigilar' y usuarios (administrador y cliente sin permisos de admin)."""
    titulo("7. Etiqueta y usuarios")
    if not TOKEN:
        info("Sin supervisor: omitido.")
        return
    if not esperar_core(pausa=pausa):
        aviso("HA no volvió a responder a tiempo: etiqueta y usuarios sin crear.")
        return

    async def hacer(cmd):
        r = await cmd({"type": "config/label_registry/list"})
        if any(x.get("label_id") == "orion_vigilar" for x in r.get("result", [])):
            info("Etiqueta 'Orion Vigilar' ya existía")
        else:
            r = await cmd({"type": "config/label_registry/create", "name": "Orion Vigilar"})
            ok("Etiqueta 'Orion Vigilar'") if r.get("success") else aviso("No pude crear la etiqueta: %s" % r.get("error"))
        quieren = []
        if datos.get("admin"):
            quieren.append((datos["admin"], ["system-admin"], "admin"))
        if datos.get("cliente"):
            quieren.append((datos["cliente"], ["system-users"], "cliente"))
        if not quieren:
            return
        usuarios = (await cmd({"type": "config/auth/list"})).get("result", [])
        for u, grupos, rol in quieren:
            nombre_u, clave = (u.get("usuario") or "").strip(), u.get("clave") or ""
            if not nombre_u or len(clave) < 8:
                aviso("Usuario %s: falta usuario o la clave es corta (mín. 8): omitido." % rol)
                continue
            ya = next((x for x in usuarios if nombre_u in [c.get("username") for c in x.get("credentials", [])] or x.get("username") == nombre_u), None)
            if ya and ya.get("is_owner"):
                aviso("'%s' es el propietario de este HA: HA solo le deja cambiar la clave a él mismo. Usá otro nombre para el administrador." % nombre_u)
                continue
            if ya:
                r = await cmd({"type": "config/auth_provider/homeassistant/admin_change_password", "user_id": ya["id"], "password": clave})
                ok("Usuario '%s' (%s): clave cambiada" % (nombre_u, rol)) if r.get("success") else aviso("No pude cambiar la clave de '%s': %s" % (nombre_u, r.get("error")))
                continue
            r = await cmd({"type": "config/auth/create", "name": u.get("nombre") or nombre_u, "group_ids": grupos})
            if not r.get("success"):
                aviso("No pude crear el usuario '%s': %s" % (nombre_u, r.get("error")))
                continue
            uid = r["result"]["user"]["id"]
            r = await cmd({"type": "config/auth_provider/homeassistant/create", "user_id": uid, "username": nombre_u, "password": clave})
            ok("Usuario '%s' (%s) creado" % (nombre_u, rol)) if r.get("success") else aviso("No pude ponerle clave a '%s': %s" % (nombre_u, r.get("error")))
    try:
        ws_correr(hacer)
    except Exception as e:
        aviso("Etiqueta y usuarios sin crear: %s" % e)

# ---------------------------------------------------------------- login con marca Nexus
def asegurar_login():
    """Instala (o repara) el componente que agrega el logo de Nexus a la pantalla de login y su línea
    `nexus_login:` en configuration.yaml. Idempotente. No reinicia HA: se activa en el próximo reinicio.
    Devuelve True si cambió algo."""
    origen = os.path.join(PAYLOAD, "custom_components", "nexus_login")
    cfg = os.path.join(CONFIG, "configuration.yaml")
    if not os.path.isdir(origen) or not os.path.exists(cfg):
        return False
    cambio = False
    destino = os.path.join(CONFIG, "custom_components", "nexus_login")
    nuevos = {n: leer(os.path.join(origen, n)) for n in os.listdir(origen) if os.path.isfile(os.path.join(origen, n))}
    for n, texto in nuevos.items():
        ruta = os.path.join(destino, n)
        if not os.path.exists(ruta) or leer(ruta) != texto:
            escribir(ruta, texto)
            cambio = True
    texto_cfg = leer(cfg)
    if not re.search(r"(?m)^nexus_login:", texto_cfg):
        copia = cfg + ".bak-nexus-" + SELLO
        if not os.path.exists(copia):
            shutil.copy2(cfg, copia)
        escribir(cfg, texto_cfg.rstrip("\n") + "\n\n# Marca Nexus en la pantalla de login (custom_components/nexus_login)\nnexus_login:\n")
        cambio = True
    return cambio


# ---------------------------------------------------------------- tema Nexus (pantallas internas)
TEMA_APLICADO = os.path.join(os.path.dirname(OPTIONS), "nexus_tema_aplicado")  # /data, privado del add-on


def _copiar_si_cambia(origen, destino):
    """Copia el archivo solo si no existe o difiere (bytes). Devuelve True si copió."""
    with open(origen, "rb") as f:
        nuevo = f.read()
    if os.path.exists(destino):
        with open(destino, "rb") as f:
            if f.read() == nuevo:
                return False
    os.makedirs(os.path.dirname(destino), exist_ok=True)
    with open(destino, "wb") as f:
        f.write(nuevo)
    return True


def asegurar_marca():
    """Mantiene al día la marca visual: logo y recursos de www/nexus, tema "Nexus" (azul marino con el logo
    como marca de agua) y la versión del script de marca en configuration.yaml (para saltear la caché).
    No toca el dashboard del cliente. Idempotente. Devuelve True si cambió algo."""
    cambio = False
    for src in ("www/nexus", "themes/nexus"):
        raiz = os.path.join(PAYLOAD, src)
        if not os.path.isdir(raiz):
            continue
        for carpeta, _, archivos in os.walk(raiz):
            for n in archivos:
                origen = os.path.join(carpeta, n)
                rel = os.path.relpath(origen, os.path.join(PAYLOAD, os.path.dirname(src)))
                if _copiar_si_cambia(origen, os.path.join(CONFIG, os.path.dirname(src), rel)):
                    cambio = True
    cfg = os.path.join(CONFIG, "configuration.yaml")
    js = os.path.join(PAYLOAD, "www/nexus/nexus-branding.js")
    if cambio and os.path.exists(cfg) and os.path.exists(js):
        with open(js, "rb") as f:
            ver = hashlib.sha1(f.read()).hexdigest()[:8]
        texto = leer(cfg)
        nuevo = re.sub(r"(nexus-branding\.js\?v=)[0-9A-Za-z]+", r"\g<1>" + ver, texto)
        if nuevo != texto:
            copia = cfg + ".bak-nexus-" + SELLO
            if not os.path.exists(copia):
                shutil.copy2(cfg, copia)
            escribir(cfg, nuevo)
    return cambio


def tema_por_defecto():
    """Deja "Nexus" como tema por defecto de Home Assistant, una sola vez (después cada usuario puede elegir
    otro en su perfil). Necesita que el core esté arriba; si falla, reintenta en el próximo inicio."""
    if os.path.exists(TEMA_APLICADO) or not TOKEN:
        return False
    if not os.path.exists(os.path.join(CONFIG, "themes", "nexus", "nexus.yaml")):
        return False
    base = SUPERVISOR + "/core/api/services/frontend/"
    for servicio, cuerpo in (("reload_themes", {}), ("set_theme", {"name": "Nexus"})):
        req = urllib.request.Request(
            base + servicio, data=json.dumps(cuerpo).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + TOKEN, "Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=30).read()
    escribir(TEMA_APLICADO, "ok\n")
    return True


# ---------------------------------------------------------------- token de Home Assistant para Orion
def _http_json(url, cuerpo, formulario=False, timeout=20, crudo=False):
    if formulario:
        datos, tipo = urllib.parse.urlencode(cuerpo).encode("utf-8"), "application/x-www-form-urlencoded"
    else:
        datos, tipo = json.dumps(cuerpo).encode("utf-8"), "application/json"
    req = urllib.request.Request(url, data=datos, method="POST", headers={"Content-Type": tipo})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        texto = r.read().decode("utf-8")
    return texto if crudo else json.loads(texto or "{}")


def token_largo(usuario, clave, nombre="Orion (automático)", dias=3650, base=None):
    """Crea un token de acceso de larga duración para `usuario` iniciando sesión como él (el usuario del
    Supervisor es de sistema y HA no le permite crear tokens de larga duración)."""
    base = (base or os.environ.get("NEXUS_HA_URL", "http://127.0.0.1:8123")).rstrip("/")
    cid = base + "/"
    flujo = _http_json(base + "/auth/login_flow", {"client_id": cid, "handler": ["homeassistant", None],
                                                    "redirect_uri": cid + "?auth_callback=1"})
    paso = _http_json(base + "/auth/login_flow/" + flujo["flow_id"],
                      {"username": usuario, "password": clave, "client_id": cid})
    if paso.get("type") != "create_entry":
        raise RuntimeError("Home Assistant no aceptó el inicio de sesión de '%s'" % usuario)
    tok = _http_json(base + "/auth/token", {"grant_type": "authorization_code", "code": paso["result"],
                                             "client_id": cid}, formulario=True)
    acceso, refresco = tok["access_token"], tok.get("refresh_token")
    try:
        import websockets

        async def _ws():
            async with websockets.connect(base.replace("http", "ws", 1) + "/api/websocket", max_size=None) as ws:
                await ws.recv()  # auth_required
                await ws.send(json.dumps({"type": "auth", "access_token": acceso}))
                if json.loads(await ws.recv()).get("type") != "auth_ok":
                    raise RuntimeError("el websocket de HA rechazó el token")
                await ws.send(json.dumps({"id": 1, "type": "auth/long_lived_access_token",
                                          "client_name": nombre, "lifespan": dias}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == 1:
                        if not m.get("success"):
                            raise RuntimeError("HA no creó el token: %s" % (m.get("error") or {}).get("message", "?"))
                        return m["result"]
        return asyncio.run(_ws())
    finally:
        if refresco:  # la sesión temporal con la que se pidió el token no debe quedar abierta
            try:
                _http_json(base + "/auth/revoke", {"token": refresco, "action": "revoke"}, formulario=True, crudo=True)
            except Exception:  # noqa: BLE001
                pass


def entregar_token_a_orion(datos, servidor, api_key):
    """Crea un token de larga duración del usuario administrador y se lo entrega a Orion (que lo guarda en
    la ficha de la instalación) para que pueda consultar este Home Assistant sin cargar el token a mano."""
    titulo("8. Token de Home Assistant para Orion")
    adm = (datos or {}).get("admin") or {}
    if not (adm.get("usuario") and adm.get("clave") and servidor and api_key):
        info("El paquete no trae usuario administrador: no se crea el token.")
        return
    try:
        token = token_largo(adm["usuario"], adm["clave"])
    except Exception as e:  # noqa: BLE001
        aviso("No pude crear el token para Orion: %s" % e)
        return
    req = urllib.request.Request(
        servidor.rstrip("/") + "/api/tickets/ha/ha_token.php",
        data=json.dumps({"token": token}).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json", "X-API-Key": api_key, "User-Agent": "nexus-addon/1.3"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            resp = json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        aviso("Orion no aceptó el token (HTTP %s)." % e.code)
        return
    except Exception as e:  # noqa: BLE001
        aviso("No pude entregar el token a Orion: %s" % e)
        return
    if resp.get("ok"):
        ok("Token de larga duración de '%s' entregado a Orion" % adm["usuario"])
    else:
        aviso("Orion no guardó el token: %s" % resp.get("error", resp))


# ---------------------------------------------------------------- principal
def main():
    titulo("Nexus by Orion · instalador (add-on)")
    o = opciones()
    datos = {}
    if not (o.get("codigo") or "").strip() and os.path.exists(AUTO):
        with open(AUTO, encoding="utf-8") as f:
            datos = json.load(f)
        o["codigo"] = datos.get("codigo", "")
        o["url_publica"] = datos.get("url_publica", o.get("url_publica", ""))
        info("Modo automático: datos tomados de nexus_instalar.json")
    if not (o.get("codigo") or "").strip() and os.path.exists(AUTO) and os.path.exists(ESTADO) and not datos.get("codigo"):
        info("Ya instalado: solo se crean etiqueta y usuarios")
        crear_accesos(datos, pausa=0)
        os.remove(AUTO)
        ok("nexus_instalar.json borrado")
        return
    if not (o.get("codigo") or "").strip() and not (o.get("api_key") or "").strip():
        info("Nada para instalar (sin código ni nexus_instalar.json).")
        # Equipos ya instalados: el login con marca Nexus llega con las actualizaciones del add-on.
        # Idempotente y silencioso; no reinicia HA (surte efecto en el próximo reinicio).
        try:
            if asegurar_login():
                ok("Marca Nexus en la pantalla de login instalada (se activa en el próximo reinicio de Home Assistant)")
        except Exception as e:  # noqa: BLE001
            aviso("No pude instalar la marca del login: %s" % e)
        try:
            if asegurar_marca():
                ok("Logo y tema Nexus actualizados (se activan en el próximo reinicio de Home Assistant)")
        except Exception as e:  # noqa: BLE001
            aviso("No pude actualizar el tema Nexus: %s" % e)
        try:
            if tema_por_defecto():
                ok("Tema Nexus puesto por defecto")
        except Exception as e:  # noqa: BLE001
            info("Tema por defecto pendiente (se reintenta en el próximo inicio): %s" % e)
        return

    titulo("1. Datos de la instalación")
    webhook_id = (o.get("webhook_id") or "").strip()
    if (o.get("codigo") or "").strip():
        if not webhook_id:
            webhook_id = "orion_respuesta_" + secrets.token_hex(16)
        cliente_id, api_key, nombre = pedir_a_orion(o, webhook_id)
        ok("Código canjeado en Orion%s" % ((" (" + nombre + ")") if nombre else ""))
        ts_cfg = datos.get("tailscale") or {}
        if ts_cfg.get("activo"):
            # remoto.py (corre después de este script) pide a Orion la clave de Tailscale con esta API key
            escribir(REMOTO, json.dumps({"servidor": o["servidor"].rstrip("/"), "api_key": api_key,
                                         "hostname": ts_cfg.get("hostname", "")}))
            os.chmod(REMOTO, 0o600)
            ok("Acceso remoto (Tailscale) programado")
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
    for src, dst in (("www/nexus", "www/nexus"), ("www/community", "www/community"), ("themes/ios_glass", "themes/ios_glass"), ("themes/nexus", "themes/nexus")):
        shutil.copytree(os.path.join(PAYLOAD, src), os.path.join(CONFIG, dst), dirs_exist_ok=True)
    ok("Marca Nexus, tarjetas (card-mod, button-card) y temas")
    try:
        if tema_por_defecto():
            ok("Tema Nexus puesto por defecto")
    except Exception as e:  # noqa: BLE001
        info("Tema por defecto pendiente (se reintenta en el próximo inicio): %s" % e)
    if asegurar_login():
        ok("Marca Nexus en la pantalla de login (se activa al reiniciar Home Assistant)")
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
    m = re.search(r"(?m)^orion_tickets_api_key:[ \t]*(.*)$", texto)
    if m and m.group(1).strip().strip("\"'") == api_key:
        info("orion_tickets_api_key ya estaba (igual)")
    elif m:
        texto = texto[:m.start()] + "orion_tickets_api_key: %s" % api_key + texto[m.end():]
        escribir(sec, texto)
        ok("orion_tickets_api_key actualizada")
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

    if TOKEN and o.get("reiniciar", True):
        crear_accesos(datos)
        entregar_token_a_orion(datos, o.get("servidor", ""), api_key)
    if datos and os.path.exists(AUTO):
        os.remove(AUTO)  # tenía el código y las claves: no debe quedar en /config
        ok("nexus_instalar.json borrado")
    escribir(ESTADO, json.dumps({"instalado": SELLO, "cliente_id": cliente_id}))

    titulo("Listo")
    if AVISOS:
        print("  Revisá estos avisos:")
        for a in AVISOS:
            print("   - " + a)
    print(
        "\n  Próximos pasos (en el Home Assistant):\n"
        "   1. Asignar la etiqueta 'Orion Vigilar' a los dispositivos que deben abrir un ticket si caen 24 hs.\n"
        "      (Con nexus_instalar.json la etiqueta y los usuarios se crean solos; si no, hay que crearlos a mano.)\n"
        "   2. Abrir el dashboard Nexus > Soporte y mandar una consulta de prueba.\n"
        "   3. Si el HA se publica detrás de un túnel o proxy: Ajustes > Sistema > Red > Servidor HTTP >\n"
        "      'Confiar en X-Forwarded-For' y agregar el proxy de confianza (add-on Cloudflared: 172.30.33.0/24)."
    )


if __name__ == "__main__":
    main()
