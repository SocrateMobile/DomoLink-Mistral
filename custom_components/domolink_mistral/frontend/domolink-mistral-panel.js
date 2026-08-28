/**
 * DomoLink-Mistral — Panneau Frontend pour Home Assistant
 *
 * Panneau latéral interactif avec :
 * - Analyse des logs, configuration.yaml, !includes, automations, scripts, blueprints, ESPHome
 * - Badges de gravité colorés (high/medium/low) et étiquettes de catégorie
 * - Boîtes de dialogue de confirmation stables (résistant aux mises à jour d'état HA)
 * - Modal déplaçable (draggable) pour le guide pas-à-pas manuel
 * - Section "Erreurs ignorées" repliable
 * - Design responsive (mobile & desktop)
 * - 100% Vanilla JS (zéro dépendance CDN externe)
 */

class DomolinkMistralPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._issues = [];
    this._ignoredIssues = [];
    this._selectedIssue = null;
    this._isAnalyzing = false;
    this._isApplying = false;
    this._lastAnalysis = null;
    this._currentStatus = "En attente";
    this._showIgnored = false;
    this._confirmData = null; // { title, message, onConfirm }
    this._initialized = false;

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
          flex-wrap: wrap; gap: 12px; margin-bottom: 24px;
        }
        .header h1 { margin: 0; font-size: 1.5em; }
        .header-info { font-size: 0.85em; color: var(--secondary-text-color, #757575); }

        .btn {
          padding: 10px 20px; border: none; border-radius: 8px;
          cursor: pointer; font-weight: 600; font-size: 0.9em;
          color: white; transition: opacity 0.2s;
        }
        .btn:hover { opacity: 0.85; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-primary { background: var(--primary-color, #03a9f4); }
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
          position: fixed; width: 420px; max-height: 80vh;
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

        /* ── Confirmation dialog (Stable) ── */
        .confirm-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.6); z-index: 300;
          display: flex; align-items: center; justify-content: center;
        }
        .confirm-box {
          background: var(--card-background-color, #fff); padding: 24px;
          border-radius: 12px; max-width: 440px; width: 90%;
          box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        }
        .confirm-box h3 { margin: 0 0 12px 0; font-size: 1.2em; color: var(--primary-text-color); }
        .confirm-box p { margin: 0 0 20px 0; line-height: 1.5; color: var(--secondary-text-color); font-size: 0.95em; }
        .confirm-buttons { display: flex; gap: 12px; justify-content: flex-end; }

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
      ${this._isAnalyzing ? this._renderLoading() : this._renderContent()}
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
        <button class="btn btn-primary" id="btn-analyze" ${this._isAnalyzing ? "disabled" : ""}>
          ${this._isAnalyzing ? '<span class="spinner"></span>Analyse en cours...' : '🔍 Analyser maintenant'}
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
        <button class="btn btn-auto btn-small" data-action="auto" data-id="${issue.id}" ${!hasAutoFix ? 'title="Pas de correctif automatique disponible pour ce problème"' : ''}>🔧 Automatique</button>
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

    const x = this._modalPos.x !== null ? this._modalPos.x : (window.innerWidth - 440);
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

    return `
      <div class="confirm-overlay" id="confirm-overlay">
        <div class="confirm-box">
          <h3>${this._confirmData.title || "Confirmation requise"}</h3>
          <p>${this._confirmData.message}</p>
          <div class="confirm-buttons">
            ${hasAction ? `<button class="btn btn-ignore" id="btn-confirm-cancel">Annuler</button>` : ''}
            <button class="btn ${hasAction ? 'btn-auto' : 'btn-primary'}" id="btn-confirm-ok">${hasAction ? 'Confirmer' : 'Compris'}</button>
          </div>
        </div>
      </div>
    `;
  }

  _attachEvents() {
    const root = this.shadowRoot;

    // Bouton Analyser
    const btnAnalyze = root.getElementById("btn-analyze");
    if (btnAnalyze) {
      btnAnalyze.addEventListener("click", () => {
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
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
                  message: "Une sauvegarde de sécurité sera créée avant d'appliquer la modification. Souhaitez-vous continuer ?",
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
                  message: "Aucun correctif automatique n'est disponible pour ce problème. Consultez le guide « 📖 Manuel » pour les instructions de correction pas-à-pas.",
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
        this._confirmData = {
          title: "⚡ Exécuter All Auto",
          message: "Une sauvegarde complète sera créée, puis tous les correctifs automatiques disponibles seront appliqués. Confirmer ?",
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
