import re

with open("custom_components/domolink_mistral/mistral_api.py", "r") as f:
    content = f.read()

content = content.replace('return {"success": False, "error": str(e)}', 'return {"success": False, "response_text": f"Désolé, une erreur est survenue: {e}", "service_calls": []}')

with open("custom_components/domolink_mistral/mistral_api.py", "w") as f:
    f.write(content)
