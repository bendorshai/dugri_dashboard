#!/bin/bash
mkdir -p config
printf '%s' "$CONFIG2_JSON" > config/config.json
python main.py
