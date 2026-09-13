import re

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "r") as f:
    content = f.read()

btn_html = """
          <div style="display: flex; gap: 8px;">
            <button class="btn btn-warning" id="btn-repair-all" ${autoFixCount === 0 || this._isApplying ? "disabled" : ""}>
              ⚡ Corriger Tout (All Auto: ${autoFixCount})
            </button>
            <button class="btn btn-danger" id="btn-rollback" title="Annuler la dernière modification YAML">
              ⏪ Rollback
            </button>
"""

content = content.replace("""          <div style="display: flex; gap: 8px;">
            <button class="btn btn-warning" id="btn-repair-all" ${autoFixCount === 0 || this._isApplying ? "disabled" : ""}>
              ⚡ Corriger Tout (All Auto: ${autoFixCount})
            </button>""", btn_html)

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "w") as f:
    f.write(content)
