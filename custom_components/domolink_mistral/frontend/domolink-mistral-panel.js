/**
 * DomoLink-Mistral — Panneau Frontend pour Home Assistant
 *
 * Panneau latéral interactif avec :
 * - Badges de gravité colorés (high/medium/low)
 * - Spinner de chargement pendant l'analyse
 * - Modal déplaçable (draggable) pour le mode Manuel
 * - Section "Erreurs ignorées" repliable
 * - Design responsive (mobile)
 * - Aucun import CDN externe — vanilla JS pur
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
    this._lastAnalysis = null;
    this._showIgnored = false;

    // Drag state pour la modal
    this._dragOffset = { x: 0, y: 0 };
    this._modalPos = { x: null, y: null };
    this._isDragging = false;
  }

  set hass(hass) {
    this._hass = hass;
    this._updateFromSensor();
    this._render();
  }

  _updateFromSensor() {
    if (!this._hass) return;

    // Trouver le sensor DomoLink-Mistral de manière fiable
    const entityId = Object.keys(this._hass.states).find(
      (id) => id.startsWith("sensor.") && id.includes("domolink") && id.includes("probleme")
    ) || Object.keys(this._hass.states).find(
      (id) => id.startsWith("sensor.") && id.includes("domolink")
    );

    if (entityId && this._hass.states[entityId]) {
      const stateObj = this._hass.states[entityId];
      const attrs = stateObj.attributes || {};
      this._issues = attrs.issues || [];
      this._ignoredIssues = attrs.ignored_issues || [];
      this._lastAnalysis = attrs.last_analysis || null;

      // Si on était en train d'analyser et que les résultats arrivent
      if (this._isAnalyzing && this._lastAnalysis) {
        this._isAnalyzing = false;
      }
    }
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

        .card-title { margin: 0 0 8px 0; font-size: 1.1em; display: flex; align-items: center; flex-wrap: wrap; }
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
        .modal-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          z-index: 99; /* ne bloque PAS les clics derrière */
          pointer-events: none;
        }
        .modal {
          position: fixed; width: 380px; max-height: 80vh;
          background: var(--card-background-color, #fff);
          border: 2px solid var(--primary-color, #03a9f4);
          border-radius: 12px; z-index: 100;
          box-shadow: 0 8px 32px rgba(0,0,0,0.25);
          color: var(--primary-text-color);
          pointer-events: all; overflow: hidden;
          display: flex; flex-direction: column;
        }
        .modal-header {
          padding: 12px 16px; cursor: grab;
          background: var(--primary-color, #03a9f4); color: white;
          font-weight: 700; display: flex; justify-content: space-between; align-items: center;
          user-select: none;
        }
        .modal-header:active { cursor: grabbing; }
        .modal-body { padding: 16px; overflow-y: auto; flex: 1; line-height: 1.6; white-space: pre-wrap; }
        .modal-close { background: none; border: none; color: white; font-size: 1.4em; cursor: pointer; padding: 0 4px; }

        /* ── Confirmation dialog ── */
        .confirm-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.5); z-index: 200;
          display: flex; align-items: center; justify-content: center;
        }
        .confirm-box {
          background: var(--card-background-color, #fff); padding: 24px;
          border-radius: 12px; max-width: 400px; width: 90%;
          box-shadow: 0 8px 32px rgba(0,0,0,0.3);
        }
        .confirm-box p { margin: 0 0 20px 0; line-height: 1.5; }
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
    `;

    this._attachEvents();
  }

  _renderHeader() {
    return `
      <div class="header">
        <div>
          <h1>🧠 DomoLink-Mistral</h1>
          <div class="header-info">Dernière analyse : ${this._timeAgo(this._lastAnalysis)}</div>
        </div>
        <button class="btn btn-primary" id="btn-analyze" ${this._isAnalyzing ? "disabled" : ""}>
          ${this._isAnalyzing ? '<span class="spinner"></span>Analyse en cours...' : '🔍 Analyser maintenant'}
        </button>
      </div>
    `;
  }

  _renderLoading() {
    return `
      <div class="loading-overlay">
        <div class="big-spinner"></div>
        <p>Mistral AI analyse vos logs...<br>Cela peut prendre 10 à 30 secondes.</p>
      </div>
    `;
  }

  _renderContent() {
    let html = "";

    if (this._issues.length === 0 && this._ignoredIssues.length === 0) {
      html += `<div class="empty-state">✅ Aucun problème détecté. Votre système est sain !</div>`;
    } else {
      // Issues actives
      for (const issue of this._issues) {
        html += this._renderIssueCard(issue, false);
      }

      // Bouton All Auto
      if (this._issues.some(i => i.auto_fix_script && i.auto_fix_script.length > 0)) {
        html += `
          <div class="footer">
            <button class="btn btn-allauto" id="btn-allauto">
              ⚡ All Auto — Sauvegarder et tout corriger
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

    let buttons = "";
    if (isIgnored) {
      buttons = `<button class="btn btn-primary btn-small" data-action="unignore" data-id="${issue.id}">Réactiver</button>`;
    } else {
      buttons = `
        <button class="btn btn-ignore btn-small" data-action="ignore" data-id="${issue.id}">Ignorer</button>
        <button class="btn btn-manual btn-small" data-action="manual" data-id="${issue.id}">📖 Manuel</button>
        <button class="btn btn-auto btn-small" data-action="auto" data-id="${issue.id}">🔧 Automatique</button>
      `;
    }

    return `
      <div class="card severity-border" style="border-left-color: ${color};">
        <div class="card-title">
          ${issue.title}
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

    const x = this._modalPos.x !== null ? this._modalPos.x : (window.innerWidth - 400);
    const y = this._modalPos.y !== null ? this._modalPos.y : 20;

    return `
      <div class="modal" id="modal" style="top: ${y}px; left: ${x}px;">
        <div class="modal-header" id="modal-header">
          📖 Guide Pas-à-Pas
          <button class="modal-close" id="modal-close">✕</button>
        </div>
        <div class="modal-body">${this._selectedIssue.manual_fix || "Aucune instruction disponible."}</div>
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
            if (issue) this._showConfirm(
              "Une sauvegarde sera créée, puis le correctif sera appliqué. Continuer ?",
              () => this._hass.callService("domolink_mistral", "apply_fix", {
                fix_script: JSON.stringify(issue.auto_fix_script)
              })
            );
            break;
        }
      });
    });

    // All Auto
    const btnAllAuto = root.getElementById("btn-allauto");
    if (btnAllAuto) {
      btnAllAuto.addEventListener("click", () => {
        this._showConfirm(
          "Voulez-vous vraiment corriger TOUTES les erreurs affichées ? Une sauvegarde sera créée au préalable.",
          () => this._hass.callService("domolink_mistral", "apply_all_fixes", {})
        );
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

  _showConfirm(message, onConfirm) {
    const root = this.shadowRoot;
    const overlay = document.createElement("div");
    overlay.className = "confirm-overlay";
    overlay.innerHTML = `
      <div class="confirm-box">
        <p>${message}</p>
        <div class="confirm-buttons">
          <button class="btn btn-ignore" id="confirm-cancel">Annuler</button>
          <button class="btn btn-auto" id="confirm-ok">Confirmer</button>
        </div>
      </div>
    `;
    root.appendChild(overlay);

    overlay.querySelector("#confirm-cancel").addEventListener("click", () => overlay.remove());
    overlay.querySelector("#confirm-ok").addEventListener("click", () => {
      overlay.remove();
      onConfirm();
    });
  }
}

customElements.define("domolink-mistral-panel", DomolinkMistralPanel);
