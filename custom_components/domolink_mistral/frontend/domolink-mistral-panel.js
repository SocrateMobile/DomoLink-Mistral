/**
 * DomoLink-Mistral — Panneau Frontend pour Home Assistant
 *
 * Fonctionnalités :
 * - Onglet 1 : Diagnostic & Audit complet (Logs, YAML, !includes, ESPHome, Blueprints, Entités)
 * - Onglet 2 : Générateur d'Automations IA en langage naturel ("Prompt to Automation")
 * - Diff visuel Avant/Après (rouge/vert) pour les modifications de fichiers YAML
 * - Modal déplaçable (draggable) pour le guide pas-à-pas manuel
 * - Boîtes de confirmation sécurisées avec copies de sauvegarde .bak
 * - 100% Vanilla JS sans aucune dépendance externe
 */

class DomolinkMistralPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._activeTab = "audit"; // "audit" ou "generator"
    this._issues = [];
    this._ignoredIssues = [];
    this._selectedIssue = null;
    this._isAnalyzing = false;
    this._isApplying = false;
    this._isGenerating = false;
    this._lastAnalysis = null;
    this._currentStatus = "En attente";
    this._showIgnored = false;
    this._confirmData = null; // { title, message, actions, onConfirm }
    this._initialized = false;

    // État du générateur d'automation
    this._genPrompt = "";
    this._generatedAutomation = null; // { title, description, yaml, explanation }

    // Drag state pour la modal manuelle
    this._dragOffset = { x: 0, y: 0 };
    this._modalPos = { x: null, y: null };
    this._isDragging = false;
  }

  set hass(hass) {
    this._hass = hass;
    const changed = this._updateFromSensor();
    if (!this._initialized || changed) {
      this._initialized = true;
      this._render();
    }
  }

  _updateFromSensor() {
    if (!this._hass) return false;

    const entityId = Object.keys(this._hass.states).find(
      (id) => id.startsWith("sensor.") && id.includes("domolink") && id.includes("probleme")
    ) || Object.keys(this._hass.states).find(
      (id) => id.startsWith("sensor.") && id.includes("domolink")
    );

    if (entityId && this._hass.states[entityId]) {
      const stateObj = this._hass.states[entityId];
      const attrs = stateObj.attributes || {};

      const newLast = attrs.last_analysis || null;
      const newStatus = attrs.current_status || "En attente";
      const newIssues = attrs.issues || [];
      const newIgnored = attrs.ignored_issues || [];

      const changed = (
        newLast !== this._lastAnalysis ||
        newStatus !== this._currentStatus ||
        newIssues.length !== this._issues.length ||
        newIgnored.length !== this._ignoredIssues.length
      );

      this._issues = newIssues;
      this._ignoredIssues = newIgnored;
      this._lastAnalysis = newLast;
      this._currentStatus = newStatus;

      // Arrêter les spinners si l'action est terminée ou en erreur
      if (this._isAnalyzing) {
        if (newStatus.includes("terminée") || newStatus.includes("Erreur") || newStatus.includes("✅")) {
          this._isAnalyzing = false;
        }
      }
      if (this._isApplying) {
        if (!newStatus.startsWith("⏳")) {
          this._isApplying = false;
        }
      }
      if (this._isGenerating) {
        if (newStatus.includes("générée") || newStatus.includes("Échec") || newStatus.includes("✅")) {
          this._isGenerating = false;
        }
      }

      return changed;
    }
    return false;
  }

  _severityColor(severity) {
    switch (severity) {
      case "high": return "#f44336";
      case "medium": return "#ff9800";
      case "low": return "#4caf50";
      default: return "#9e9e9e";
    }
  }

  _severityLabel(severity) {
    switch (severity) {
      case "high": return "🔴 Critique";
      case "medium": return "🟠 Moyen";
      case "low": return "🟢 Faible";
      default: return severity;
    }
  }

  _categoryIcon(category) {
    switch (category) {
      case "yaml_syntax": return "📑 Syntaxe YAML";
      case "esphome": return "⚡ ESPHome Builder";
      case "blueprint": return "📘 Blueprint";
      case "log_error": return "📜 Erreur de log";
      case "integration": return "🔌 Intégration";
      case "entity": return "🏷️ Entité orpheline";
      case "automation": return "⚡ Automation";
      case "script": return "📝 Script";
      case "optimization": return "🚀 Optimisation";
      case "best_practice": return "💡 Bonne pratique";
      default: return category || "";
    }
  }

  _timeAgo(isoString) {
    if (!isoString) return "Jamais";
    const diff = Math.floor((Date.now() - new Date(isoString).getTime()) / 1000);
    if (diff < 60) return "Il y a quelques secondes";
    if (diff < 3600) return `Il y a ${Math.floor(diff / 60)} min`;
    if (diff < 86400) return `Il y a ${Math.floor(diff / 3600)}h`;
    return `Il y a ${Math.floor(diff / 86400)} jour(s)`;
  }

  _render() {
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>
        :host {
          display: block;
          padding: 24px;
          font-family: var(--paper-font-body1_-_font-family, 'Roboto', sans-serif);
          background: var(--primary-background-color, #fafafa);
          color: var(--primary-text-color, #212121);
          min-height: 100vh;
          box-sizing: border-box;
        }

        .header {
          display: flex; align-items: center; justify-content: space-between;
          flex-wrap: wrap; gap: 12px; margin-bottom: 20px;
        }
        .header h1 { margin: 0; font-size: 1.5em; }
        .header-info { font-size: 0.85em; color: var(--secondary-text-color, #757575); }

        /* ── Tabs Navigation ── */
        .tabs-nav {
          display: flex; gap: 8px; margin-bottom: 24px;
          border-bottom: 1px solid var(--divider-color, #e0e0e0);
          padding-bottom: 8px;
        }
        .tab-btn {
          padding: 10px 18px; border: none; border-radius: 8px;
          cursor: pointer; font-weight: 600; font-size: 0.95em;
          background: transparent; color: var(--secondary-text-color, #757575);
          transition: all 0.2s;
        }
        .tab-btn:hover { background: rgba(0,0,0,0.05); color: var(--primary-text-color); }
        .tab-btn.active {
          background: var(--primary-color, #03a9f4);
          color: white;
          box-shadow: 0 2px 6px rgba(3, 169, 244, 0.3);
        }

        .btn {
          padding: 10px 20px; border: none; border-radius: 8px;
          cursor: pointer; font-weight: 600; font-size: 0.9em;
          color: white; transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.85; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-primary { background: var(--primary-color, #03a9f4); }
        .btn-success { background: #4caf50; }
        .btn-ignore { background: var(--secondary-text-color, #9e9e9e); }
        .btn-manual { background: var(--info-color, #2196f3); }
        .btn-auto { background: var(--warning-color, #ff9800); }
        .btn-allauto { background: var(--error-color, #f44336); }
        .btn-small { padding: 6px 12px; font-size: 0.8em; }

        .card {
          background: var(--card-background-color, #fff);
          border-radius: 12px; padding: 20px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.08);
          margin-bottom: 16px; transition: box-shadow 0.2s;
        }
        .card:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.12); }

        .severity-border { border-left: 5px solid; padding-left: 16px; }

        .badge {
          display: inline-block; padding: 2px 10px; border-radius: 12px;
          font-size: 0.75em; font-weight: 700; color: white; margin-left: 8px;
        }

        .badge-category {
          background: rgba(150, 150, 150, 0.2);
          color: var(--primary-text-color, #333);
          border: 1px solid rgba(150, 150, 150, 0.3);
        }

        .stats-bar {
          display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 20px;
        }
        .stat-chip {
          padding: 8px 14px; border-radius: 8px; font-weight: 600; font-size: 0.85em;
          background: var(--card-background-color, #fff);
          box-shadow: 0 1px 4px rgba(0,0,0,0.08);
          display: flex; align-items: center; gap: 6px;
        }

        .card-title { margin: 0 0 8px 0; font-size: 1.1em; display: flex; align-items: center; flex-wrap: wrap; gap: 6px; }
        .card-desc { margin: 0 0 16px 0; line-height: 1.5; color: var(--secondary-text-color, #616161); }
        .buttons { display: flex; gap: 8px; flex-wrap: wrap; }

        .spinner {
          display: inline-block; width: 20px; height: 20px;
          border: 3px solid rgba(255,255,255,0.3);
          border-top: 3px solid white;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
          vertical-align: middle; margin-right: 8px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .loading-overlay {
          text-align: center; padding: 60px 20px;
          color: var(--secondary-text-color);
        }
        .loading-overlay .big-spinner {
          width: 48px; height: 48px; margin: 0 auto 20px;
          border: 4px solid var(--divider-color, #e0e0e0);
          border-top: 4px solid var(--primary-color, #03a9f4);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        .empty-state {
          text-align: center; padding: 60px 20px;
          font-size: 1.2em;
          color: var(--secondary-text-color);
        }

        .section-toggle {
          cursor: pointer; padding: 12px 0; font-weight: 600;
          color: var(--secondary-text-color); user-select: none;
          border-top: 1px solid var(--divider-color, #e0e0e0);
          margin-top: 24px;
        }
        .section-toggle:hover { color: var(--primary-text-color); }

        .ignored-section .card { opacity: 0.6; }
        .ignored-badge { background: var(--secondary-text-color, #9e9e9e); }

        .footer { margin-top: 32px; text-align: center; }

        /* ── Modal déplaçable ── */
        .modal {
          position: fixed; width: 440px; max-height: 80vh;
          background: var(--card-background-color, #fff);
          border: 2px solid var(--primary-color, #03a9f4);
          border-radius: 12px; z-index: 100;
          box-shadow: 0 8px 32px rgba(0,0,0,0.25);
          color: var(--primary-text-color);
          overflow: hidden;
          display: flex; flex-direction: column;
        }
        .modal-header {
          padding: 12px 16px; cursor: grab;
          background: var(--primary-color, #03a9f4); color: white;
          font-weight: 700; display: flex; justify-content: space-between; align-items: center;
          user-select: none;
        }
        .modal-header:active { cursor: grabbing; }
        .modal-body { padding: 16px; overflow-y: auto; flex: 1; line-height: 1.6; white-space: pre-wrap; font-size: 0.9em; }
        .modal-close { background: none; border: none; color: white; font-size: 1.4em; cursor: pointer; padding: 0 4px; }

        /* ── Confirmation dialog avec Diff visuel ── */
        .confirm-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.65); z-index: 300;
          display: flex; align-items: center; justify-content: center;
        }
        .confirm-box {
          background: var(--card-background-color, #fff); padding: 24px;
          border-radius: 12px; max-width: 550px; width: 92%;
          max-height: 85vh; overflow-y: auto;
          box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        }
        .confirm-box h3 { margin: 0 0 12px 0; font-size: 1.2em; color: var(--primary-text-color); }
        .confirm-box p { margin: 0 0 16px 0; line-height: 1.5; color: var(--secondary-text-color); font-size: 0.95em; }
        .confirm-buttons { display: flex; gap: 12px; justify-content: flex-end; margin-top: 20px; }

        /* ── Visual Diff Styles ── */
        .diff-container {
          background: var(--primary-background-color, #1e1e1e);
          border: 1px solid var(--divider-color, #444);
          border-radius: 8px; padding: 12px; margin: 12px 0;
          font-family: monospace; font-size: 0.85em; overflow-x: auto;
        }
        .diff-file-label {
          font-weight: 700; color: var(--primary-color, #03a9f4); margin-bottom: 8px;
        }
        .diff-line-remove {
          background: rgba(244, 67, 54, 0.15); color: #f44336;
          padding: 4px 8px; border-left: 3px solid #f44336; margin-bottom: 4px;
          white-space: pre-wrap; word-break: break-all;
        }
        .diff-line-add {
          background: rgba(76, 175, 80, 0.15); color: #4caf50;
          padding: 4px 8px; border-left: 3px solid #4caf50;
          white-space: pre-wrap; word-break: break-all;
        }
        .service-call-box {
          background: rgba(3, 169, 244, 0.1); border-left: 3px solid var(--primary-color, #03a9f4);
          padding: 8px 12px; margin: 8px 0; font-family: monospace; font-size: 0.85em;
        }

        /* ── Generator Tab Styles ── */
        .gen-container { max-width: 800px; margin: 0 auto; }
        .gen-textarea {
          width: 100%; min-height: 100px; padding: 14px;
          border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff); color: var(--primary-text-color, #212121);
          font-family: inherit; font-size: 1em; resize: vertical; box-sizing: border-box;
          margin-bottom: 12px;
        }
        .gen-textarea:focus { outline: 2px solid var(--primary-color, #03a9f4); }
        .chips-container { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
        .chip {
          background: rgba(3, 169, 244, 0.1); color: var(--primary-color, #03a9f4);
          border: 1px solid rgba(3, 169, 244, 0.3); border-radius: 16px;
          padding: 6px 12px; font-size: 0.8em; font-weight: 600; cursor: pointer;
          transition: all 0.2s;
        }
        .chip:hover { background: var(--primary-color, #03a9f4); color: white; }

        .yaml-code-block {
          background: #1e1e1e; color: #d4d4d4; padding: 16px;
          border-radius: 8px; font-family: monospace; font-size: 0.9em;
          line-height: 1.5; overflow-x: auto; white-space: pre;
          margin: 16px 0; border: 1px solid #333;
        }

        /* ── Responsive ── */
        @media (max-width: 600px) {
          :host { padding: 12px; }
          .header h1 { font-size: 1.2em; }
          .buttons { flex-direction: column; }
          .modal { width: calc(100% - 24px) !important; left: 12px !important; right: 12px !important; }
          .footer .btn { width: 100%; }
        }
      </style>

      ${this._renderHeader()}
      ${this._renderTabs()}
      ${this._activeTab === "audit" ? (this._isAnalyzing ? this._renderLoading() : this._renderContent()) : this._renderGenerator()}
      ${this._renderModal()}
      ${this._renderConfirmDialog()}
    `;

    this._attachEvents();
  }

  _renderHeader() {
    return `
      <div class="header">
        <div style="display: flex; align-items: center; gap: 12px;">
          <img src="/domolink_mistral_frontend/icon.png" alt="Logo" style="width: 38px; height: 38px; border-radius: 8px;" />
          <div>
            <h1 style="margin: 0; font-size: 1.5em; line-height: 1.2;">DomoLink-Mistral</h1>
            <div class="header-info">Dernière analyse : ${this._timeAgo(this._lastAnalysis)}</div>
          </div>
        </div>
        ${this._activeTab === "audit" ? `
          <button class="btn btn-primary" id="btn-analyze" ${this._isAnalyzing ? "disabled" : ""}>
            ${this._isAnalyzing ? '<span class="spinner"></span>Analyse en cours...' : '🔍 Analyser maintenant'}
          </button>
        ` : ''}
      </div>
    `;
  }

  _renderTabs() {
    return `
      <div class="tabs-nav">
        <button class="tab-btn ${this._activeTab === "audit" ? "active" : ""}" id="tab-audit">
          🛡️ Diagnostic & Santé (${this._issues.length})
        </button>
        <button class="tab-btn ${this._activeTab === "generator" ? "active" : ""}" id="tab-generator">
          ✨ Générateur d'Automations IA
        </button>
      </div>
    `;
  }

  _renderLoading() {
    const isError = this._currentStatus && this._currentStatus.includes("Erreur");
    const spinnerHtml = isError ? "❌" : `<div class="big-spinner"></div>`;

    return `
      <div class="loading-overlay">
        ${spinnerHtml}
        <h3 style="margin-bottom: 8px;">Analyse approfondie en cours...</h3>
        <p style="color: var(--primary-color, #03a9f4); font-weight: 600; margin-top: 0; max-width: 600px; margin-left: auto; margin-right: auto;">
          ${this._currentStatus || "Initialisation..."}
        </p>
      </div>
    `;
  }

  _renderContent() {
    let html = "";

    if (this._currentStatus && this._currentStatus.includes("Erreur")) {
      html += `
        <div class="card severity-border" style="border-left-color: #f44336;">
          <h3 style="margin-top:0; color:#f44336;">⚠️ Échec de l'analyse</h3>
          <p>${this._currentStatus}</p>
        </div>
      `;
    } else if (this._currentStatus && this._currentStatus.includes("terminée")) {
      html += `
        <div style="margin-bottom: 16px; font-size: 0.95em; color: var(--secondary-text-color, #757575);">
          ${this._currentStatus}
        </div>
      `;
    }

    if (this._issues.length === 0 && this._ignoredIssues.length === 0) {
      if (!this._currentStatus || !this._currentStatus.includes("Erreur")) {
        html += `<div class="empty-state">✅ Aucun problème détecté dans vos logs et fichiers YAML. Votre système est sain !</div>`;
      }
    } else {
      const highCount = this._issues.filter(i => i.severity === "high").length;
      const medCount = this._issues.filter(i => i.severity === "medium").length;
      const lowCount = this._issues.filter(i => i.severity === "low").length;

      html += `
        <div class="stats-bar">
          <div class="stat-chip"><strong>${this._issues.length}</strong> Problème(s) actif(s)</div>
          ${highCount > 0 ? `<div class="stat-chip" style="color: #f44336;">🔴 <strong>${highCount}</strong> Critique(s)</div>` : ''}
          ${medCount > 0 ? `<div class="stat-chip" style="color: #ff9800;">🟠 <strong>${medCount}</strong> Moyen(s)</div>` : ''}
          ${lowCount > 0 ? `<div class="stat-chip" style="color: #4caf50;">🟢 <strong>${lowCount}</strong> Faible(s)</div>` : ''}
        </div>
      `;

      // Issues actives
      for (const issue of this._issues) {
        html += this._renderIssueCard(issue, false);
      }

      // Bouton All Auto
      if (this._issues.some(i => i.auto_fix_script && i.auto_fix_script.length > 0)) {
        html += `
          <div class="footer">
            <button class="btn btn-allauto" id="btn-allauto">
              ⚡ All Auto — Sauvegarder et tout corriger (${this._issues.filter(i => i.auto_fix_script && i.auto_fix_script.length > 0).length} correctifs)
            </button>
          </div>
        `;
      }

      // Section ignorées (repliable)
      if (this._ignoredIssues.length > 0) {
        html += `
          <div class="section-toggle" id="toggle-ignored">
            ${this._showIgnored ? "▼" : "▶"} Erreurs ignorées (${this._ignoredIssues.length})
          </div>
        `;
        if (this._showIgnored) {
          html += `<div class="ignored-section">`;
          for (const issue of this._ignoredIssues) {
            html += this._renderIssueCard(issue, true);
          }
          html += `</div>`;
        }
      }
    }

    return html;
  }

  _renderGenerator() {
    let resultHtml = "";
    if (this._generatedAutomation) {
      const auto = this._generatedAutomation;
      resultHtml = `
        <div class="card" style="border: 2px solid var(--primary-color, #03a9f4); margin-top: 24px;">
          <h2 style="margin-top: 0; color: var(--primary-color, #03a9f4);">🎉 ${auto.title || "Automation générée"}</h2>
          <p style="color: var(--secondary-text-color);">${auto.description || ""}</p>
          
          ${auto.explanation ? `
            <div style="background: rgba(3,169,244,0.08); padding: 12px 16px; border-radius: 8px; margin: 14px 0; font-size: 0.92em; line-height: 1.5;">
              <strong>💡 Explication du fonctionnement :</strong><br>
              ${auto.explanation}
            </div>
          ` : ''}

          <div class="yaml-code-block">${auto.yaml || ""}</div>

          <div style="display: flex; gap: 12px; flex-wrap: wrap; justify-content: flex-end;">
            <button class="btn btn-ignore" id="btn-copy-yaml">📋 Copier le YAML</button>
            <button class="btn btn-success" id="btn-save-automation">💾 Injecter et activer dans automations.yaml</button>
          </div>
        </div>
      `;
    }

    return `
      <div class="gen-container">
        <div class="card">
          <h2 style="margin-top: 0;">✨ Créer une automation avec l'IA</h2>
          <p style="color: var(--secondary-text-color); margin-bottom: 16px;">
            Décrivez en langage naturel ce que vous souhaitez réaliser. Mistral analyse vos vraies entités Home Assistant pour générer une règle prête à l'emploi.
          </p>

          <div class="chips-container">
            <span class="chip" data-prompt="Éteindre toutes les lumières à 23h et fermer les volets">🌙 Extinction 23h</span>
            <span class="chip" data-prompt="Alerte notification si la porte du garage reste ouverte plus de 10 minutes">🚪 Alerte garage ouvert</span>
            <span class="chip" data-prompt="Allumer la lumière de l'allée sur détection de mouvement la nuit pendant 3 minutes">🚶 Détection mouvement nuit</span>
            <span class="chip" data-prompt="Fermer les volets si la température extérieure dépasse 26°C">☀️ Canicule volets fermés</span>
          </div>

          <textarea class="gen-textarea" id="gen-prompt-input" placeholder="Exemple : Si quelqu'un sonne à la porte et qu'il fait nuit, allumer la lumière du porche à 100% pendant 2 minutes...">${this._genPrompt}</textarea>

          <div style="display: flex; justify-content: flex-end;">
            <button class="btn btn-primary" id="btn-do-generate" ${this._isGenerating ? "disabled" : ""}>
              ${this._isGenerating ? '<span class="spinner"></span>Génération par Mistral...' : '✨ Générer l\'automation'}
            </button>
          </div>
        </div>

        ${resultHtml}
      </div>
    `;
  }

  _renderIssueCard(issue, isIgnored) {
    const color = this._severityColor(issue.severity);
    const label = this._severityLabel(issue.severity);
    const categoryLabel = issue.category ? this._categoryIcon(issue.category) : "";
    const hasAutoFix = issue.auto_fix_script && issue.auto_fix_script.length > 0;

    let buttons = "";
    if (isIgnored) {
      buttons = `<button class="btn btn-primary btn-small" data-action="unignore" data-id="${issue.id}">Réactiver</button>`;
    } else {
      buttons = `
        <button class="btn btn-ignore btn-small" data-action="ignore" data-id="${issue.id}">Ignorer</button>
        <button class="btn btn-manual btn-small" data-action="manual" data-id="${issue.id}">📖 Manuel</button>
        <button class="btn btn-auto btn-small" data-action="auto" data-id="${issue.id}" ${!hasAutoFix ? 'title="Pas de correctif automatique disponible"' : ''}>🔧 Automatique</button>
      `;
    }

    return `
      <div class="card severity-border" style="border-left-color: ${color};">
        <div class="card-title">
          <span>${issue.title}</span>
          ${categoryLabel ? `<span class="badge badge-category">${categoryLabel}</span>` : ''}
          <span class="badge ${isIgnored ? 'ignored-badge' : ''}" style="background: ${isIgnored ? '#9e9e9e' : color};">
            ${isIgnored ? 'Ignoré' : label}
          </span>
        </div>
        <p class="card-desc">${issue.description || ""}</p>
        <div class="buttons">${buttons}</div>
      </div>
    `;
  }

  _renderModal() {
    if (!this._selectedIssue) return "";

    const x = this._modalPos.x !== null ? this._modalPos.x : (window.innerWidth - 460);
    const y = this._modalPos.y !== null ? this._modalPos.y : 30;

    return `
      <div class="modal" id="modal" style="top: ${y}px; left: ${x}px;">
        <div class="modal-header" id="modal-header">
          📖 Guide Pas-à-Pas : ${this._selectedIssue.title}
          <button class="modal-close" id="modal-close">✕</button>
        </div>
        <div class="modal-body">${this._selectedIssue.manual_fix || "Aucune instruction détaillée disponible."}</div>
      </div>
    `;
  }

  _renderConfirmDialog() {
    if (!this._confirmData) return "";

    const hasAction = this._confirmData.onConfirm !== null;
    let diffHtml = "";

    // Afficher le Diff visuel si des actions de modification de fichier sont présentes
    if (this._confirmData.actions && Array.isArray(this._confirmData.actions)) {
      for (const act of this._confirmData.actions) {
        if (act.action_type === "yaml_edit" || act.file) {
          diffHtml += `
            <div class="diff-container">
              <div class="diff-file-label">📄 Fichier cible : ${act.file}</div>
              ${act.find ? `<div class="diff-line-remove"><strong>- Ligne(s) supprimée(s) :</strong><br>${act.find}</div>` : ''}
              ${act.replace ? `<div class="diff-line-add"><strong>+ Ligne(s) ajoutée(s) :</strong><br>${act.replace}</div>` : ''}
              ${act.content ? `<div class="diff-line-add"><strong>+ Nouveau contenu :</strong><br>${act.content}</div>` : ''}
            </div>
          `;
        } else if (act.domain && act.service) {
          diffHtml += `
            <div class="service-call-box">
              ⚡ <strong>Appel de service :</strong> ${act.domain}.${act.service}
              ${act.service_data ? `<pre style="margin:4px 0 0 0;">${JSON.stringify(act.service_data, null, 2)}</pre>` : ''}
            </div>
          `;
        }
      }
    }

    return `
      <div class="confirm-overlay" id="confirm-overlay">
        <div class="confirm-box">
          <h3>${this._confirmData.title || "Confirmation requise"}</h3>
          <p>${this._confirmData.message}</p>
          ${diffHtml}
          <div class="confirm-buttons">
            ${hasAction ? `<button class="btn btn-ignore" id="btn-confirm-cancel">Annuler</button>` : ''}
            <button class="btn ${hasAction ? 'btn-auto' : 'btn-primary'}" id="btn-confirm-ok">${hasAction ? 'Confirmer et Appliquer' : 'Compris'}</button>
          </div>
        </div>
      </div>
    `;
  }

  _attachEvents() {
    const root = this.shadowRoot;

    // Navigation onglets
    const tabAudit = root.getElementById("tab-audit");
    const tabGenerator = root.getElementById("tab-generator");
    if (tabAudit) {
      tabAudit.addEventListener("click", () => {
        this._activeTab = "audit";
        this._render();
      });
    }
    if (tabGenerator) {
      tabGenerator.addEventListener("click", () => {
        this._activeTab = "generator";
        this._render();
      });
    }

    // Bouton Analyser
    const btnAnalyze = root.getElementById("btn-analyze");
    if (btnAnalyze) {
      btnAnalyze.addEventListener("click", () => {
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    // Generator : Chips de suggestions rapides
    root.querySelectorAll(".chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const text = chip.dataset.prompt;
        const textarea = root.getElementById("gen-prompt-input");
        if (textarea) {
          textarea.value = text;
          this._genPrompt = text;
        }
      });
    });

    // Generator : Champ texte
    const genInput = root.getElementById("gen-prompt-input");
    if (genInput) {
      genInput.addEventListener("input", (e) => {
        this._genPrompt = e.target.value;
      });
    }

    // Generator : Bouton Générer
    const btnDoGenerate = root.getElementById("btn-do-generate");
    if (btnDoGenerate) {
      btnDoGenerate.addEventListener("click", async () => {
        const prompt = this._genPrompt.trim();
        if (!prompt) return;

        this._isGenerating = true;
        this._render();

        try {
          // Écouter la réponse via le service HA
          const resp = await this._hass.callService("domolink_mistral", "generate_automation", { prompt });
          if (resp && resp.response) {
            this._generatedAutomation = resp.response;
          }
        } catch (e) {
          console.error("DomoLink Generator error:", e);
        } finally {
          this._isGenerating = false;
          this._render();
        }
      });
    }

    // Generator : Copier le YAML
    const btnCopy = root.getElementById("btn-copy-yaml");
    if (btnCopy && this._generatedAutomation) {
      btnCopy.addEventListener("click", () => {
        navigator.clipboard.writeText(this._generatedAutomation.yaml || "");
        btnCopy.textContent = "✅ Copié !";
        setTimeout(() => { if (btnCopy) btnCopy.textContent = "📋 Copier le YAML"; }, 2000);
      });
    }

    // Generator : Injecter dans automations.yaml
    const btnSave = root.getElementById("btn-save-automation");
    if (btnSave && this._generatedAutomation) {
      btnSave.addEventListener("click", () => {
        this._confirmData = {
          title: `💾 Enregistrer l'automation`,
          message: `L'automation "${this._generatedAutomation.title}" sera injectée dans votre fichier automations.yaml (une copie de sauvegarde .bak sera créée). Continuer ?`,
          actions: [{
            file: "automations.yaml",
            content: this._generatedAutomation.yaml
          }],
          onConfirm: () => {
            this._hass.callService("domolink_mistral", "save_automation", {
              yaml: this._generatedAutomation.yaml
            });
            this._confirmData = {
              title: "🎉 Succès !",
              message: "Votre automation a été ajoutée et rechargée dans Home Assistant. Vous pouvez la retrouver dans Paramètres -> Automations & Scènes.",
              onConfirm: null
            };
            this._render();
          }
        };
        this._render();
      });
    }

    // Boutons d'action sur les cartes
    root.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        const allIssues = [...this._issues, ...this._ignoredIssues];
        const issue = allIssues.find((i) => i.id === id);

        switch (action) {
          case "ignore":
            this._hass.callService("domolink_mistral", "ignore_issue", { issue_id: id });
            break;
          case "unignore":
            this._hass.callService("domolink_mistral", "unignore_issue", { issue_id: id });
            break;
          case "manual":
            if (issue) {
              this._selectedIssue = issue;
              this._modalPos = { x: null, y: null };
              this._render();
            }
            break;
          case "auto":
            if (issue) {
              const autoFixAvailable = issue.auto_fix_script && issue.auto_fix_script.length > 0;
              if (autoFixAvailable) {
                this._confirmData = {
                  title: `🔧 Réparation : ${issue.title}`,
                  message: "Une sauvegarde de sécurité (.bak) sera créée avant d'appliquer ce correctif. Voici l'aperçu des modifications :",
                  actions: issue.auto_fix_script,
                  onConfirm: () => {
                    this._isApplying = true;
                    this._render();
                    this._hass.callService("domolink_mistral", "apply_fix", {
                      fix_script: JSON.stringify(issue.auto_fix_script),
                      issue_id: id
                    });
                  }
                };
              } else {
                this._confirmData = {
                  title: `ℹ️ ${issue.title}`,
                  message: "Aucun correctif automatique n'est disponible pour ce problème. Consultez le guide « 📖 Manuel » pour les instructions pas-à-pas.",
                  onConfirm: null
                };
              }
              this._render();
            }
            break;
        }
      });
    });

    // Confirmation dialog listeners
    const btnConfirmCancel = root.getElementById("btn-confirm-cancel");
    if (btnConfirmCancel) {
      btnConfirmCancel.addEventListener("click", () => {
        this._confirmData = null;
        this._render();
      });
    }

    const btnConfirmOk = root.getElementById("btn-confirm-ok");
    if (btnConfirmOk) {
      btnConfirmOk.addEventListener("click", () => {
        const cb = this._confirmData ? this._confirmData.onConfirm : null;
        this._confirmData = null;
        this._render();
        if (cb) cb();
      });
    }

    // All Auto
    const btnAllAuto = root.getElementById("btn-allauto");
    if (btnAllAuto) {
      btnAllAuto.addEventListener("click", () => {
        const fixable = this._issues.filter(i => i.auto_fix_script && i.auto_fix_script.length > 0);
        const allActions = [];
        fixable.forEach(f => {
          if (Array.isArray(f.auto_fix_script)) allActions.push(...f.auto_fix_script);
        });

        this._confirmData = {
          title: "⚡ Exécuter All Auto",
          message: `Une sauvegarde complète sera créée, puis ${fixable.length} correctif(s) seront appliqués. Aperçu des opérations :`,
          actions: allActions,
          onConfirm: () => {
            this._isApplying = true;
            this._render();
            this._hass.callService("domolink_mistral", "apply_all_fixes", {});
          }
        };
        this._render();
      });
    }

    // Toggle section ignorées
    const toggleIgnored = root.getElementById("toggle-ignored");
    if (toggleIgnored) {
      toggleIgnored.addEventListener("click", () => {
        this._showIgnored = !this._showIgnored;
        this._render();
      });
    }

    // Modal close
    const modalClose = root.getElementById("modal-close");
    if (modalClose) {
      modalClose.addEventListener("click", () => {
        this._selectedIssue = null;
        this._render();
      });
    }

    // Modal drag
    const modalHeader = root.getElementById("modal-header");
    const modal = root.getElementById("modal");
    if (modalHeader && modal) {
      modalHeader.addEventListener("mousedown", (e) => {
        this._isDragging = true;
        this._dragOffset = {
          x: e.clientX - modal.offsetLeft,
          y: e.clientY - modal.offsetTop,
        };
        e.preventDefault();
      });

      const onMove = (e) => {
        if (!this._isDragging) return;
        this._modalPos = {
          x: e.clientX - this._dragOffset.x,
          y: e.clientY - this._dragOffset.y,
        };
        modal.style.left = this._modalPos.x + "px";
        modal.style.top = this._modalPos.y + "px";
      };

      const onUp = () => { this._isDragging = false; };

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    }
  }
}

customElements.define("domolink-mistral-panel", DomolinkMistralPanel);
