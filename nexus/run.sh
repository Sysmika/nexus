#!/usr/bin/with-contenv bashio
bashio::log.info "Nexus by Orion · instalador"
python3 /instalar.py || bashio::log.warning "El instalador terminó con errores (ver arriba)"
# Acceso remoto (Tailscale): solo hace algo si el paquete de Orion lo pidió; si sí, queda corriendo.
exec python3 /remoto.py
