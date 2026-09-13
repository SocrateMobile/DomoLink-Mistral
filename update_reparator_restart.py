import re

with open("custom_components/domolink_mistral/reparator.py", "r") as f:
    content = f.read()

intercept = """        if not domain or not service:
            skipped += 1
            continue

        if domain == "homeassistant" and service == "restart":
            if hass.services.has_service("restart_ha", "start_process"):
                domain = "restart_ha"
                service = "start_process"
                data = {"action": "quick_restart"}
"""

content = re.sub(r'        if not domain or not service:\n            skipped \+= 1\n            continue\n', intercept, content)

with open("custom_components/domolink_mistral/reparator.py", "w") as f:
    f.write(content)
