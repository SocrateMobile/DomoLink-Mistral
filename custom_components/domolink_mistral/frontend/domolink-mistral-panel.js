import {
  LitElement,
  html,
  css,
} from "https://unpkg.com/lit-element@2.4.0/lit-element.js?module";

class DomolinkMistralPanel extends LitElement {
  static get properties() {
    return {
      hass: { type: Object },
      narrow: { type: Boolean },
      route: { type: Object },
      panel: { type: Object },
      issues: { type: Array },
      selectedIssue: { type: Object },
    };
  }

  constructor() {
    super();
    // Données fictives pour tester le design de l'interface
    this.issues = [
      {
        id: "demo_1",
        title: "Test de connexion Mistral",
        severity: "low",
        description: "Ceci est une fausse erreur pour tester l'interface. Elle simule ce que l'IA va renvoyer.",
        manual_fix: "1. Allez dans les paramètres.\n2. Cliquez sur ignorer pour tester.",
        auto_fix_script: "[]"
      }
    ];
    this.selectedIssue = null;
  }

  static get styles() {
    return css`
      :host {
        display: block;
        padding: 16px;
        background-color: var(--primary-background-color);
        height: 100vh;
        overflow: auto;
      }
      .header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-bottom: 24px;
      }
      .card {
        background: var(--card-background-color, #fff);
        border-radius: 8px;
        padding: 16px;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        margin-bottom: 16px;
        color: var(--primary-text-color);
      }
      .buttons {
        display: flex;
        gap: 8px;
        margin-top: 16px;
      }
      button {
        padding: 8px 16px;
        border: none;
        border-radius: 4px;
        cursor: pointer;
        font-weight: bold;
        background-color: var(--primary-color);
        color: var(--text-primary-color, white);
      }
      button.ignore { background-color: var(--secondary-text-color); }
      button.manual { background-color: var(--info-color, #03a9f4); }
      button.auto { background-color: var(--warning-color, #ff9800); }
      button.allauto { background-color: var(--error-color, #f44336); }
      
      /* Fenêtre en surimpression (modal) pour le mode Manuel */
      .modal {
        position: fixed;
        top: 20px;
        right: 20px;
        width: 350px;
        background: var(--card-background-color, #fff);
        border: 2px solid var(--primary-color);
        padding: 16px;
        border-radius: 8px;
        z-index: 100;
        box-shadow: 0 4px 8px rgba(0,0,0,0.2);
        color: var(--primary-text-color);
      }
    `;
  }

  render() {
    return html`
      <div class="header">
        <h1>DomoLink-Mistral</h1>
        <button @click="${this.analyzeNow}">Lancer l'analyse (Live)</button>
      </div>

      <div class="issues-list">
        ${this.issues.map(
          (issue) => html`
            <div class="card">
              <h3>${issue.title} <span style="font-size: 12px; color: gray;">(${issue.severity})</span></h3>
              <p>${issue.description}</p>
              <div class="buttons">
                <button class="ignore" @click="${() => this.ignoreIssue(issue.id)}">Ignorer</button>
                <button class="manual" @click="${() => this.showManual(issue)}">Manuel (Détacher)</button>
                <button class="auto" @click="${() => this.applyAuto(issue)}">Automatique</button>
              </div>
            </div>
          `
        )}
      </div>

      <div style="margin-top: 40px; text-align: center;">
        <button class="allauto" @click="${this.applyAllAuto}">All Auto (Sauvegarder et tout corriger)</button>
      </div>

      ${this.selectedIssue
        ? html`
            <div class="modal">
              <h3>Guide Pas-à-Pas</h3>
              <p style="white-space: pre-wrap;">${this.selectedIssue.manual_fix}</p>
              <button @click="${() => { this.selectedIssue = null; }}" style="margin-top: 16px;">Fermer</button>
            </div>
          `
        : ""}
    `;
  }

  analyzeNow() {
    this.hass.callService("domolink_mistral", "analyze_now", {});
    alert("Analyse lancée en arrière-plan !");
  }

  ignoreIssue(id) {
    alert("Problème " + id + " ignoré.");
  }

  showManual(issue) {
    this.selectedIssue = issue;
  }

  applyAuto(issue) {
    if (confirm("Une sauvegarde va être lancée, puis le correctif sera appliqué. Continuer ?")) {
      this.hass.callService("domolink_mistral", "apply_fix", { fix_script: issue.auto_fix_script });
    }
  }

  applyAllAuto() {
    if (confirm("Voulez-vous vraiment corriger toutes les erreurs affichées ? Une sauvegarde sera effectuée au préalable.")) {
      alert("Mode All Auto déclenché.");
    }
  }
}

customElements.define("domolink-mistral-panel", DomolinkMistralPanel);
