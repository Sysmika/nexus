#!/usr/bin/with-contenv bashio
bashio::log.info "Nexus by Orion · instalador"
python3 /instalar.py || bashio::log.warning "El instalador terminó con errores (ver arriba)"
# Modo demo (solo si la opción modo_demo está activa): corre aparte para no demorar el acceso remoto.
python3 /demo.py &
# Replicator (stock y compras): se instala una sola vez por equipo; corre aparte porque la primera vez
# construye la imagen y puede llevar varios minutos.
python3 /replicator.py &
# Orion SysGestion: deja el repositorio en la tienda sin instalar; lo instala solo si se cargó sysgestion_url.
python3 /sysgestion.py &
# Acceso remoto (Tailscale): solo hace algo si el paquete de Orion lo pidió; si sí, queda corriendo.
if [ -f /data/nexus_remoto.json ]; then
  exec python3 /remoto.py
fi
python3 /remoto.py
# Sin acceso remoto: esperar a que terminen los procesos de fondo antes de cerrar el add-on.
wait
