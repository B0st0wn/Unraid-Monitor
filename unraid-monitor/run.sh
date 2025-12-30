#!/usr/bin/with-contenv bashio

bashio::log.info "Starting Unraid Monitor..."

# MQTT Auto-discovery
MQTT_AUTO_DISCOVER=$(bashio::config 'mqtt.auto_discover')

if [ "$MQTT_AUTO_DISCOVER" = "true" ]; then
    bashio::log.info "MQTT auto-discovery enabled"
    if bashio::services.available "mqtt"; then
        export MQTT_HOST=$(bashio::services "mqtt" "host")
        export MQTT_PORT=$(bashio::services "mqtt" "port")
        export MQTT_USER=$(bashio::services "mqtt" "username")
        export MQTT_PASS=$(bashio::services "mqtt" "password")
        bashio::log.info "MQTT auto-discovered: ${MQTT_HOST}:${MQTT_PORT}"
    else
        bashio::log.warning "MQTT service not found, using manual config"
        export MQTT_HOST=$(bashio::config 'mqtt.host')
        export MQTT_PORT=$(bashio::config 'mqtt.port')
        export MQTT_USER=$(bashio::config 'mqtt.username')
        export MQTT_PASS=$(bashio::config 'mqtt.password')
    fi
else
    bashio::log.info "Using manual MQTT configuration"
    export MQTT_HOST=$(bashio::config 'mqtt.host')
    export MQTT_PORT=$(bashio::config 'mqtt.port')
    export MQTT_USER=$(bashio::config 'mqtt.username')
    export MQTT_PASS=$(bashio::config 'mqtt.password')
fi

# Convert options.json to config.yaml
bashio::log.info "Converting add-on options to config format..."
python3 /opt/app/create_config.py

# Set environment variables
export USE_GRAPHQL=$(bashio::config 'use_graphql')
export DATA_PATH=/data

# Start application
bashio::log.info "Starting Unraid monitoring service..."
cd /opt
exec python3 -m app.main
