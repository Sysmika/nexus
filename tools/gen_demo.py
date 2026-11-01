#!/usr/bin/env python3
"""Genera el contenido del MODO DEMO de Nexus (entidades ficticias + dashboards por rubro).

Salida (dentro del add-on):  nexus/payload/demo/
    packages/demo_<rubro>.yaml      entidades ficticias (template / thermostat / alarma manual / helpers)
    dashboards/<rubro>.yaml         dashboard del rubro
    manifest.json                   lo que necesita instalar.py (dashboards, usuarios, etiquetas)

Los valores no son fijos: salen de la hora (ondas senoidales + un poco de ruido), así que los sensores "respiran"
y los gráficos se ven vivos sin ningún dispositivo real.   Uso:  python tools/gen_demo.py
"""
import json
import os
import yaml

RAIZ = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "nexus", "payload", "demo")


class Dumper(yaml.SafeDumper):
    pass


def _str(d, v):
    if "\n" in v:
        return d.represent_scalar("tag:yaml.org,2002:str", v, style="|")
    return d.represent_scalar("tag:yaml.org,2002:str", v)


Dumper.add_representer(str, _str)
Dumper.ignore_aliases = lambda self, data: True


def volcar(obj):
    return yaml.dump(obj, Dumper=Dumper, allow_unicode=True, sort_keys=False, default_flow_style=False, width=1000)


# ------------------------------------------------------------------ plantillas de valores que "respiran"
H = "{% set h = now().hour + now().minute / 60 %}"
R = "{% set r = ((now().minute * 7 + now().hour * 3) % 7 - 3) / 3 %}"


class Plantilla(str):
    """Texto de plantilla que además recuerda con qué parámetros se calcula (para precargar el historial)."""
    spec = None


def _con_spec(texto, **spec):
    p = Plantilla(texto)
    p.spec = spec
    return p


def onda(base, amp, pico=15, ruido=0.3, dec=1, minimo=None, extra=""):
    """base + amp*cos(...) con máximo a la hora `pico` (+ ruido chico). amp<0 invierte la onda."""
    v = "%s + %s * cos((h - %s) * 0.2618) + r * %s%s" % (base, amp, pico, ruido, extra)
    if minimo is not None:
        v = "max(%s, %s)" % (minimo, v)
    return _con_spec(H + R + "{{ (%s) | round(%s) }}" % (v, dec), tipo="onda", base=base, amp=amp, pico=pico,
                     dec=dec, minimo=minimo)


def acumulado(p0, amp, pico, factor=0.001, dec=2):
    """Energía del día (kWh) = integral de p0 + amp*cos((h-pico)*0.2618) desde las 0 hs (se reinicia a medianoche)."""
    return _con_spec(H + "{{ ((%s * h + %s * (sin((h - %s) * 0.2618) - sin(-%s * 0.2618)) / 0.2618) * %s) | round(%s) }}"
                     % (p0, amp, pico, pico, factor, dec), tipo="acumulado", p0=p0, amp=amp, pico=pico, factor=factor)


def bateria(base, dias=120):
    """Batería que baja lentamente con el día del año."""
    return "{{ (%s - ((now().timetuple().tm_yday * 3) %% %s) / 10) | round(0) }}" % (base, dias)


HIST = []  # historial a precargar (lo lee demo.py desde manifest.json)


def slug(nombre):
    t = nombre.lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u"), ("ñ", "n"), ("ü", "u")):
        t = t.replace(a, b)
    import re
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", t)).strip("_")


def sensor(nombre, uid, unidad, estado, dc=None, sc="measurement", icono=None, disponible=None):
    d = {"name": nombre, "unique_id": uid, "state": str(estado)}
    spec = getattr(estado, "spec", None)
    if spec and unidad:
        HIST.append({"entity_id": "sensor." + slug(nombre), "unidad": unidad, "suma": sc == "total_increasing", **spec})
    if unidad:
        d["unit_of_measurement"] = unidad
    if dc:
        d["device_class"] = dc
    if sc:
        d["state_class"] = sc
    if icono:
        d["icon"] = icono
    if disponible:
        d["availability"] = disponible
    return d


def binario(nombre, uid, dc, estado, icono=None):
    d = {"name": nombre, "unique_id": uid, "device_class": dc, "state": estado}
    if icono:
        d["icon"] = icono
    return d


def luz(nombre, uid, atenuable=True, icono=None):
    d = {"name": nombre, "unique_id": uid, "turn_on": [], "turn_off": []}
    if atenuable:
        d["set_level"] = []
    if icono:
        d["icon"] = icono
    return d


def interruptor(nombre, uid, icono=None):
    d = {"name": nombre, "unique_id": uid, "turn_on": [], "turn_off": []}
    if icono:
        d["icon"] = icono
    return d


def persiana(nombre, uid, dc="shade", icono=None):
    d = {"name": nombre, "unique_id": uid, "device_class": dc, "open_cover": [], "close_cover": [], "stop_cover": [],
         "set_cover_position": []}
    if icono:
        d["icon"] = icono
    return d


def cuantos_on(entidades):
    return "{{ %r | select('is_state', 'on') | list | count }}" % (entidades,)


# ------------------------------------------------------------------ piezas de dashboard
def tile(entidad, nombre=None, icono=None, features=None, color=None, vertical=False, hide_state=False, tap=None, ancho=False):
    t = {"type": "tile", "entity": entidad}
    if ancho:
        t["grid_options"] = {"columns": 12}
    if hide_state:
        t["state_content"] = []
    if nombre:
        t["name"] = nombre
    if icono:
        t["icon"] = icono
    if color:
        t["color"] = color
    if vertical:
        t["vertical"] = True
    if features:
        t["features"] = features
        t["features_position"] = "bottom"
    if tap:
        t["tap_action"] = tap
    return t


def titulo(texto, icono=None, sub=None):
    h = {"type": "heading", "heading": texto, "heading_style": "title"}
    if icono:
        h["icon"] = icono
    if sub:
        h["subheading"] = sub
    return h


def seccion(*cards, span=1):
    s = {"type": "grid", "cards": list(cards)}
    if span != 1:
        s["column_span"] = span
    return s


def escena(script, nombre, icono, color):
    return {"type": "button", "entity": script, "name": nombre, "icon": icono, "show_state": False, "icon_height": "34px",
            "tap_action": {"action": "perform-action", "perform_action": "script.turn_on", "target": {"entity_id": script}},
            "grid_options": {"columns": 6, "rows": 2}}


def vista(titulo_, path, icono, secciones, max_cols=3):
    return {"title": titulo_, "path": path, "icon": icono, "type": "sections", "max_columns": max_cols,
            "theme": "Nexus", "sections": secciones}


def guardar_dashboard(rubro, vistas):
    texto = ("# Dashboard demo \"%s\" — GENERADO por tools/gen_demo.py (no editar a mano: se pisa en cada actualización).\n"
             % rubro)
    texto += volcar({"title": "Nexus", "views": vistas})
    texto += "- !include views/soporte.yaml\n"
    ruta = os.path.join(RAIZ, "dashboards", rubro + ".yaml")
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write(texto)


def guardar_paquete(rubro, paquete):
    ruta = os.path.join(RAIZ, "packages", "demo_%s.yaml" % rubro)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8", newline="\n") as f:
        f.write("# Entidades FICTICIAS del modo demo \"%s\" — GENERADO por tools/gen_demo.py (no editar a mano).\n" % rubro)
        f.write(volcar(paquete))


