import re
with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "r") as f:
    content = f.read()

# Replace the duplicated button
dup = """            <button class="btn btn-danger" id="btn-rollback" title="Annuler la dernière modification YAML">
              ⏪ Rollback
            </button>
            <button class="btn btn-danger" id="btn-rollback" title="Annuler la dernière modification YAML">
              ⏪ Rollback
            </button>"""
            
fixed = """            <button class="btn btn-danger" id="btn-rollback" title="Annuler la dernière modification YAML">
              ⏪ Rollback
            </button>"""

content = content.replace(dup, fixed)

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "w") as f:
    f.write(content)
