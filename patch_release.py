import re

with open("scripts/release.py", "r") as f:
    content = f.read()

content = content.replace('REPO_NAME = "Restart-HA"', 'REPO_NAME = "DomoLink-Mistral"')
content = content.replace('custom_components", "restart_ha"', 'custom_components", "domolink_mistral"')
content = content.replace('Restart-HA', 'DomoLink-Mistral')
content = content.replace('Restart HA', 'DomoLink-Mistral IA')

with open("scripts/release.py", "w") as f:
    f.write(content)
