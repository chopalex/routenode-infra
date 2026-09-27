FROM python:3.12-alpine
RUN apk add --no-cache docker-cli
WORKDIR /app
COPY service_exporter.py geoip_names.py awg-peers.json /app/
# Mount .env at runtime: ./exporters/.env:/app/.env:ro
EXPOSE 9101
CMD ["python3", "/app/service_exporter.py"]
