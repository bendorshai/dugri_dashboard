#!/bin/bash
mkdir -p config
printf '%s' "$DASHBOARD_CONFIG_JSON" > config/config.json
python app.py
