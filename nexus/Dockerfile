FROM ghcr.io/home-assistant/base:3.24

RUN apk add --no-cache python3 py3-websockets tailscale

COPY run.sh instalar.py remoto.py demo.py /
COPY payload /payload
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]
