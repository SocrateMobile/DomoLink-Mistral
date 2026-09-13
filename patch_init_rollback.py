import re

with open("custom_components/domolink_mistral/__init__.py", "r") as f:
    content = f.read()

handler = """
    async def handle_rollback(call: ServiceCall):
        from .reparator import rollback_latest_fix
        res = await rollback_latest_fix(hass)
        if res.get("success"):
            # Update frontend to trigger a reload or show success
            hass.bus.async_fire("domolink_mistral_rollback_success", res)
        else:
            hass.bus.async_fire("domolink_mistral_rollback_failed", res)
        return res

    # ── Enregistrement des services ──
    hass.services.async_register(DOMAIN, "rollback_latest_fix", handle_rollback)
"""

content = content.replace("    # ── Enregistrement des services ──", handler)

with open("custom_components/domolink_mistral/__init__.py", "w") as f:
    f.write(content)
