"""Server-side Meta Conversions API sender for the dashboard (Purchase event)."""
from __future__ import annotations
import hashlib
import logging
import time
import requests

logger = logging.getLogger(__name__)


def _sha256(v: str) -> str:
    return hashlib.sha256(v.strip().lower().encode("utf-8")).hexdigest()


def send_event(meta_config: dict, *, email: str, event_name: str, event_id: str,
               user_meta: dict | None = None, custom_data: dict | None = None,
               action_source: str = "website", event_source_url: str | None = None) -> dict | None:
    """Best-effort CAPI send. Returns the send outcome
    ({"sent_ok","http_status","events_received","fbtrace_id"} or {"sent_ok":False,"error"}),
    or None when meta is disabled/unconfigured (nothing sent). Never raises."""
    if not meta_config or not meta_config.get("enabled"):
        return None
    pixel_id = meta_config.get("pixel_id")
    token = meta_config.get("capi_access_token")
    if not pixel_id or not token:
        return None
    user_meta = user_meta or {}
    user_data = {"em": _sha256(email), "external_id": _sha256(email)}
    for src, dst in (("fbp", "fbp"), ("fbc", "fbc"),
                     ("client_ip", "client_ip_address"),
                     ("client_user_agent", "client_user_agent")):
        if user_meta.get(src):
            user_data[dst] = user_meta[src]
    event = {"event_name": event_name, "event_time": int(time.time()),
             "event_id": event_id, "action_source": action_source, "user_data": user_data}
    if event_source_url:
        event["event_source_url"] = event_source_url
    if custom_data:
        event["custom_data"] = custom_data
    payload = {"data": [event]}
    if meta_config.get("test_event_code"):
        payload["test_event_code"] = meta_config["test_event_code"]
    ver = meta_config.get("api_version", "v20.0")
    url = f"https://graph.facebook.com/{ver}/{pixel_id}/events?access_token={token}"
    try:
        resp = requests.post(url, json=payload, timeout=3)
        body = {}
        try:
            body = resp.json()
        except Exception:
            pass
        return {"sent_ok": bool(resp.ok), "http_status": resp.status_code,
                "events_received": body.get("events_received"),
                "fbtrace_id": body.get("fbtrace_id")}
    except Exception as e:
        logger.warning("Meta CAPI (dashboard) send failed (swallowed)", exc_info=True)
        return {"sent_ok": False, "error": str(e)}
