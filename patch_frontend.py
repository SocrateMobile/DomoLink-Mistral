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
            <button class="btn btn-secondary" id="btn-toggle-ignored">
"""
content = content.replace("""          <div style="display: flex; gap: 8px;">
            <button class="btn btn-warning" id="btn-repair-all" ${autoFixCount === 0 || this._isApplying ? "disabled" : ""}>
              ⚡ Corriger Tout (All Auto: ${autoFixCount})
            </button>
            <button class="btn btn-secondary" id="btn-toggle-ignored">""", btn_html)

# Add event listener
listener_html = """
      const btnAll = this.shadowRoot.getElementById("btn-repair-all");
      if (btnAll) btnAll.addEventListener("click", () => this._handleApplyAll());

      const btnRollback = this.shadowRoot.getElementById("btn-rollback");
      if (btnRollback) btnRollback.addEventListener("click", () => this._handleRollback());
"""
content = re.sub(r'      const btnAll = this\.shadowRoot\.getElementById\("btn-repair-all"\);\n      if \(btnAll\) btnAll\.addEventListener\("click", \(\) => this\._handleApplyAll\(\)\);\n', listener_html, content)

# Add _handleRollback function
handler_html = """
  async _handleApplyAll() {
"""
rollback_func = """
  async _handleRollback() {
    if (!confirm("Voulez-vous vraiment annuler la dernière modification YAML effectuée par Mistral ? Le fichier sauvegardé (.bak) écrasera la version actuelle.")) return;
    this._showToast("Restauration en cours...", "info");
    try {
      const response = await this.hass.callService("domolink_mistral", "rollback_latest_fix");
      if (response && response.success) {
        this._showToast(response.message || "Restauration effectuée avec succès !", "success");
      } else {
        this._showToast(response?.reason || "Échec de la restauration.", "error");
      }
    } catch (err) {
      this._showToast("Erreur lors du rollback : " + err.message, "error");
    }
  }

  async _handleApplyAll() {
"""
content = content.replace(handler_html, rollback_func)

with open("custom_components/domolink_mistral/frontend/domolink-mistral-panel.js", "w") as f:
    f.write(content)
