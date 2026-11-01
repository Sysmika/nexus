#!/usr/bin/env python3
"""Nexus by Orion · modo demo.

Solo hace algo si la opción `modo_demo` del add-on está activa (equipos de demostración para clientes, no los
instalados en clientes reales). Deja el Home Assistant "completo" sin ningún dispositivo real:
  · entidades ficticias por rubro (packages/demo_<rubro>.yaml: sensores que varían con la hora, luces, persianas,
    aire acondicionado, alarma...) y un dashboard por rubro (dashboards/<rubro>.yaml)
  · usuarios de demostración sin permisos de administrador (uno por rubro, ej. juan=Hogar) con la clave `demo_clave`
  · www/nexus/entornos.json: de ahí nexus-branding.js sabe qué dashboard ve cada usuario (es visual, no seguridad)
  · la etiqueta "Orion Vigilar" en algunos sensores, para poder mostrar el aviso por email/WhatsApp
Todo es idempotente. El contenido sale de payload/demo (lo genera tools/gen_demo.py).
"""
import datetime
import hashlib
import json
import math
import os
import re
import sys
import time
import urllib.request

import instalar as I

DEMO = os.path.join(I.PAYLOAD, "demo")


def leer_manifiesto():
    with open(os.path.join(DEMO, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def copiar_contenido(man):
    """Paquetes, dashboards y entornos.json. Devuelve True si cambió algo que pide reiniciar Home Assistant."""
    cambio = False
    for sub in ("packages", "dashboards"):
        carpeta = os.path.join(DEMO, sub)
        if not os.path.isdir(carpeta):
            continue
        for n in sorted(os.listdir(carpeta)):
            if I._copiar_si_cambia(os.path.join(carpeta, n), os.path.join(I.CONFIG, sub, n)):
                cambio = True
                I.ok("%s/%s" % (sub, n))
    # el dashboard de cada rubro incluye la vista de Soporte
    soporte = os.path.join(I.CONFIG, "dashboards", "views", "soporte.yaml")
    if not os.path.exists(soporte):
        I._copiar_si_cambia(os.path.join(I.PAYLOAD, "config/dashboards/views/soporte.yaml"), soporte)
        cambio = True
    # quién ve qué (solo con los rubros que existen)
    entornos = {"usuarios": {u: man["rubros"][r]["dashboard"]["url_path"]
                             for u, r in man.get("usuarios", {}).items() if r in man["rubros"]}}
    nuevo = json.dumps(entornos, ensure_ascii=False, indent=2).encode("utf-8")
    ruta = os.path.join(I.CONFIG, "www", "nexus", "entornos.json")
    if not os.path.exists(ruta) or open(ruta, "rb").read() != nuevo:
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        with open(ruta, "wb") as f:
            f.write(nuevo)
        I.ok("www/nexus/entornos.json")
    if parchear_dashboards(man):
        cambio = True
    return cambio


def parchear_dashboards(man):
    """Agrega a configuration.yaml (lovelace: dashboards:) los dashboards de los rubros que falten."""
    cfg = os.path.join(I.CONFIG, "configuration.yaml")
    lineas = I.leer(cfg).split("\n")
    r = I.rango_bloque(lineas, "lovelace")
    faltan = []
    for rubro in man["rubros"].values():
        d = rubro["dashboard"]
        if r is None or (d["url_path"] + ":") not in "\n".join(lineas[r[0]:r[1]]):
            faltan.append(d)
    if not faltan:
        return False
    bloque = []
    for d in faltan:
        bloque += ["    %s:" % d["url_path"], "      mode: yaml", "      filename: %s" % d["archivo"],
                   "      title: %s" % d["titulo"], "      icon: %s" % d["icono"], "      show_in_sidebar: true"]
    copia = cfg + ".bak-demo-" + I.SELLO
    if not os.path.exists(copia):
        import shutil
        shutil.copy2(cfg, copia)
    if r is None:
        I.anexar(lineas, ["lovelace:", "  dashboards:"] + bloque)
    else:
        pos = next((i for i in range(r[0] + 1, r[1]) if re.match(r"^\s+dashboards:", lineas[i])), None)
        if pos is None:
            I.aviso("lovelace existe sin 'dashboards:': agregá los dashboards de demo a mano.")
            return False
        lineas[pos + 1:pos + 1] = bloque
    I.escribir(cfg, "\n".join(lineas).rstrip("\n") + "\n")
    I.ok("configuration.yaml: dashboards de demo (%s)" % ", ".join(d["url_path"] for d in faltan))
    return True


def reiniciar_core():
    """Verifica la configuración y reinicia Home Assistant. Devuelve True si lo reinició."""
    if not I.TOKEN:
        I.info("Sin supervisor: reiniciá Home Assistant a mano.")
        return False
    try:
        res = I.supervisor("/core/check")
    except Exception as e:  # noqa: BLE001
        I.aviso("No pude verificar la configuración: %s" % e)
        return False
    if res.get("result") != "ok":
        I.aviso("La configuración con el contenido de demo no es válida, no se reinicia: %s" % res)
        return False
    I.supervisor("/core/restart")
    I.ok("Home Assistant se está reiniciando para cargar la demo")
    return True


def accesos_demo(man, o):
    """Etiqueta 'Orion Vigilar' en los sensores marcados, entidades auxiliares ocultas y usuarios de demostración."""
    clave = (o.get("demo_clave") or "").strip()
    vigilar = [e for r in man["rubros"].values() for e in r.get("vigilar", [])]
    ocultar = [e for r in man["rubros"].values() for e in r.get("ocultar", [])]

    async def hacer(cmd):
        r = await cmd({"type": "config/label_registry/list"})
        if not any(x.get("label_id") == "orion_vigilar" for x in r.get("result", [])):
            await cmd({"type": "config/label_registry/create", "name": "Orion Vigilar"})
        for e in vigilar:
            g = await cmd({"type": "config/entity_registry/get", "entity_id": e})
            if not g.get("success"):
                continue
            etiquetas = list(g["result"].get("labels") or [])
            if "orion_vigilar" not in etiquetas:
                await cmd({"type": "config/entity_registry/update", "entity_id": e, "labels": etiquetas + ["orion_vigilar"]})
        for e in ocultar:
            g = await cmd({"type": "config/entity_registry/get", "entity_id": e})
            if g.get("success") and not g["result"].get("hidden_by"):
                await cmd({"type": "config/entity_registry/update", "entity_id": e, "hidden_by": "user"})
        usuarios = (await cmd({"type": "config/auth/list"})).get("result", [])
        for nombre, rubro in man.get("usuarios", {}).items():
            if rubro not in man["rubros"]:
                continue
            ya = next((x for x in usuarios if nombre in [c.get("username") for c in x.get("credentials", [])]
                       or (x.get("name") or "").lower() == nombre), None)
            if ya:
                continue
            if len(clave) < 8:
                I.aviso("Usuario demo '%s' sin crear: falta la opción demo_clave (mínimo 8 caracteres)." % nombre)
                continue
            r = await cmd({"type": "config/auth/create", "name": nombre.capitalize(), "group_ids": ["system-users"]})
            if not r.get("success"):
                I.aviso("No pude crear el usuario demo '%s': %s" % (nombre, r.get("error")))
                continue
            r2 = await cmd({"type": "config/auth_provider/homeassistant/create", "user_id": r["result"]["user"]["id"],
                            "username": nombre, "password": clave})
            if r2.get("success"):
                I.ok("Usuario demo '%s' (%s) creado" % (nombre, rubro))
            else:
                I.aviso("No pude ponerle clave a '%s': %s" % (nombre, r2.get("error")))
    I.ws_correr(hacer)


# ---------------------------------------------------------------- historial (estadísticas) precargado
MARCA_HIST = os.path.join(os.path.dirname(I.OPTIONS), "nexus_demo_historial")  # /data, privado del add-on
DIAS_HIST = 14
CLASE_UNIDAD = {"°C": "temperature", "W": "power", "kWh": "energy", "hPa": "pressure"}


def desfase_local():
    """Segundos entre la hora local de Home Assistant y UTC (las plantillas calculan con la hora local)."""
    req = urllib.request.Request(
        I.SUPERVISOR + "/core/api/template",
        data=json.dumps({"template": "{{ now().utcoffset().total_seconds() | int }}"}).encode("utf-8"), method="POST",
        headers={"Authorization": "Bearer " + I.TOKEN, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return int(r.read().decode("utf-8").strip())


def _desvio(dt_local):
    """Variación de un día a otro (±1), para que los días no sean copias idénticos."""
    return math.sin(dt_local.timetuple().tm_yday * 1.9)


def _onda(sp, hc, dev):
    v = sp["base"] + sp["amp"] * math.cos((hc - sp["pico"]) * 0.2618) + dev * abs(sp["amp"]) * 0.25
    return max(sp["minimo"], v) if sp.get("minimo") is not None else v


def _acum(sp, h, dev):
    v = (sp["p0"] * h + sp["amp"] * (math.sin((h - sp["pico"]) * 0.2618) - math.sin(-sp["pico"] * 0.2618)) / 0.2618)
    return v * sp["factor"] * (1 + 0.08 * dev)


def puntos(sp, desfase):
    """Una fila por hora de los últimos DIAS_HIST días (hasta la hora anterior a la actual)."""
    ahora = datetime.datetime.now(datetime.timezone.utc).replace(minute=0, second=0, microsecond=0)
    t = ahora - datetime.timedelta(days=DIAS_HIST)
    filas, previo, dia_actual = [], 0.0, None
    while t < ahora:
        local = t + datetime.timedelta(seconds=desfase)
        dev = _desvio(local)
        if sp["tipo"] == "onda":
            v = round(_onda(sp, local.hour + 0.5, dev), sp.get("dec", 1))
            tol = max(abs(sp["amp"]) * 0.08, 0.1)
            filas.append({"start": t.isoformat(), "mean": v, "min": round(v - tol, 2), "max": round(v + tol, 2)})
        else:
            if dia_actual is not None and local.date() != dia_actual[0]:
                previo += dia_actual[1]  # el día anterior terminó: su total pasa a la suma acumulada
            estado = round(_acum(sp, local.hour + 1, dev), 3)
            filas.append({"start": t.isoformat(), "state": estado, "sum": round(previo + estado, 3)})
            dia_actual = (local.date(), estado)
        t += datetime.timedelta(hours=1)
    return filas


def precargar_historial(man):
    """Carga ~14 días de estadísticas de largo plazo de los sensores ficticios, para que los gráficos y la pestaña
    Energía se vean con historia desde el primer día. Una sola vez por contenido (marca en /data)."""
    hist = [h for r in man["rubros"].values() for h in r.get("historial", [])]
    if not hist:
        return
    firma = hashlib.sha1(json.dumps(hist, sort_keys=True).encode("utf-8")).hexdigest()
    if os.path.exists(MARCA_HIST) and open(MARCA_HIST).read().strip() == firma:
        return
    desfase = desfase_local()
    fallos = []

    async def hacer(cmd):
        for sp in hist:
            meta = {"has_mean": not sp["suma"], "has_sum": sp["suma"], "name": None, "source": "recorder",
                    "statistic_id": sp["entity_id"], "unit_of_measurement": sp["unidad"],
                    "unit_class": CLASE_UNIDAD.get(sp["unidad"])}
            r = await cmd({"type": "recorder/import_statistics", "metadata": meta, "stats": puntos(sp, desfase)})
            if not r.get("success"):
                fallos.append("%s: %s" % (sp["entity_id"], (r.get("error") or {}).get("message", r)))
    I.ws_correr(hacer)
    if fallos:
        I.aviso("Historial de demo: %d sensores sin precargar (%s)" % (len(fallos), "; ".join(fallos[:3])))
        return
    with open(MARCA_HIST, "w") as f:
        f.write(firma)
    I.ok("Historial de demo precargado (%d sensores, %d días)" % (len(hist), DIAS_HIST))


def main():
    o = I.opciones()
    if not o.get("modo_demo"):
        return 0
    I.titulo("Nexus by Orion · modo demo")
    if not os.path.isdir(DEMO):
        I.aviso("Esta versión del add-on no trae contenido de demo.")
        return 0
    man = leer_manifiesto()
    reinicio = False
    try:
        if copiar_contenido(man):
            reinicio = reiniciar_core()
    except Exception as e:  # noqa: BLE001
        I.aviso("Modo demo: no pude copiar el contenido: %s" % e)
        return 1
    if not I.TOKEN:
        return 0
    if not I.esperar_core(maximo=600, pausa=45 if reinicio else 0):
        I.aviso("Home Assistant no respondió a tiempo: usuarios y etiquetas de demo sin crear.")
        return 1
    try:
        accesos_demo(man, o)
    except Exception as e:  # noqa: BLE001
        I.aviso("Modo demo: usuarios y etiquetas sin crear: %s" % e)
    try:
        precargar_historial(man)
    except Exception as e:  # noqa: BLE001
        I.aviso("Modo demo: no pude precargar el historial: %s" % e)
    I.ok("Modo demo al día")
    return 0


if __name__ == "__main__":
    sys.exit(main())
