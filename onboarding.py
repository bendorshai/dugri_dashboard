"""Legacy onboarding blueprint — redirects all old step URLs to landing page."""
from __future__ import annotations

from flask import Blueprint, redirect, url_for

onboarding_bp = Blueprint("onboarding", __name__, url_prefix="/onboarding")


@onboarding_bp.route("/step/<int:step_num>", methods=["GET", "POST"])
def step(step_num: int):
    return redirect(url_for("landing"))
