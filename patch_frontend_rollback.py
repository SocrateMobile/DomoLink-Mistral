import re

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "r") as f:
    content = f.read()

# Insert after btnRepairAll listener
insert_html = """
    // Rollback
    const btnRollback = root.getElementById("btn-rollback");
    if (btnRollback) {
      btnRollback.addEventListener("click", async () => {
        if (!confirm("Voulez-vous annuler la dernière modification ? Le backup sera restauré.")) return;
        this._showToast("Restauration en cours...", "info");
        try {
          const response = await this.hass.callService("domolink_mistral", "rollback_latest_fix");
          if (response) {
            this._showToast("Restauration effectuée avec succès !", "success");
          }
        } catch (err) {
          this._showToast("Erreur lors du rollback.", "error");
        }
      });
    }
"""

content = re.sub(r'(    const btnRepairAll = root\.getElementById\("btn-repair-all"\);\n    if \(btnRepairAll\) \{\n      btnRepairAll\.addEventListener\("click", \(\) => \{\n        this\._applyAllAutoFixes\(\);\n      \}\);\n    \})', r'\1\n' + insert_html, content)

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "w") as f:
    f.write(content)