# ======================================================================================================
#  HOGAR
# ======================================================================================================
def hogar():
    p = "hogar"
    HIST.clear()
    luces = ["light.hogar_luz_living", "light.hogar_luz_cocina", "light.hogar_luz_dormitorio",
             "light.hogar_luz_pasillo", "light.hogar_luz_jardin"]
    falla = "{{ is_state('input_boolean.demo_falla_hogar', 'off') }}"

    potencia = (H + R + "{% set luces = " + repr(luces) + " %}"
                "{{ (380 + 240 * cos((h - 20) * 0.2618) + r * 25 + (luces | select('is_state', 'on') | list | count) * 45"
                " + (900 if is_state('switch.hogar_aa_living_compresor', 'on') else 0)) | round(0) }}")

    sensores = [
        sensor("Hogar Temperatura Living", "demo_hogar_temp_living", "°C", onda(23.5, 2.0, 16), "temperature"),
        sensor("Hogar Humedad Living", "demo_hogar_hum_living", "%", onda(52, -7, 16, 1, 0), "humidity"),
        sensor("Hogar Temperatura Dormitorio", "demo_hogar_temp_dormitorio", "°C", onda(22.0, 2.0, 17), "temperature",
               disponible=falla),
        sensor("Hogar Humedad Dormitorio", "demo_hogar_hum_dormitorio", "%", onda(55, -6, 17, 1, 0), "humidity"),
        sensor("Hogar Temperatura Cocina", "demo_hogar_temp_cocina", "°C", onda(24.5, 2.5, 14), "temperature"),
        sensor("Hogar Temperatura Exterior", "demo_hogar_temp_exterior", "°C", onda(20, 7, 15, 0.4), "temperature"),
        sensor("Hogar Humedad Exterior", "demo_hogar_hum_exterior", "%", onda(62, -18, 15, 2, 0), "humidity"),
        sensor("Hogar Presión", "demo_hogar_presion", "hPa", onda(1014, 3, 10, 0.5), "atmospheric_pressure"),
        sensor("Hogar CO2 Living", "demo_hogar_co2_living", "ppm", onda(640, 190, 21, 12, 0), "carbon_dioxide"),
        sensor("Hogar Partículas PM2.5", "demo_hogar_pm25", "µg/m³", onda(9, 4, 19, 0.8, 0, 1), "pm25"),
        sensor("Hogar Luminosidad Living", "demo_hogar_lux_living", "lx", onda(330, 340, 13, 20, 0, 0), "illuminance"),
        sensor("Hogar Consumo Eléctrico", "demo_hogar_potencia", "W",
               _con_spec(potencia, tipo="onda", base=470, amp=240, pico=20, dec=0, minimo=None), "power"),
        sensor("Hogar Energía Hoy", "demo_hogar_energia_hoy", "kWh", acumulado(380, 240, 20), "energy",
               sc="total_increasing"),
        sensor("Hogar Batería Sensor Puerta", "demo_hogar_bat_puerta", "%", bateria(86), "battery"),
        sensor("Hogar Batería Sensor Movimiento", "demo_hogar_bat_mov", "%", bateria(74), "battery"),
        sensor("Hogar Batería Sensor Fuga", "demo_hogar_bat_fuga", "%", bateria(92), "battery"),
    ]
    binarios = [
        binario("Hogar Puerta Principal", "demo_hogar_puerta", "door", "{{ false }}"),
        binario("Hogar Ventana Dormitorio", "demo_hogar_ventana", "window", "{{ 10 <= now().hour < 18 }}"),
        binario("Hogar Movimiento Pasillo", "demo_hogar_mov_pasillo", "motion", "{{ now().minute % 13 < 2 }}"),
        binario("Hogar Presencia", "demo_hogar_presencia", "occupancy", "{{ now().hour >= 18 or now().hour < 8 }}"),
        binario("Hogar Fuga de Agua Baño", "demo_hogar_fuga", "moisture", "{{ false }}"),
        binario("Hogar Humo Cocina", "demo_hogar_humo", "smoke", "{{ false }}"),
    ]
    paquete = {
        "input_boolean": {
            "demo_falla_hogar": {"name": "Demo · Simular falla del sensor del dormitorio", "icon": "mdi:alert-circle-outline"},
            "demo_hogar_cerradura": {"name": "Demo · Hogar cerradura puerta (cerrada)", "icon": "mdi:lock", "initial": True},
        },
        "template": [
            {"sensor": sensores},
            {"binary_sensor": binarios},
            {"light": [
                luz("Hogar Luz Living", "demo_hogar_luz_living", icono="mdi:sofa"),
                luz("Hogar Luz Cocina", "demo_hogar_luz_cocina", icono="mdi:countertop"),
                luz("Hogar Luz Dormitorio", "demo_hogar_luz_dormitorio", icono="mdi:bed"),
                luz("Hogar Luz Pasillo", "demo_hogar_luz_pasillo", icono="mdi:lightbulb-group"),
                luz("Hogar Luz Jardín", "demo_hogar_luz_jardin", atenuable=False, icono="mdi:outdoor-lamp"),
            ]},
            {"switch": [
                interruptor("Hogar Riego Jardín", "demo_hogar_riego", "mdi:sprinkler-variant"),
                interruptor("Hogar Bomba Piscina", "demo_hogar_piscina", "mdi:pool"),
                interruptor("Hogar Enchufe TV", "demo_hogar_tv", "mdi:television"),
                interruptor("Hogar Cargador Auto", "demo_hogar_cargador", "mdi:ev-station"),
                interruptor("Hogar AA Living Compresor", "demo_hogar_aa_compresor", "mdi:air-conditioner"),
            ]},
            {"cover": [
                persiana("Hogar Persiana Living", "demo_hogar_pers_living", icono="mdi:blinds"),
                persiana("Hogar Persiana Dormitorio", "demo_hogar_pers_dorm", icono="mdi:blinds"),
                persiana("Hogar Portón Garage", "demo_hogar_garage", "garage", "mdi:garage"),
            ]},
            {"lock": [{
                "name": "Hogar Cerradura Puerta", "unique_id": "demo_hogar_cerradura",
                "state": "{{ is_state('input_boolean.demo_hogar_cerradura', 'on') | iif('locked', 'unlocked') }}",
                "lock": [{"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.demo_hogar_cerradura"}}],
                "unlock": [{"action": "input_boolean.turn_off", "target": {"entity_id": "input_boolean.demo_hogar_cerradura"}}],
            }]},
        ],
        "climate": [{
            "platform": "generic_thermostat", "name": "Hogar AA Living", "unique_id": "demo_hogar_aa_living",
            "heater": "switch.hogar_aa_living_compresor", "target_sensor": "sensor.hogar_temperatura_living",
            "ac_mode": True, "min_temp": 18, "max_temp": 30, "target_temp": 24, "precision": 0.5, "target_temp_step": 0.5,
            "initial_hvac_mode": "cool", "cold_tolerance": 0.5, "hot_tolerance": 0.5,
        }],
        "alarm_control_panel": [{
            "platform": "manual", "name": "Hogar Alarma", "unique_id": "demo_hogar_alarma",
            "code_arm_required": False, "arming_time": 5, "delay_time": 5, "trigger_time": 30,
        }],
        "script": {
            "demo_hogar_buenos_dias": {"alias": "Buenos días", "icon": "mdi:weather-sunny", "sequence": [
                {"action": "light.turn_off", "target": {"entity_id": ["light.hogar_luz_dormitorio", "light.hogar_luz_jardin", "light.hogar_luz_pasillo"]}},
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_cocina"}, "data": {"brightness_pct": 80}},
                {"action": "cover.open_cover", "target": {"entity_id": ["cover.hogar_persiana_living", "cover.hogar_persiana_dormitorio"]}},
                {"action": "alarm_control_panel.alarm_disarm", "target": {"entity_id": "alarm_control_panel.hogar_alarma"}},
            ]},
            "demo_hogar_buenas_noches": {"alias": "Buenas noches", "icon": "mdi:weather-night", "sequence": [
                {"action": "light.turn_off", "target": {"entity_id": ["light.hogar_luz_living", "light.hogar_luz_cocina", "light.hogar_luz_jardin"]}},
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_dormitorio"}, "data": {"brightness_pct": 15}},
                {"action": "cover.close_cover", "target": {"entity_id": ["cover.hogar_persiana_living", "cover.hogar_persiana_dormitorio"]}},
                {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.demo_hogar_cerradura"}},
                {"action": "alarm_control_panel.alarm_arm_home", "target": {"entity_id": "alarm_control_panel.hogar_alarma"}},
            ]},
            "demo_hogar_salgo": {"alias": "Salgo de casa", "icon": "mdi:exit-run", "sequence": [
                {"action": "light.turn_off", "target": {"entity_id": luces}},
                {"action": "switch.turn_off", "target": {"entity_id": ["switch.hogar_enchufe_tv", "switch.hogar_riego_jardin"]}},
                {"action": "cover.close_cover", "target": {"entity_id": "cover.hogar_porton_garage"}},
                {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.demo_hogar_cerradura"}},
                {"action": "alarm_control_panel.alarm_arm_away", "target": {"entity_id": "alarm_control_panel.hogar_alarma"}},
            ]},
            "demo_hogar_cine": {"alias": "Modo cine", "icon": "mdi:movie-open", "sequence": [
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_living"}, "data": {"brightness_pct": 10}},
                {"action": "light.turn_off", "target": {"entity_id": ["light.hogar_luz_cocina", "light.hogar_luz_pasillo"]}},
                {"action": "cover.close_cover", "target": {"entity_id": "cover.hogar_persiana_living"}},
                {"action": "switch.turn_on", "target": {"entity_id": "switch.hogar_enchufe_tv"}},
            ]},
            "demo_hogar_inicializar": {"alias": "Demo · Estado inicial del hogar", "icon": "mdi:restart", "sequence": [
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_living"}, "data": {"brightness_pct": 70}},
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_cocina"}, "data": {"brightness_pct": 100}},
                {"action": "light.turn_on", "target": {"entity_id": "light.hogar_luz_jardin"}},
                {"action": "light.turn_off", "target": {"entity_id": ["light.hogar_luz_dormitorio", "light.hogar_luz_pasillo"]}},
                {"action": "cover.set_cover_position", "target": {"entity_id": "cover.hogar_persiana_living"}, "data": {"position": 60}},
                {"action": "cover.set_cover_position", "target": {"entity_id": "cover.hogar_persiana_dormitorio"}, "data": {"position": 100}},
                {"action": "cover.close_cover", "target": {"entity_id": "cover.hogar_porton_garage"}},
                {"action": "switch.turn_on", "target": {"entity_id": "switch.hogar_bomba_piscina"}},
                {"action": "switch.turn_off", "target": {"entity_id": ["switch.hogar_riego_jardin", "switch.hogar_cargador_auto", "switch.hogar_enchufe_tv"]}},
                {"action": "climate.set_temperature", "target": {"entity_id": "climate.hogar_aa_living"}, "data": {"temperature": 24, "hvac_mode": "cool"}},
            ]},
        },
        "automation": [{
            "id": "demo_hogar_arranque", "alias": "Demo · Dejar el hogar en su estado inicial (una sola vez)",
            "mode": "single",
            "triggers": [{"trigger": "homeassistant", "event": "start"}],
            "conditions": [{"condition": "state", "entity_id": "input_boolean.demo_hogar_inicializado", "state": "off"}],
            "actions": [
                {"delay": {"seconds": 60}},
                {"action": "script.demo_hogar_inicializar"},
                {"action": "input_boolean.turn_on", "target": {"entity_id": "input_boolean.demo_hogar_inicializado"}},
            ],
        }],
    }
    paquete["input_boolean"]["demo_hogar_inicializado"] = {"name": "Demo · Hogar ya inicializado", "icon": "mdi:check", "initial": False}

    # ---------------------------------------------------------------- dashboard
    inicio = vista("Inicio", "inicio", "mdi:home", [
        seccion(
            titulo("Tu casa", "mdi:home-heart", "Todo en un vistazo"),
            tile("alarm_control_panel.hogar_alarma", "Alarma", ancho=True, features=[{"type": "alarm-modes", "modes": ["armed_home", "armed_away", "disarmed"]}]),
            tile("lock.hogar_cerradura_puerta", "Puerta de entrada", ancho=True, features=[{"type": "lock-commands"}]),
            tile("binary_sensor.hogar_presencia", "Presencia"),
            tile("binary_sensor.hogar_puerta_principal", "Puerta"),
            tile("binary_sensor.hogar_movimiento_pasillo", "Movimiento"),
            tile("sensor.hogar_consumo_electrico", "Consumo", "mdi:flash"),
        ),
        seccion(
            titulo("Clima", "mdi:thermometer", "Ambientes y aire acondicionado"),
            {"type": "thermostat", "entity": "climate.hogar_aa_living", "name": "Aire acondicionado living",
             "features": [{"type": "climate-hvac-modes", "hvac_modes": ["cool", "off"]}]},
            tile("sensor.hogar_temperatura_living", "Living", "mdi:sofa"),
            tile("sensor.hogar_humedad_living", "Humedad"),
            tile("sensor.hogar_temperatura_dormitorio", "Dormitorio", "mdi:bed"),
            tile("sensor.hogar_temperatura_cocina", "Cocina", "mdi:countertop"),
            tile("sensor.hogar_temperatura_exterior", "Exterior", "mdi:tree"),
            tile("sensor.hogar_co2_living", "CO₂"),
        ),
        seccion(
            titulo("Luces", "mdi:lightbulb-group"),
            tile("light.hogar_luz_living", "Living", features=[{"type": "light-brightness"}]),
            tile("light.hogar_luz_cocina", "Cocina", features=[{"type": "light-brightness"}]),
            tile("light.hogar_luz_dormitorio", "Dormitorio", features=[{"type": "light-brightness"}]),
            tile("light.hogar_luz_pasillo", "Pasillo", features=[{"type": "light-brightness"}]),
            tile("light.hogar_luz_jardin", "Jardín"),
        ),
        seccion(
            titulo("Persianas y accesos", "mdi:blinds"),
            tile("cover.hogar_persiana_living", "Persiana living", ancho=True, features=[{"type": "cover-open-close"}, {"type": "cover-position"}]),
            tile("cover.hogar_persiana_dormitorio", "Persiana dormitorio", ancho=True, features=[{"type": "cover-open-close"}, {"type": "cover-position"}]),
            tile("cover.hogar_porton_garage", "Portón del garage", ancho=True, features=[{"type": "cover-open-close"}]),
        ),
        seccion(
            titulo("Equipos", "mdi:power-plug"),
            tile("switch.hogar_riego_jardin", "Riego"),
            tile("switch.hogar_bomba_piscina", "Piscina"),
            tile("switch.hogar_enchufe_tv", "TV"),
            tile("switch.hogar_cargador_auto", "Cargador auto"),
        ),
        seccion(
            titulo("Escenas", "mdi:palette"),
            escena("script.demo_hogar_buenos_dias", "Buenos días", "mdi:weather-sunny", "amber"),
            escena("script.demo_hogar_buenas_noches", "Buenas noches", "mdi:weather-night", "indigo"),
            escena("script.demo_hogar_salgo", "Salgo de casa", "mdi:exit-run", "red"),
            escena("script.demo_hogar_cine", "Modo cine", "mdi:movie-open", "purple"),
        ),
    ])

    energia = vista("Energía", "energia", "mdi:lightning-bolt", [
        seccion(
            titulo("Consumo", "mdi:flash", "En vivo y del día"),
            {"type": "gauge", "entity": "sensor.hogar_consumo_electrico", "name": "Potencia ahora", "min": 0, "max": 3000,
             "needle": True, "severity": {"green": 0, "yellow": 1500, "red": 2300}},
            tile("sensor.hogar_energia_hoy", "Energía de hoy", "mdi:lightning-bolt-circle", ancho=True),
        ),
        seccion(
            titulo("Evolución", "mdi:chart-line", "Últimos días"),
            {"type": "statistics-graph", "title": "Potencia (promedio por hora)", "days_to_show": 3, "period": "hour",
             "stat_types": ["mean"], "chart_type": "line", "entities": ["sensor.hogar_consumo_electrico"]},
            {"type": "statistics-graph", "title": "Energía por día", "days_to_show": 14, "period": "day",
             "stat_types": ["change"], "chart_type": "bar", "entities": ["sensor.hogar_energia_hoy"]},
        ),
        seccion(
            titulo("Ambiente", "mdi:thermometer-lines", "Últimos días"),
            {"type": "statistics-graph", "title": "Temperaturas", "days_to_show": 3, "period": "hour",
             "stat_types": ["mean"], "chart_type": "line",
             "entities": ["sensor.hogar_temperatura_living", "sensor.hogar_temperatura_dormitorio",
                          "sensor.hogar_temperatura_cocina", "sensor.hogar_temperatura_exterior"]},
            {"type": "statistics-graph", "title": "CO₂ del living", "days_to_show": 3, "period": "hour",
             "stat_types": ["mean"], "chart_type": "line", "entities": ["sensor.hogar_co2_living"]},
        ),
    ])

    seguridad = vista("Seguridad", "seguridad", "mdi:shield-home", [
        seccion(
            titulo("Alarma y accesos", "mdi:shield-lock"),
            {"type": "alarm-panel", "entity": "alarm_control_panel.hogar_alarma", "name": "Alarma del hogar",
             "states": ["arm_home", "arm_away"]},
            tile("lock.hogar_cerradura_puerta", "Puerta de entrada", features=[{"type": "lock-commands"}]),
            tile("cover.hogar_porton_garage", "Portón del garage", features=[{"type": "cover-open-close"}]),
        ),
        seccion(
            titulo("Sensores", "mdi:motion-sensor"),
            tile("binary_sensor.hogar_puerta_principal", "Puerta principal", ancho=True),
            tile("binary_sensor.hogar_ventana_dormitorio", "Ventana dormitorio", ancho=True),
            tile("binary_sensor.hogar_movimiento_pasillo", "Movimiento pasillo", ancho=True),
            tile("binary_sensor.hogar_fuga_de_agua_bano", "Fuga de agua (baño)", ancho=True),
            tile("binary_sensor.hogar_humo_cocina", "Humo (cocina)", ancho=True),
        ),
        seccion(
            titulo("Baterías", "mdi:battery-heart-variant"),
            tile("sensor.hogar_bateria_sensor_puerta", "Sensor de puerta", ancho=True),
            tile("sensor.hogar_bateria_sensor_movimiento", "Sensor de movimiento", ancho=True),
            tile("sensor.hogar_bateria_sensor_fuga", "Sensor de fuga", ancho=True),
        ),
        seccion(
            titulo("Actividad reciente", "mdi:history"),
            {"type": "logbook", "hours_to_show": 24, "target": {"entity_id": [
                "binary_sensor.hogar_movimiento_pasillo", "binary_sensor.hogar_ventana_dormitorio",
                "lock.hogar_cerradura_puerta", "alarm_control_panel.hogar_alarma", "cover.hogar_porton_garage"]}},
        ),
    ])
    guardar_paquete(p, paquete)
    guardar_dashboard(p, [inicio, energia, seguridad])
    return {
        "dashboard": {"url_path": "dashboard-hogar", "titulo": "Hogar", "icono": "mdi:home", "archivo": "dashboards/hogar.yaml"},
        # sensor que se puede "romper" para mostrar el aviso por email/WhatsApp
        "vigilar": ["sensor.hogar_temperatura_dormitorio", "sensor.hogar_temperatura_living", "binary_sensor.hogar_puerta_principal"],
        "ocultar": ["input_boolean.demo_hogar_cerradura", "input_boolean.demo_hogar_inicializado",
                    "switch.hogar_aa_living_compresor"],
        "historial": list(HIST),
    }


# ======================================================================================================
#  Piezas comunes de Oficina y Comercio
# ======================================================================================================
def eid(dominio, nombre):
    return "%s.%s" % (dominio, slug(nombre))


def acc(servicio, entidades, **datos):
    a = {"action": servicio, "target": {"entity_id": entidades}}
    if datos:
        a["data"] = datos
    return a


def arranque(pref, titulo_, marcador):
    return {
        "id": "demo_%s_arranque" % pref, "alias": "Demo · Dejar %s en su estado inicial (una sola vez)" % titulo_,
        "mode": "single",
        "triggers": [{"trigger": "homeassistant", "event": "start"}],
        "conditions": [{"condition": "state", "entity_id": marcador, "state": "off"}],
        "actions": [{"delay": {"seconds": 60}}, {"action": "script.demo_%s_inicializar" % pref},
                    {"action": "input_boolean.turn_on", "target": {"entity_id": marcador}}],
    }


def cerradura(nombre, uid, ib):
    return {"name": nombre, "unique_id": uid,
            "state": "{{ is_state('%s', 'on') | iif('locked', 'unlocked') }}" % ib,
            "lock": [{"action": "input_boolean.turn_on", "target": {"entity_id": ib}}],
            "unlock": [{"action": "input_boolean.turn_off", "target": {"entity_id": ib}}]}


def termostato(nombre, uid, compresor, sensor_id, objetivo):
    return {"platform": "generic_thermostat", "name": nombre, "unique_id": uid, "heater": compresor,
            "target_sensor": sensor_id, "ac_mode": True, "min_temp": 16, "max_temp": 30, "target_temp": objetivo,
            "precision": 0.5, "target_temp_step": 0.5, "initial_hvac_mode": "cool", "cold_tolerance": 0.5,
            "hot_tolerance": 0.5}


def alarma(nombre, uid):
    return {"platform": "manual", "name": nombre, "unique_id": uid, "code_arm_required": False,
            "arming_time": 5, "delay_time": 5, "trigger_time": 30}


def grafico(titulo_, entidades, dias=3, tipos=("mean",), periodo="hour", tipo="line"):
    return {"type": "statistics-graph", "title": titulo_, "days_to_show": dias, "period": periodo,
            "stat_types": list(tipos), "chart_type": tipo, "entities": entidades}


# ======================================================================================================
#  OFICINA
# ======================================================================================================
def oficina():
    p = "oficina"
    HIST.clear()
    falla = "{{ is_state('input_boolean.demo_falla_oficina', 'off') }}"
    luces = ["Oficina Luz Recepción", "Oficina Luz Open Space", "Oficina Luz Sala de Reuniones", "Oficina Luz Pasillo",
             "Oficina Luz Cartel"]
    luces_ids = [eid("light", n) for n in luces]
    potencia = (H + R + "{% set luces = " + repr(luces_ids) + " %}"
                "{{ (2100 + 1100 * cos((h - 14) * 0.2618) + r * 60 + (luces | select('is_state', 'on') | list | count) * 55"
                " + (1200 if is_state('switch.oficina_aa_open_space_compresor', 'on') else 0)) | round(0) }}")

    sensores = [
        sensor("Oficina Temperatura Sala de Servidores", "demo_of_temp_srv", "°C", onda(24.0, 1.4, 15, 0.2), "temperature",
               disponible=falla),
        sensor("Oficina Humedad Sala de Servidores", "demo_of_hum_srv", "%", onda(42, -4, 15, 1, 0), "humidity"),
        sensor("Oficina Temperatura Open Space", "demo_of_temp_open", "°C", onda(23.5, 2.2, 15), "temperature"),
        sensor("Oficina Humedad Open Space", "demo_of_hum_open", "%", onda(48, -6, 15, 1, 0), "humidity"),
        sensor("Oficina CO2 Open Space", "demo_of_co2", "ppm", onda(620, 300, 14, 14, 0, 420), "carbon_dioxide"),
        sensor("Oficina Personas Presentes", "demo_of_personas", "personas", onda(8, 10, 13, 0.8, 0, 0), None,
               icono="mdi:account-group"),
        sensor("Oficina Luminosidad Open Space", "demo_of_lux", "lx", onda(380, 320, 13, 18, 0, 0), "illuminance"),
        sensor("Oficina Consumo Eléctrico", "demo_of_potencia", "W",
               _con_spec(potencia, tipo="onda", base=2300, amp=1100, pico=14, dec=0, minimo=None), "power"),
        sensor("Oficina Energía Hoy", "demo_of_energia", "kWh", acumulado(2100, 1100, 14), "energy", sc="total_increasing"),
        sensor("Oficina UPS Carga de Batería", "demo_of_ups_bateria", "%", "{{ 100 }}", "battery"),
        sensor("Oficina UPS Autonomía", "demo_of_ups_min", "min", onda(46, 3, 12, 0.5, 0), None, icono="mdi:timer-outline"),
        sensor("Oficina UPS Carga Conectada", "demo_of_ups_carga", "%", onda(38, 7, 14, 1, 0), None, icono="mdi:gauge"),
        sensor("Oficina Internet Latencia", "demo_of_ping", "ms", onda(16, 5, 15, 3, 0, 8), None, icono="mdi:speedometer"),
        sensor("Oficina Internet Descarga", "demo_of_bajada", "Mbit/s", onda(310, -45, 14, 8, 0), "data_rate"),
        sensor("Oficina Internet Subida", "demo_of_subida", "Mbit/s", onda(142, -22, 14, 5, 0), "data_rate"),
        sensor("Oficina Servidor CPU", "demo_of_cpu", "%", onda(34, 22, 11, 4, 0, 3), None, icono="mdi:cpu-64-bit"),
        sensor("Oficina NAS Temperatura de Discos", "demo_of_nas_temp", "°C", onda(38, 3, 16, 0.4, 0), "temperature"),
        sensor("Oficina NAS Espacio Usado", "demo_of_nas_uso", "%",
               "{{ (58 + (now().timetuple().tm_yday % 30) * 0.2) | round(1) }}", None, icono="mdi:harddisk"),
        sensor("Oficina Impresora Tóner", "demo_of_toner", "%", bateria(71, 90), None, icono="mdi:printer"),
        sensor("Oficina Batería Sensor Puerta", "demo_of_bat_puerta", "%", bateria(81), "battery"),
        sensor("Oficina Batería Sensor Sala de Servidores", "demo_of_bat_srv", "%", bateria(67), "battery"),
    ]
    binarios = [
        binario("Oficina Puerta de Ingreso", "demo_of_puerta", "door", "{{ now().minute % 17 == 3 and 8 <= now().hour < 19 }}"),
        binario("Oficina Puerta Sala de Servidores", "demo_of_puerta_srv", "door", "{{ false }}"),
        binario("Oficina Movimiento Recepción", "demo_of_mov_rec", "motion", "{{ 8 <= now().hour < 19 and now().minute % 7 < 3 }}"),
        binario("Oficina Sala de Reuniones Ocupada", "demo_of_reunion", "occupancy", "{{ now().hour in [10, 11, 15, 16] }}"),
        binario("Oficina Internet Conectado", "demo_of_internet", "connectivity", "{{ true }}"),
        binario("Oficina UPS en Batería", "demo_of_ups_en_bateria", "power", "{{ false }}"),
        binario("Oficina Humo", "demo_of_humo", "smoke", "{{ false }}"),
        binario("Oficina Fuga de Agua Sala de Servidores", "demo_of_fuga", "moisture", "{{ false }}"),
    ]
    paquete = {
        "input_boolean": {
            "demo_falla_oficina": {"name": "Demo · Simular falla del sensor de la sala de servidores", "icon": "mdi:alert-circle-outline"},
            "demo_oficina_cerradura_ingreso": {"name": "Demo · Oficina cerradura ingreso", "icon": "mdi:lock", "initial": True},
            "demo_oficina_cerradura_srv": {"name": "Demo · Oficina cerradura servidores", "icon": "mdi:lock", "initial": True},
            "demo_oficina_inicializado": {"name": "Demo · Oficina ya inicializada", "icon": "mdi:check", "initial": False},
        },
        "template": [
            {"sensor": sensores},
            {"binary_sensor": binarios},
            {"light": [luz(luces[0], "demo_of_luz_rec", icono="mdi:desk-lamp"),
                       luz(luces[1], "demo_of_luz_open", icono="mdi:ceiling-light"),
                       luz(luces[2], "demo_of_luz_reu", icono="mdi:presentation"),
                       luz(luces[3], "demo_of_luz_pas", icono="mdi:lightbulb-group"),
                       luz(luces[4], "demo_of_luz_cartel", atenuable=False, icono="mdi:sign-direction")]},
            {"switch": [interruptor("Oficina Proyector", "demo_of_proyector", "mdi:projector"),
                        interruptor("Oficina Cafetera", "demo_of_cafetera", "mdi:coffee-maker"),
                        interruptor("Oficina Cartelería Digital", "demo_of_carteleria", "mdi:monitor-shimmer"),
                        interruptor("Oficina Enchufes Escritorios", "demo_of_enchufes", "mdi:power-socket-ar"),
                        interruptor("Oficina AA Open Space Compresor", "demo_of_aa1_comp", "mdi:air-conditioner"),
                        interruptor("Oficina AA Sala de Servidores Compresor", "demo_of_aa2_comp", "mdi:air-conditioner")]},
            {"cover": [persiana("Oficina Cortina Sala de Reuniones", "demo_of_cortina_reu", icono="mdi:curtains"),
                       persiana("Oficina Persiana Open Space", "demo_of_pers_open", icono="mdi:blinds"),
                       persiana("Oficina Portón Estacionamiento", "demo_of_porton", "garage", "mdi:gate")]},
            {"lock": [cerradura("Oficina Cerradura Ingreso", "demo_of_cerr_ing", "input_boolean.demo_oficina_cerradura_ingreso"),
                      cerradura("Oficina Cerradura Sala de Servidores", "demo_of_cerr_srv", "input_boolean.demo_oficina_cerradura_srv")]},
        ],
        "climate": [termostato("Oficina AA Open Space", "demo_of_aa1", "switch.oficina_aa_open_space_compresor",
                               "sensor.oficina_temperatura_open_space", 23),
                    termostato("Oficina AA Sala de Servidores", "demo_of_aa2", "switch.oficina_aa_sala_de_servidores_compresor",
                               "sensor.oficina_temperatura_sala_de_servidores", 22)],
        "alarm_control_panel": [alarma("Oficina Alarma", "demo_of_alarma")],
        "script": {
            "demo_oficina_abrir": {"alias": "Abrir la oficina", "icon": "mdi:key-variant", "sequence": [
                acc("input_boolean.turn_off", "input_boolean.demo_oficina_cerradura_ingreso"),
                acc("alarm_control_panel.alarm_disarm", "alarm_control_panel.oficina_alarma"),
                acc("light.turn_on", [luces_ids[0], luces_ids[1], luces_ids[3]], brightness_pct=85),
                acc("cover.open_cover", [eid("cover", "Oficina Persiana Open Space"), eid("cover", "Oficina Portón Estacionamiento")]),
                acc("switch.turn_on", [eid("switch", "Oficina Cafetera"), eid("switch", "Oficina Cartelería Digital")]),
                acc("climate.turn_on", ["climate.oficina_aa_open_space"]),
            ]},
            "demo_oficina_cerrar": {"alias": "Cerrar la oficina", "icon": "mdi:lock-check", "sequence": [
                acc("light.turn_off", luces_ids),
                acc("switch.turn_off", [eid("switch", "Oficina Proyector"), eid("switch", "Oficina Cafetera"),
                                         eid("switch", "Oficina Cartelería Digital"), eid("switch", "Oficina Enchufes Escritorios")]),
                acc("cover.close_cover", [eid("cover", "Oficina Persiana Open Space"), eid("cover", "Oficina Portón Estacionamiento")]),
                acc("input_boolean.turn_on", ["input_boolean.demo_oficina_cerradura_ingreso", "input_boolean.demo_oficina_cerradura_srv"]),
                acc("alarm_control_panel.alarm_arm_away", "alarm_control_panel.oficina_alarma"),
            ]},
            "demo_oficina_reunion": {"alias": "Modo reunión", "icon": "mdi:presentation", "sequence": [
                acc("light.turn_on", luces_ids[2], brightness_pct=40),
                acc("cover.close_cover", eid("cover", "Oficina Cortina Sala de Reuniones")),
                acc("switch.turn_on", eid("switch", "Oficina Proyector")),
            ]},
            "demo_oficina_ahorro": {"alias": "Modo ahorro de energía", "icon": "mdi:leaf", "sequence": [
                acc("light.turn_off", [luces_ids[2], luces_ids[3], luces_ids[4]]),
                acc("switch.turn_off", [eid("switch", "Oficina Proyector"), eid("switch", "Oficina Enchufes Escritorios")]),
                acc("climate.set_temperature", "climate.oficina_aa_open_space", temperature=25),
            ]},
            "demo_oficina_inicializar": {"alias": "Demo · Estado inicial de la oficina", "icon": "mdi:restart", "sequence": [
                acc("light.turn_on", luces_ids[0], brightness_pct=90),
                acc("light.turn_on", luces_ids[1], brightness_pct=100),
                acc("light.turn_on", luces_ids[3], brightness_pct=60),
                acc("light.turn_off", luces_ids[2]),
                acc("light.turn_on", luces_ids[4]),
                acc("cover.set_cover_position", eid("cover", "Oficina Cortina Sala de Reuniones"), position=100),
                acc("cover.set_cover_position", eid("cover", "Oficina Persiana Open Space"), position=70),
                acc("cover.close_cover", eid("cover", "Oficina Portón Estacionamiento")),
                acc("switch.turn_on", [eid("switch", "Oficina Cafetera"), eid("switch", "Oficina Cartelería Digital"),
                                        eid("switch", "Oficina Enchufes Escritorios")]),
                acc("switch.turn_off", eid("switch", "Oficina Proyector")),
                acc("climate.set_temperature", "climate.oficina_aa_open_space", temperature=23, hvac_mode="cool"),
                acc("climate.set_temperature", "climate.oficina_aa_sala_de_servidores", temperature=22, hvac_mode="cool"),
            ]},
        },
        "automation": [arranque("oficina", "la oficina", "input_boolean.demo_oficina_inicializado")],
    }
    T = tile
    inicio = vista("Inicio", "inicio", "mdi:office-building", [
        seccion(
            titulo("Accesos", "mdi:shield-key", "Alarma y cerraduras"),
            T("alarm_control_panel.oficina_alarma", "Alarma", ancho=True, features=[{"type": "alarm-modes", "modes": ["armed_home", "armed_away", "disarmed"]}]),
            T("lock.oficina_cerradura_ingreso", "Ingreso", ancho=True, features=[{"type": "lock-commands"}]),
            T("lock.oficina_cerradura_sala_de_servidores", "Sala de servidores", ancho=True, features=[{"type": "lock-commands"}]),
            T("cover.oficina_porton_estacionamiento", "Portón del estacionamiento", ancho=True, features=[{"type": "cover-open-close"}]),
        ),
        seccion(
            titulo("Ambiente", "mdi:thermometer", "Open space y climatización"),
            {"type": "thermostat", "entity": "climate.oficina_aa_open_space", "name": "Aire acondicionado open space",
             "features": [{"type": "climate-hvac-modes", "hvac_modes": ["cool", "off"]}]},
            T("sensor.oficina_temperatura_open_space", "Temperatura"),
            T("sensor.oficina_humedad_open_space", "Humedad"),
            T("sensor.oficina_co2_open_space", "CO₂"),
            T("sensor.oficina_personas_presentes", "Personas"),
            T("binary_sensor.oficina_sala_de_reuniones_ocupada", "Sala de reuniones"),
            T("sensor.oficina_consumo_electrico", "Consumo"),
        ),
        seccion(
            titulo("Luces", "mdi:lightbulb-group"),
            T("light.oficina_luz_recepcion", "Recepción", features=[{"type": "light-brightness"}]),
            T("light.oficina_luz_open_space", "Open space", features=[{"type": "light-brightness"}]),
            T("light.oficina_luz_sala_de_reuniones", "Reuniones", features=[{"type": "light-brightness"}]),
            T("light.oficina_luz_pasillo", "Pasillo", features=[{"type": "light-brightness"}]),
            T("light.oficina_luz_cartel", "Cartel exterior"),
        ),
        seccion(
            titulo("Salas y cortinas", "mdi:curtains"),
            T("cover.oficina_cortina_sala_de_reuniones", "Cortina de reuniones", ancho=True, features=[{"type": "cover-open-close"}, {"type": "cover-position"}]),
            T("cover.oficina_persiana_open_space", "Persiana open space", ancho=True, features=[{"type": "cover-open-close"}, {"type": "cover-position"}]),
        ),
        seccion(
            titulo("Equipos", "mdi:power-plug"),
            T("switch.oficina_proyector", "Proyector"),
            T("switch.oficina_cafetera", "Cafetera"),
            T("switch.oficina_carteleria_digital", "Cartelería"),
            T("switch.oficina_enchufes_escritorios", "Escritorios"),
        ),
        seccion(
            titulo("Escenas", "mdi:palette"),
            escena("script.demo_oficina_abrir", "Abrir oficina", "mdi:key-variant", "amber"),
            escena("script.demo_oficina_cerrar", "Cerrar oficina", "mdi:lock-check", "red"),
            escena("script.demo_oficina_reunion", "Modo reunión", "mdi:presentation", "purple"),
            escena("script.demo_oficina_ahorro", "Ahorro", "mdi:leaf", "green"),
        ),
    ])
    infra = vista("Infraestructura", "infraestructura", "mdi:server-network", [
        seccion(
            titulo("Energía de respaldo", "mdi:battery-charging-100", "UPS"),
            {"type": "gauge", "entity": "sensor.oficina_ups_carga_de_bateria", "name": "Batería de la UPS", "min": 0, "max": 100,
             "severity": {"green": 50, "yellow": 25, "red": 0}},
            T("sensor.oficina_ups_autonomia", "Autonomía", ancho=True),
            T("sensor.oficina_ups_carga_conectada", "Carga conectada", ancho=True),
            T("binary_sensor.oficina_ups_en_bateria", "Funcionando con batería", ancho=True),
        ),
        seccion(
            titulo("Internet", "mdi:web", "Conexión del edificio"),
            T("binary_sensor.oficina_internet_conectado", "Internet", ancho=True),
            T("sensor.oficina_internet_latencia", "Latencia"),
            T("sensor.oficina_internet_descarga", "Bajada"),
            T("sensor.oficina_internet_subida", "Subida"),
            grafico("Latencia (ms)", ["sensor.oficina_internet_latencia"]),
        ),
        seccion(
            titulo("Sala de servidores", "mdi:server"),
            {"type": "thermostat", "entity": "climate.oficina_aa_sala_de_servidores", "name": "Aire de la sala de servidores"},
            T("sensor.oficina_temperatura_sala_de_servidores", "Temperatura"),
            T("sensor.oficina_humedad_sala_de_servidores", "Humedad"),
            T("sensor.oficina_servidor_cpu", "CPU del servidor"),
            T("sensor.oficina_nas_temperatura_de_discos", "Discos del NAS"),
            T("sensor.oficina_nas_espacio_usado", "Espacio del NAS"),
            T("sensor.oficina_impresora_toner", "Tóner impresora"),
            grafico("Temperatura de la sala de servidores", ["sensor.oficina_temperatura_sala_de_servidores"]),
        ),
    ])
    energia = vista("Energía", "energia", "mdi:lightning-bolt", [
        seccion(
            titulo("Consumo", "mdi:flash", "En vivo y del día"),
            {"type": "gauge", "entity": "sensor.oficina_consumo_electrico", "name": "Potencia ahora", "min": 0, "max": 6000,
             "needle": True, "severity": {"green": 0, "yellow": 3500, "red": 4800}},
            T("sensor.oficina_energia_hoy", "Energía de hoy", "mdi:lightning-bolt-circle", ancho=True),
        ),
        seccion(
            titulo("Evolución", "mdi:chart-line", "Últimos días"),
            grafico("Potencia (promedio por hora)", ["sensor.oficina_consumo_electrico"]),
            grafico("Energía por día", ["sensor.oficina_energia_hoy"], dias=14, tipos=("change",), periodo="day", tipo="bar"),
        ),
        seccion(
            titulo("Ocupación", "mdi:account-group", "Últimos días"),
            grafico("Personas presentes", ["sensor.oficina_personas_presentes"]),
            grafico("CO₂ del open space", ["sensor.oficina_co2_open_space"]),
        ),
    ])
    seguridad = vista("Seguridad", "seguridad", "mdi:shield-home", [
        seccion(
            titulo("Alarma", "mdi:shield-lock"),
            {"type": "alarm-panel", "entity": "alarm_control_panel.oficina_alarma", "name": "Alarma de la oficina", "states": ["arm_home", "arm_away"]},
        ),
        seccion(
            titulo("Sensores", "mdi:motion-sensor"),
            T("binary_sensor.oficina_puerta_de_ingreso", "Puerta de ingreso", ancho=True),
            T("binary_sensor.oficina_puerta_sala_de_servidores", "Puerta sala de servidores", ancho=True),
            T("binary_sensor.oficina_movimiento_recepcion", "Movimiento recepción", ancho=True),
            T("binary_sensor.oficina_humo", "Humo", ancho=True),
            T("binary_sensor.oficina_fuga_de_agua_sala_de_servidores", "Fuga de agua (servidores)", ancho=True),
            T("sensor.oficina_bateria_sensor_puerta", "Batería sensor puerta", ancho=True),
            T("sensor.oficina_bateria_sensor_sala_de_servidores", "Batería sensor servidores", ancho=True),
        ),
        seccion(
            titulo("Actividad reciente", "mdi:history"),
            {"type": "logbook", "hours_to_show": 24, "target": {"entity_id": [
                "binary_sensor.oficina_puerta_de_ingreso", "binary_sensor.oficina_movimiento_recepcion",
                "lock.oficina_cerradura_ingreso", "lock.oficina_cerradura_sala_de_servidores",
                "alarm_control_panel.oficina_alarma", "binary_sensor.oficina_sala_de_reuniones_ocupada"]}},
        ),
    ])
    guardar_paquete(p, paquete)
    guardar_dashboard(p, [inicio, infra, energia, seguridad])
    return {
        "dashboard": {"url_path": "dashboard-oficina", "titulo": "Oficina", "icono": "mdi:office-building", "archivo": "dashboards/oficina.yaml"},
        "vigilar": ["sensor.oficina_temperatura_sala_de_servidores", "sensor.oficina_servidor_cpu", "binary_sensor.oficina_internet_conectado"],
        "ocultar": ["input_boolean.demo_oficina_cerradura_ingreso", "input_boolean.demo_oficina_cerradura_srv",
                    "input_boolean.demo_oficina_inicializado", "switch.oficina_aa_open_space_compresor",
                    "switch.oficina_aa_sala_de_servidores_compresor"],
        "historial": list(HIST),
    }


# ======================================================================================================
#  COMERCIO
# ======================================================================================================
def comercio():
    p = "comercio"
    HIST.clear()
    falla = "{{ is_state('input_boolean.demo_falla_comercio', 'off') }}"
    luces = ["Comercio Luz Vidriera", "Comercio Luz Salón", "Comercio Luz Góndolas", "Comercio Luz Depósito", "Comercio Luz Cartel LED"]
    luces_ids = [eid("light", n) for n in luces]
    potencia = (H + R + "{% set luces = " + repr(luces_ids) + " %}"
                "{{ (2600 + 1300 * cos((h - 17) * 0.2618) + r * 70 + (luces | select('is_state', 'on') | list | count) * 80"
                " + (1100 if is_state('switch.comercio_aa_salon_compresor', 'on') else 0)) | round(0) }}")
    sensores = [
        sensor("Comercio Temperatura Heladera 1", "demo_co_hel1", "°C", onda(3.6, 0.7, 13, 0.25, 1), "temperature", disponible=falla),
        sensor("Comercio Temperatura Heladera 2", "demo_co_hel2", "°C", onda(4.1, 0.6, 14, 0.25, 1), "temperature"),
        sensor("Comercio Temperatura Freezer", "demo_co_frz", "°C", onda(-18.4, 1.2, 14, 0.3, 1), "temperature"),
        sensor("Comercio Temperatura Salón", "demo_co_temp", "°C", onda(23.8, 2.0, 16), "temperature"),
        sensor("Comercio Humedad Salón", "demo_co_hum", "%", onda(50, -6, 16, 1, 0), "humidity"),
        sensor("Comercio Temperatura Depósito", "demo_co_dep", "°C", onda(19.5, 1.8, 15), "temperature"),
        sensor("Comercio Personas en el Local", "demo_co_personas", "personas", onda(6, 9, 18, 0.9, 0, 0), None, icono="mdi:account-group"),
        sensor("Comercio Clientes Hoy", "demo_co_clientes", "clientes", acumulado(7, 6, 17, 1, 0), None, sc="total_increasing", icono="mdi:account-multiple-check"),
        sensor("Comercio Ventas Hoy", "demo_co_ventas", "$", acumulado(3400, 2600, 17, 1, 0), None, sc="total_increasing", icono="mdi:cash-register"),
        sensor("Comercio Ticket Promedio", "demo_co_ticket", "$", onda(12400, 1800, 18, 220, 0), None, icono="mdi:receipt-text"),
        sensor("Comercio Wi-Fi Clientes Conectados", "demo_co_wifi", "dispositivos", onda(7, 9, 18, 0.9, 0, 0), None, icono="mdi:wifi"),
        sensor("Comercio Luminosidad Vidriera", "demo_co_lux", "lx", onda(420, 380, 13, 22, 0, 0), "illuminance"),
        sensor("Comercio Consumo Eléctrico", "demo_co_potencia", "W",
               _con_spec(potencia, tipo="onda", base=2800, amp=1300, pico=17, dec=0, minimo=None), "power"),
        sensor("Comercio Energía Hoy", "demo_co_energia", "kWh", acumulado(2600, 1300, 17), "energy", sc="total_increasing"),
        sensor("Comercio Impresora Fiscal Papel", "demo_co_papel", "%", bateria(58, 70), None, icono="mdi:receipt"),
        sensor("Comercio Batería Sensor Heladera 1", "demo_co_bat_h1", "%", bateria(77), "battery"),
        sensor("Comercio Batería Sensor Freezer", "demo_co_bat_frz", "%", bateria(63), "battery"),
    ]
    binarios = [
        binario("Comercio Puerta de Ingreso", "demo_co_puerta", "door", "{{ 9 <= now().hour < 21 and now().minute % 5 < 1 }}"),
        binario("Comercio Puerta Depósito", "demo_co_puerta_dep", "door", "{{ false }}"),
        binario("Comercio Movimiento Salón", "demo_co_mov", "motion", "{{ 9 <= now().hour < 21 and now().minute % 4 < 2 }}"),
        binario("Comercio Movimiento Depósito", "demo_co_mov_dep", "motion", "{{ now().minute % 23 < 1 }}"),
        binario("Comercio Puerta Heladera 1", "demo_co_hel_puerta", "door", "{{ now().minute % 19 < 1 }}"),
        binario("Comercio Caja Abierta", "demo_co_caja", "opening", "{{ 9 <= now().hour < 21 and now().minute % 6 < 1 }}"),
        binario("Comercio Terminal de Cobro Conectado", "demo_co_pos", "connectivity", "{{ true }}"),
        binario("Comercio Internet Conectado", "demo_co_internet", "connectivity", "{{ true }}"),
        binario("Comercio Humo", "demo_co_humo", "smoke", "{{ false }}"),
    ]
    paquete = {
        "input_boolean": {
            "demo_falla_comercio": {"name": "Demo · Simular falla del sensor de la heladera", "icon": "mdi:alert-circle-outline"},
            "demo_comercio_cerradura_dep": {"name": "Demo · Comercio cerradura depósito", "icon": "mdi:lock", "initial": True},
            "demo_comercio_inicializado": {"name": "Demo · Comercio ya inicializado", "icon": "mdi:check", "initial": False},
        },
        "template": [
            {"sensor": sensores},
            {"binary_sensor": binarios},
            {"light": [luz(luces[0], "demo_co_luz_vid", icono="mdi:storefront-outline"),
                       luz(luces[1], "demo_co_luz_sal", icono="mdi:ceiling-light"),
                       luz(luces[2], "demo_co_luz_gon", icono="mdi:shelf"),
                       luz(luces[3], "demo_co_luz_dep", icono="mdi:warehouse"),
                       luz(luces[4], "demo_co_luz_cartel", atenuable=False, icono="mdi:sign-real-estate")]},
            {"switch": [interruptor("Comercio Música Ambiente", "demo_co_musica", "mdi:speaker"),
                        interruptor("Comercio Cartel Abierto", "demo_co_abierto", "mdi:store-clock"),
                        interruptor("Comercio Cartelería Promociones", "demo_co_promos", "mdi:monitor-shimmer"),
                        interruptor("Comercio Máquina de Café", "demo_co_cafe", "mdi:coffee-maker"),
                        interruptor("Comercio AA Salón Compresor", "demo_co_aa_comp", "mdi:air-conditioner")]},
            {"cover": [persiana("Comercio Cortina Metálica", "demo_co_cortina", "shutter", "mdi:window-shutter"),
                       persiana("Comercio Toldo", "demo_co_toldo", "awning", "mdi:awning-outline")]},
            {"lock": [cerradura("Comercio Cerradura Depósito", "demo_co_cerr", "input_boolean.demo_comercio_cerradura_dep")]},
        ],
        "climate": [termostato("Comercio AA Salón", "demo_co_aa", "switch.comercio_aa_salon_compresor",
                               "sensor.comercio_temperatura_salon", 24)],
        "alarm_control_panel": [alarma("Comercio Alarma", "demo_co_alarma")],
        "script": {
            "demo_comercio_abrir": {"alias": "Abrir el local", "icon": "mdi:store-check", "sequence": [
                acc("alarm_control_panel.alarm_disarm", "alarm_control_panel.comercio_alarma"),
                acc("input_boolean.turn_off", "input_boolean.demo_comercio_cerradura_dep"),
                acc("cover.open_cover", eid("cover", "Comercio Cortina Metálica")),
                acc("light.turn_on", luces_ids, brightness_pct=90),
                acc("switch.turn_on", [eid("switch", "Comercio Música Ambiente"), eid("switch", "Comercio Cartel Abierto"),
                                        eid("switch", "Comercio Cartelería Promociones"), eid("switch", "Comercio Máquina de Café")]),
                acc("climate.turn_on", "climate.comercio_aa_salon"),
            ]},
            "demo_comercio_cerrar": {"alias": "Cerrar el local", "icon": "mdi:store-remove", "sequence": [
                acc("light.turn_off", [luces_ids[1], luces_ids[2], luces_ids[3]]),
                acc("light.turn_on", luces_ids[0], brightness_pct=30),
                acc("switch.turn_off", [eid("switch", "Comercio Música Ambiente"), eid("switch", "Comercio Cartel Abierto"),
                                         eid("switch", "Comercio Cartelería Promociones"), eid("switch", "Comercio Máquina de Café")]),
                acc("cover.close_cover", eid("cover", "Comercio Cortina Metálica")),
                acc("input_boolean.turn_on", "input_boolean.demo_comercio_cerradura_dep"),
                acc("alarm_control_panel.alarm_arm_away", "alarm_control_panel.comercio_alarma"),
            ]},
            "demo_comercio_promo": {"alias": "Promoción en vidriera", "icon": "mdi:sale", "sequence": [
                acc("light.turn_on", [luces_ids[0], luces_ids[4]], brightness_pct=100),
                acc("switch.turn_on", [eid("switch", "Comercio Cartelería Promociones"), eid("switch", "Comercio Música Ambiente")]),
            ]},
            "demo_comercio_limpieza": {"alias": "Modo limpieza", "icon": "mdi:broom", "sequence": [
                acc("light.turn_on", [luces_ids[1], luces_ids[2], luces_ids[3]], brightness_pct=100),
                acc("switch.turn_off", [eid("switch", "Comercio Música Ambiente"), eid("switch", "Comercio Cartelería Promociones")]),
            ]},
            "demo_comercio_inicializar": {"alias": "Demo · Estado inicial del comercio", "icon": "mdi:restart", "sequence": [
                acc("light.turn_on", luces_ids[0], brightness_pct=100),
                acc("light.turn_on", luces_ids[1], brightness_pct=90),
                acc("light.turn_on", luces_ids[2], brightness_pct=80),
                acc("light.turn_off", luces_ids[3]),
                acc("light.turn_on", luces_ids[4]),
                acc("cover.set_cover_position", eid("cover", "Comercio Cortina Metálica"), position=100),
                acc("cover.set_cover_position", eid("cover", "Comercio Toldo"), position=60),
                acc("switch.turn_on", [eid("switch", "Comercio Música Ambiente"), eid("switch", "Comercio Cartel Abierto"),
                                        eid("switch", "Comercio Cartelería Promociones")]),
                acc("switch.turn_off", eid("switch", "Comercio Máquina de Café")),
                acc("climate.set_temperature", "climate.comercio_aa_salon", temperature=24, hvac_mode="cool"),
            ]},
        },
        "automation": [arranque("comercio", "el comercio", "input_boolean.demo_comercio_inicializado")],
    }
    T = tile
    inicio = vista("Inicio", "inicio", "mdi:storefront", [
        seccion(
            titulo("Hoy", "mdi:cash-register", "El día en números"),
            T("sensor.comercio_ventas_hoy", "Ventas de hoy", "mdi:cash-register", ancho=True),
            T("sensor.comercio_clientes_hoy", "Clientes"),
            T("sensor.comercio_ticket_promedio", "Ticket promedio"),
            T("sensor.comercio_personas_en_el_local", "En el local"),
            T("sensor.comercio_wi_fi_clientes_conectados", "Wi-Fi"),
        ),
        seccion(
            titulo("Local", "mdi:store", "Apertura y accesos"),
            T("alarm_control_panel.comercio_alarma", "Alarma", ancho=True, features=[{"type": "alarm-modes", "modes": ["armed_home", "armed_away", "disarmed"]}]),
            T("cover.comercio_cortina_metalica", "Cortina metálica", ancho=True, features=[{"type": "cover-open-close"}, {"type": "cover-position"}]),
            T("cover.comercio_toldo", "Toldo", ancho=True, features=[{"type": "cover-open-close"}]),
            T("lock.comercio_cerradura_deposito", "Depósito", ancho=True, features=[{"type": "lock-commands"}]),
        ),
        seccion(
            titulo("Luces", "mdi:lightbulb-group"),
            T("light.comercio_luz_vidriera", "Vidriera", features=[{"type": "light-brightness"}]),
            T("light.comercio_luz_salon", "Salón", features=[{"type": "light-brightness"}]),
            T("light.comercio_luz_gondolas", "Góndolas", features=[{"type": "light-brightness"}]),
            T("light.comercio_luz_deposito", "Depósito", features=[{"type": "light-brightness"}]),
            T("light.comercio_luz_cartel_led", "Cartel LED"),
        ),
        seccion(
            titulo("Ambiente", "mdi:thermometer"),
            {"type": "thermostat", "entity": "climate.comercio_aa_salon", "name": "Aire acondicionado del salón",
             "features": [{"type": "climate-hvac-modes", "hvac_modes": ["cool", "off"]}]},
            T("sensor.comercio_temperatura_salon", "Salón"),
            T("sensor.comercio_humedad_salon", "Humedad"),
        ),
        seccion(
            titulo("Equipos", "mdi:power-plug"),
            T("switch.comercio_musica_ambiente", "Música"),
            T("switch.comercio_cartel_abierto", "Cartel Abierto"),
            T("switch.comercio_carteleria_promociones", "Promociones"),
            T("switch.comercio_maquina_de_cafe", "Café"),
        ),
        seccion(
            titulo("Escenas", "mdi:palette"),
            escena("script.demo_comercio_abrir", "Abrir local", "mdi:store-check", "green"),
            escena("script.demo_comercio_cerrar", "Cerrar local", "mdi:store-remove", "red"),
            escena("script.demo_comercio_promo", "Promoción", "mdi:sale", "amber"),
            escena("script.demo_comercio_limpieza", "Limpieza", "mdi:broom", "blue"),
        ),
    ])
    ventas = vista("Ventas", "ventas", "mdi:chart-areaspline", [
        seccion(
            titulo("Hoy", "mdi:cash-register"),
            {"type": "gauge", "entity": "sensor.comercio_clientes_hoy", "name": "Clientes de hoy", "min": 0, "max": 300,
             "severity": {"green": 120, "yellow": 60, "red": 0}},
            T("sensor.comercio_ventas_hoy", "Ventas de hoy", "mdi:cash-register", ancho=True),
            T("sensor.comercio_ticket_promedio", "Ticket promedio", ancho=True),
        ),
        seccion(
            titulo("Evolución", "mdi:chart-line", "Últimos días"),
            grafico("Ventas por día ($)", ["sensor.comercio_ventas_hoy"], dias=14, tipos=("change",), periodo="day", tipo="bar"),
            grafico("Clientes por día", ["sensor.comercio_clientes_hoy"], dias=14, tipos=("change",), periodo="day", tipo="bar"),
        ),
        seccion(
            titulo("Movimiento del local", "mdi:account-group"),
            grafico("Personas en el local", ["sensor.comercio_personas_en_el_local"]),
            grafico("Dispositivos Wi-Fi", ["sensor.comercio_wi_fi_clientes_conectados"]),
        ),
    ])
    frio = vista("Cadena de frío", "frio", "mdi:snowflake-thermometer", [
        seccion(
            titulo("Heladeras y freezer", "mdi:fridge-industrial", "Control de temperatura"),
            T("sensor.comercio_temperatura_heladera_1", "Heladera 1", "mdi:fridge", ancho=True),
            T("sensor.comercio_temperatura_heladera_2", "Heladera 2", "mdi:fridge", ancho=True),
            T("sensor.comercio_temperatura_freezer", "Freezer", "mdi:fridge-top", ancho=True),
            T("binary_sensor.comercio_puerta_heladera_1", "Puerta heladera 1", ancho=True),
        ),
        seccion(
            titulo("Historial", "mdi:chart-line", "Últimos días"),
            grafico("Heladeras (°C)", ["sensor.comercio_temperatura_heladera_1", "sensor.comercio_temperatura_heladera_2"]),
            grafico("Freezer (°C)", ["sensor.comercio_temperatura_freezer"]),
        ),
        seccion(
            titulo("Sensores", "mdi:battery-heart-variant"),
            T("sensor.comercio_bateria_sensor_heladera_1", "Batería sensor heladera", ancho=True),
            T("sensor.comercio_bateria_sensor_freezer", "Batería sensor freezer", ancho=True),
            T("sensor.comercio_temperatura_deposito", "Depósito", ancho=True),
        ),
    ])
    seguridad = vista("Seguridad", "seguridad", "mdi:shield-home", [
        seccion(
            titulo("Alarma", "mdi:shield-lock"),
            {"type": "alarm-panel", "entity": "alarm_control_panel.comercio_alarma", "name": "Alarma del local", "states": ["arm_home", "arm_away"]},
            T("sensor.comercio_consumo_electrico", "Consumo ahora", "mdi:flash", ancho=True),
            T("sensor.comercio_energia_hoy", "Energía de hoy", ancho=True),
        ),
        seccion(
            titulo("Sensores y cobro", "mdi:motion-sensor"),
            T("binary_sensor.comercio_puerta_de_ingreso", "Puerta de ingreso", ancho=True),
            T("binary_sensor.comercio_puerta_deposito", "Puerta del depósito", ancho=True),
            T("binary_sensor.comercio_movimiento_salon", "Movimiento salón", ancho=True),
            T("binary_sensor.comercio_movimiento_deposito", "Movimiento depósito", ancho=True),
            T("binary_sensor.comercio_caja_abierta", "Caja registradora", ancho=True),
            T("binary_sensor.comercio_terminal_de_cobro_conectado", "Terminal de cobro", ancho=True),
            T("binary_sensor.comercio_internet_conectado", "Internet", ancho=True),
            T("sensor.comercio_impresora_fiscal_papel", "Papel impresora fiscal", ancho=True),
        ),
        seccion(
            titulo("Actividad reciente", "mdi:history"),
            {"type": "logbook", "hours_to_show": 24, "target": {"entity_id": [
                "binary_sensor.comercio_puerta_de_ingreso", "binary_sensor.comercio_caja_abierta",
                "binary_sensor.comercio_movimiento_deposito", "lock.comercio_cerradura_deposito",
                "alarm_control_panel.comercio_alarma", "cover.comercio_cortina_metalica"]}},
        ),
    ])
    guardar_paquete(p, paquete)
    guardar_dashboard(p, [inicio, ventas, frio, seguridad])
    return {
        "dashboard": {"url_path": "dashboard-comercio", "titulo": "Comercio", "icono": "mdi:storefront", "archivo": "dashboards/comercio.yaml"},
        "vigilar": ["sensor.comercio_temperatura_heladera_1", "sensor.comercio_temperatura_freezer", "binary_sensor.comercio_terminal_de_cobro_conectado"],
        "ocultar": ["input_boolean.demo_comercio_cerradura_dep", "input_boolean.demo_comercio_inicializado",
                    "switch.comercio_aa_salon_compresor"],
        "historial": list(HIST),
    }


RUBROS = {"hogar": hogar, "oficina": oficina, "comercio": comercio}

if __name__ == "__main__":
    manifiesto = {"rubros": {}, "usuarios": {"juan": "hogar", "pedro": "oficina", "maria": "comercio"}}
    for nombre, fn in RUBROS.items():
        manifiesto["rubros"][nombre] = fn()
    with open(os.path.join(RAIZ, "manifest.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifiesto, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("OK ->", os.path.normpath(RAIZ))
