/**
 * DomoLink-Mistral — Panneau Frontend Ultime pour Home Assistant
 *
 * 6 Onglets intégrés :
 * 1. 🛡️ Diagnostic & Audit (Logs, YAML, !includes, ESPHome, Blueprints, Entités)
 * 2. 🔧 Réparation Sécurisée (Actions 1-clic, Diff visuel avant/après, All Auto, Ignorés)
 * 3. ✨ Générateur IA (Création d'automations en langage naturel avec vraies entités)
 * 4. 🎙️ Assist Vocal & Écrit (Chat interactif avec tool-calling pour piloter la maison)
 * 5. 👁️ Vision & Surveillance (Analyse de caméras via Mistral Pixtral : colis, personnes, anomalies)
 * 6. 📰 Smart Briefing (Synthèse matinale/soirée avec lecture vocale TTS et résumé)
 */

class DomolinkMistralPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._hass = null;
    this._activeTab = "audit"; // "audit" | "repair" | "generator" | "assist" | "vision" | "briefing"
    this._issues = [];
    this._ignoredIssues = [];
    this._selectedIssue = null;
    this._isAnalyzing = false;
    this._isApplying = false;
    this._isGenerating = false;
    this._isAssisting = false;
    this._isAnalyzingVision = false;
    this._isGeneratingBriefing = false;
    this._lastAnalysis = null;
    this._currentStatus = "En attente";
    this._showIgnored = false;
    this._confirmData = null;
    this._initialized = false;
    this._repairFilter = "all"; // "all" | "high" | "medium" | "low"

    // Onglet Générateur
    this._genPrompt = "";
    this._generatedAutomation = null;

    // Onglet Assist Chat
    this._chatInput = "";
    this._chatMessages = [
      {
        role: "assistant",
        text: "Bonjour ! Je suis votre assistant DomoLink-Mistral. Que puis-je faire pour vous aujourd'hui ?",
        services: []
      }
    ];

    // Onglet Vision
    this._selectedCamera = "";
    this._visionPrompt = "Décris précisément ce que tu vois sur cette image. Détecte les personnes, véhicules, colis, ouvertures ou anomalies.";
    this._visionResult = null;

    // Onglet Briefing
    this._briefingTimeOfDay = "auto";
    this._briefingCustom = "";
    this._briefingResult = null;

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

      // Arrêter les spinners
      if (this._isAnalyzing && (newStatus.includes("terminée") || newStatus.includes("Erreur") || newStatus.includes("✅"))) {
        this._isAnalyzing = false;
      }
      if (this._isApplying && !newStatus.startsWith("⏳")) {
        this._isApplying = false;
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
      default: return category || "Général";
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

        /* ── Navigation 6 Onglets ── */
        .tabs-nav {
          display: flex; gap: 6px; margin-bottom: 24px;
          border-bottom: 2px solid var(--divider-color, #e0e0e0);
          padding-bottom: 8px; overflow-x: auto;
        }
        .tab-btn {
          padding: 10px 16px; border: none; border-radius: 8px;
          cursor: pointer; font-weight: 600; font-size: 0.9em;
          background: transparent; color: var(--secondary-text-color, #757575);
          white-space: nowrap; transition: all 0.2s;
          display: flex; align-items: center; gap: 6px;
        }
        .tab-btn:hover { background: rgba(0,0,0,0.05); color: var(--primary-text-color); }
        .tab-btn.active {
          background: var(--primary-color, #03a9f4);
          color: white;
          box-shadow: 0 2px 6px rgba(3, 169, 244, 0.35);
        }
        .tab-count {
          background: rgba(255,255,255,0.3); padding: 2px 6px;
          border-radius: 10px; font-size: 0.75em;
        }

        .btn {
          padding: 10px 18px; border: none; border-radius: 8px;
          cursor: pointer; font-weight: 600; font-size: 0.9em;
          color: white; transition: opacity 0.2s;
          display: inline-flex; align-items: center; gap: 6px; justify-content: center;
        }
        .btn:hover { opacity: 0.88; }
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
          font-size: 0.75em; font-weight: 700; color: white;
        }
        .badge-category {
          background: rgba(150, 150, 150, 0.18);
          color: var(--primary-text-color, #333);
          border: 1px solid rgba(150, 150, 150, 0.25);
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

        .card-title { margin: 0 0 8px 0; font-size: 1.1em; display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
        .card-desc { margin: 0 0 16px 0; line-height: 1.5; color: var(--secondary-text-color, #616161); }
        .buttons { display: flex; gap: 8px; flex-wrap: wrap; }

        .spinner {
          display: inline-block; width: 18px; height: 18px;
          border: 3px solid rgba(255,255,255,0.3);
          border-top: 3px solid white;
          border-radius: 50%;
          animation: spin 0.8s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        .big-spinner {
          width: 48px; height: 48px; margin: 0 auto 20px;
          border: 4px solid var(--divider-color, #e0e0e0);
          border-top: 4px solid var(--primary-color, #03a9f4);
          border-radius: 50%;
          animation: spin 1s linear infinite;
        }

        .loading-overlay {
          text-align: center; padding: 60px 20px;
          color: var(--secondary-text-color);
        }

        .empty-state {
          text-align: center; padding: 50px 20px; font-size: 1.15em;
          color: var(--secondary-text-color);
        }

        /* ── Visual Diff ── */
        .diff-container {
          background: #1e1e1e; color: #d4d4d4;
          border-radius: 8px; padding: 14px; margin: 12px 0;
          font-family: monospace; font-size: 0.85em; overflow-x: auto;
        }
        .diff-file-label { color: #03a9f4; font-weight: 700; margin-bottom: 8px; }
        .diff-line-remove {
          background: rgba(244, 67, 54, 0.2); color: #ef5350;
          padding: 4px 8px; border-left: 3px solid #f44336; margin-bottom: 4px;
          white-space: pre-wrap; word-break: break-all;
        }
        .diff-line-add {
          background: rgba(76, 175, 80, 0.2); color: #81c784;
          padding: 4px 8px; border-left: 3px solid #4caf50;
          white-space: pre-wrap; word-break: break-all;
        }
        .service-call-box {
          background: rgba(3, 169, 244, 0.1); border-left: 3px solid #03a9f4;
          padding: 8px 12px; margin: 8px 0; font-family: monospace; font-size: 0.85em;
        }

        /* ── Modals & Dialogs ── */
        .confirm-overlay {
          position: fixed; top: 0; left: 0; right: 0; bottom: 0;
          background: rgba(0,0,0,0.65); z-index: 300;
          display: flex; align-items: center; justify-content: center;
        }
        .confirm-box {
          background: var(--card-background-color, #fff); padding: 24px;
          border-radius: 12px; max-width: 550px; width: 92%;
          max-height: 85vh; overflow-y: auto; box-shadow: 0 12px 40px rgba(0,0,0,0.4);
        }
        .confirm-box h3 { margin: 0 0 12px 0; color: var(--primary-text-color); }
        .confirm-box p { margin: 0 0 16px 0; color: var(--secondary-text-color); line-height: 1.5; }
        .confirm-buttons { display: flex; gap: 12px; justify-content: flex-end; margin-top: 20px; }

        .modal {
          position: fixed; width: 450px; max-height: 80vh;
          background: var(--card-background-color, #fff);
          border: 2px solid var(--primary-color, #03a9f4);
          border-radius: 12px; z-index: 100; box-shadow: 0 8px 32px rgba(0,0,0,0.25);
          color: var(--primary-text-color); display: flex; flex-direction: column; overflow: hidden;
        }
        .modal-header {
          padding: 12px 16px; cursor: grab; background: var(--primary-color, #03a9f4); color: white;
          font-weight: 700; display: flex; justify-content: space-between; align-items: center;
        }
        .modal-body { padding: 16px; overflow-y: auto; flex: 1; line-height: 1.6; white-space: pre-wrap; font-size: 0.9em; }
        .modal-close { background: none; border: none; color: white; font-size: 1.4em; cursor: pointer; }

        /* ── Chat Assist UI ── */
        .chat-container { display: flex; flex-direction: column; height: 500px; }
        .chat-messages { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 12px; }
        .chat-bubble {
          max-width: 80%; padding: 12px 16px; border-radius: 14px; line-height: 1.5; font-size: 0.95em;
        }
        .chat-user {
          align-self: flex-end; background: var(--primary-color, #03a9f4); color: white; border-bottom-right-radius: 2px;
        }
        .chat-bot {
          align-self: flex-start; background: rgba(0,0,0,0.06); color: var(--primary-text-color); border-bottom-left-radius: 2px;
        }
        .chat-input-bar { display: flex; gap: 8px; margin-top: 12px; }
        .chat-input {
          flex: 1; padding: 12px 16px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff); color: var(--primary-text-color);
        }

        /* ── Form Inputs ── */
        .input-field {
          width: 100%; padding: 12px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc);
          background: var(--card-background-color, #fff); color: var(--primary-text-color);
          box-sizing: border-box; margin-bottom: 12px; font-family: inherit;
        }
        .chips-container { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 16px; }
        .chip {
          background: rgba(3, 169, 244, 0.1); color: var(--primary-color, #03a9f4);
          border: 1px solid rgba(3, 169, 244, 0.3); border-radius: 16px;
          padding: 6px 12px; font-size: 0.8em; font-weight: 600; cursor: pointer;
        }
        .chip:hover { background: var(--primary-color, #03a9f4); color: white; }

        .yaml-code-block {
          background: #1e1e1e; color: #d4d4d4; padding: 16px; border-radius: 8px;
          font-family: monospace; font-size: 0.9em; line-height: 1.5; overflow-x: auto; white-space: pre;
          margin: 16px 0; border: 1px solid #333;
        }

        @media (max-width: 700px) {
          :host { padding: 12px; }
          .modal { width: calc(100% - 24px) !important; left: 12px !important; }
        }
      </style>

      ${this._renderHeader()}
      ${this._renderTabs()}

      ${this._renderActiveTabContent()}

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
            <h1 style="margin: 0; font-size: 1.4em; line-height: 1.2;">DomoLink-Mistral</h1>
            <div class="header-info">Dernière analyse : ${this._timeAgo(this._lastAnalysis)}</div>
          </div>
        </div>
        <button class="btn btn-primary" id="btn-quick-scan" ${this._isAnalyzing ? "disabled" : ""}>
          ${this._isAnalyzing ? '<span class="spinner"></span>Audit en cours...' : '🔍 Lancer l\'Audit'}
        </button>
      </div>
    `;
  }

  _renderTabs() {
    return `
      <div class="tabs-nav">
        <button class="tab-btn ${this._activeTab === "audit" ? "active" : ""}" data-tab="audit">
          🛡️ Diagnostic & Audit
        </button>
        <button class="tab-btn ${this._activeTab === "repair" ? "active" : ""}" data-tab="repair">
          🔧 Réparation <span class="tab-count">${this._issues.length}</span>
        </button>
        <button class="tab-btn ${this._activeTab === "generator" ? "active" : ""}" data-tab="generator">
          ✨ Générateur IA
        </button>
        <button class="tab-btn ${this._activeTab === "assist" ? "active" : ""}" data-tab="assist">
          🎙️ Assist Vocal & Écrit
        </button>
        <button class="tab-btn ${this._activeTab === "vision" ? "active" : ""}" data-tab="vision">
          👁️ Vision & Caméras
        </button>
        <button class="tab-btn ${this._activeTab === "briefing" ? "active" : ""}" data-tab="briefing">
          📰 Smart Briefing
        </button>
      </div>
    `;
  }

  _renderActiveTabContent() {
    if (this._isAnalyzing) return this._renderLoading();

    switch (this._activeTab) {
      case "audit": return this._renderAuditTab();
      case "repair": return this._renderRepairTab();
      case "generator": return this._renderGeneratorTab();
      case "assist": return this._renderAssistTab();
      case "vision": return this._renderVisionTab();
      case "briefing": return this._renderBriefingTab();
      default: return this._renderAuditTab();
    }
  }

  _renderLoading() {
    const isError = this._currentStatus && this._currentStatus.includes("Erreur");
    return `
      <div class="loading-overlay">
        ${isError ? "❌" : `<div class="big-spinner"></div>`}
        <h3>Traitement Mistral en cours...</h3>
        <p style="color: var(--primary-color, #03a9f4); font-weight: 600; max-width: 600px; margin: 0 auto;">
          ${this._currentStatus || "Initialisation..."}
        </p>
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     ONGLET 1 : DIAGNOSTIC & AUDIT
     ═══════════════════════════════════════════════════════ */
  _renderAuditTab() {
    const highCount = this._issues.filter(i => i.severity === "high").length;
    const medCount = this._issues.filter(i => i.severity === "medium").length;
    const lowCount = this._issues.filter(i => i.severity === "low").length;

    return `
      <div>
        <div class="stats-bar">
          <div class="stat-chip"><strong>${this._issues.length}</strong> Anomalie(s) active(s)</div>
          <div class="stat-chip" style="color: #f44336;">🔴 <strong>${highCount}</strong> Critique(s)</div>
          <div class="stat-chip" style="color: #ff9800;">🟠 <strong>${medCount}</strong> Moyenne(s)</div>
          <div class="stat-chip" style="color: #4caf50;">🟢 <strong>${lowCount}</strong> Faible(s)</div>
        </div>

        <div class="card">
          <h2 style="margin-top:0;">🛡️ Bilan de Santé du Système</h2>
          <p style="color: var(--secondary-text-color);">
            DomoLink-Mistral inspecte en continu vos logs, votre configuration YAML récursive, vos périphériques ESPHome, vos Blueprints et l'état de toutes vos entités.
          </p>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin: 20px 0;">
            <div style="background: rgba(0,0,0,0.03); padding: 14px; border-radius: 8px; border-left: 4px solid #03a9f4;">
              <strong>📜 Logs & Erreurs</strong><br>
              <span style="font-size: 0.85em; color: var(--secondary-text-color);">homeassistant.log & system_log structuré</span>
            </div>
            <div style="background: rgba(0,0,0,0.03); padding: 14px; border-radius: 8px; border-left: 4px solid #4caf50;">
              <strong>📑 Syntaxe & Includes YAML</strong><br>
              <span style="font-size: 0.85em; color: var(--secondary-text-color);">configuration.yaml, automations, scripts</span>
            </div>
            <div style="background: rgba(0,0,0,0.03); padding: 14px; border-radius: 8px; border-left: 4px solid #ff9800;">
              <strong>⚡ ESPHome Builder</strong><br>
              <span style="font-size: 0.85em; color: var(--secondary-text-color);">Fichiers esphome/*.yaml & composants dépréciés</span>
            </div>
            <div style="background: rgba(0,0,0,0.03); padding: 14px; border-radius: 8px; border-left: 4px solid #9c27b0;">
              <strong>🏷️ Intégrité des Entités</strong><br>
              <span style="font-size: 0.85em; color: var(--secondary-text-color);">Entités orphelines & intégrations en panne</span>
            </div>
          </div>

          <div style="display: flex; gap: 12px; justify-content: flex-end; flex-wrap: wrap;">
            <button class="btn btn-primary" id="btn-run-full-audit">🔍 Lancer un Audit Complet</button>
            ${this._issues.length > 0 ? `<button class="btn btn-auto" id="btn-goto-repair">🔧 Voir les ${this._issues.length} réparations</button>` : ''}
          </div>
        </div>
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     ONGLET 2 : RÉPARATION SÉCURISÉE
     ═══════════════════════════════════════════════════════ */
  _renderRepairTab() {
    let filtered = this._issues;
    if (this._repairFilter !== "all") {
      filtered = this._issues.filter(i => i.severity === this._repairFilter);
    }

    let cardsHtml = "";
    if (filtered.length === 0) {
      cardsHtml = `<div class="empty-state">✅ Aucune anomalie dans cette catégorie !</div>`;
    } else {
      for (const issue of filtered) {
        cardsHtml += this._renderIssueCard(issue, false);
      }
    }

    const hasFixable = this._issues.some(i => i.auto_fix_script && i.auto_fix_script.length > 0);

    return `
      <div>
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;">
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-small ${this._repairFilter === 'all' ? 'btn-primary' : 'btn-ignore'}" data-filter="all">Tous (${this._issues.length})</button>
            <button class="btn btn-small ${this._repairFilter === 'high' ? 'btn-primary' : 'btn-ignore'}" data-filter="high">🔴 Critiques</button>
            <button class="btn btn-small ${this._repairFilter === 'medium' ? 'btn-primary' : 'btn-ignore'}" data-filter="medium">🟠 Moyens</button>
            <button class="btn btn-small ${this._repairFilter === 'low' ? 'btn-primary' : 'btn-ignore'}" data-filter="low">🟢 Faibles</button>
          </div>
          ${hasFixable ? `
            <button class="btn btn-allauto" id="btn-allauto">
              ⚡ All Auto — Sauvegarder & Tout Corriger
            </button>
          ` : ''}
        </div>

        ${cardsHtml}

        ${this._ignoredIssues.length > 0 ? `
          <div class="section-toggle" id="toggle-ignored">
            ${this._showIgnored ? "▼" : "▶"} Anomalies ignorées (${this._ignoredIssues.length})
          </div>
          ${this._showIgnored ? `
            <div style="opacity: 0.65; margin-top: 12px;">
              ${this._ignoredIssues.map(i => this._renderIssueCard(i, true)).join("")}
            </div>
          ` : ''}
        ` : ''}
      </div>
    `;
  }

  _renderIssueCard(issue, isIgnored) {
    const color = this._severityColor(issue.severity);
    const label = this._severityLabel(issue.severity);
    const categoryLabel = this._categoryIcon(issue.category);
    const hasAutoFix = issue.auto_fix_script && issue.auto_fix_script.length > 0;

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
          <span>${issue.title}</span>
          <span class="badge badge-category">${categoryLabel}</span>
          <span class="badge" style="background: ${isIgnored ? '#9e9e9e' : color};">
            ${isIgnored ? 'Ignoré' : label}
          </span>
        </div>
        <p class="card-desc">${issue.description || ""}</p>
        <div class="buttons">${buttons}</div>
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     ONGLET 3 : GÉNÉRATEUR IA
     ═══════════════════════════════════════════════════════ */
  _renderGeneratorTab() {
    let resultHtml = "";
    if (this._generatedAutomation) {
      const auto = this._generatedAutomation;
      resultHtml = `
        <div class="card" style="border: 2px solid var(--primary-color, #03a9f4); margin-top: 24px;">
          <h2 style="margin-top: 0; color: var(--primary-color, #03a9f4);">🎉 ${auto.title || "Automation générée"}</h2>
          <p style="color: var(--secondary-text-color);">${auto.description || ""}</p>
          
          ${auto.explanation ? `
            <div style="background: rgba(3,169,244,0.08); padding: 12px 16px; border-radius: 8px; margin: 14px 0; font-size: 0.92em; line-height: 1.5;">
              <strong>💡 Explication :</strong><br>${auto.explanation}
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
      <div style="max-width: 800px; margin: 0 auto;">
        <div class="card">
          <h2 style="margin-top: 0;">✨ Créer une automation avec l'IA</h2>
          <p style="color: var(--secondary-text-color); margin-bottom: 16px;">
            Décrivez en français ce que vous souhaitez automatiser. Mistral utilise vos vraies entités Home Assistant pour générer un code parfait.
          </p>

          <div class="chips-container">
            <span class="chip" data-prompt="Éteindre toutes les lumières à 23h et fermer les volets">🌙 Extinction 23h</span>
            <span class="chip" data-prompt="Alerte notification si la porte du garage reste ouverte plus de 10 minutes">🚪 Alerte garage</span>
            <span class="chip" data-prompt="Allumer la lumière de l'allée sur détection de mouvement la nuit pendant 3 minutes">🚶 Détection mouvement nuit</span>
            <span class="chip" data-prompt="Fermer les volets si la température extérieure dépasse 26°C">☀️ Canicule volets fermés</span>
          </div>

          <textarea class="input-field" id="gen-prompt-input" rows="4" placeholder="Exemple : Si quelqu'un sonne à la porte et qu'il fait nuit, allumer la lumière du porche pendant 2 min...">${this._genPrompt}</textarea>

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

  /* ═══════════════════════════════════════════════════════
     ONGLET 4 : ASSIST VOCAL & ÉCRIT
     ═══════════════════════════════════════════════════════ */
  _renderAssistTab() {
    const msgHtml = this._chatMessages.map(m => `
      <div class="chat-bubble ${m.role === 'user' ? 'chat-user' : 'chat-bot'}">
        ${m.text}
        ${m.services && m.services.length > 0 ? `
          <div style="font-size:0.8em; margin-top:6px; opacity:0.85; border-top:1px solid rgba(255,255,255,0.2); padding-top:4px;">
            ⚡ Actions exécutées : ${m.services.map(s => `${s.domain}.${s.service}`).join(", ")}
          </div>
        ` : ''}
      </div>
    `).join("");

    return `
      <div style="max-width: 800px; margin: 0 auto;">
        <div class="card chat-container">
          <div class="chat-messages" id="chat-box">
            ${msgHtml}
          </div>

          <div class="chips-container" style="margin: 8px 0;">
            <span class="chip" data-chat="Éteins toutes les lumières">💡 Éteins les lumières</span>
            <span class="chip" data-chat="Quelle est la température de la maison ?">🌡️ Température</span>
            <span class="chip" data-chat="Est-ce que des portes sont ouvertes ?">🚪 Portes ouvertes ?</span>
          </div>

          <div class="chat-input-bar">
            <select class="input-field" id="chat-camera-select" style="width: auto; margin-bottom: 0; padding: 12px; border-radius: 8px 0 0 8px; border-right: none;">
              <option value="">📸 Joindre une caméra...</option>
              ${Object.keys(this._hass.states).filter(id => id.startsWith("camera.")).map(id => `
                <option value="${id}">${this._hass.states[id].attributes.friendly_name || id}</option>
              `).join("")}
            </select>
            <input type="text" class="chat-input" id="chat-input-text" style="border-radius: 0; border-left: 1px solid var(--divider-color, #ccc);" placeholder="Parlez ou écrivez à Mistral AI..." value="${this._chatInput}">
            <button class="btn btn-primary" id="btn-chat-send" style="border-radius: 0 8px 8px 0;" ${this._isAssisting ? "disabled" : ""}>
              ${this._isAssisting ? '<span class="spinner"></span>' : 'Envoyer 📤'}
            </button>
          </div>
        </div>
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     ONGLET 5 : VISION & CAMÉRAS
     ═══════════════════════════════════════════════════════ */
  _renderVisionTab() {
    // Lister les caméras disponibles dans HA
    const cameraEntities = Object.keys(this._hass.states).filter(id => id.startsWith("camera."));

    let resultHtml = "";
    if (this._visionResult) {
      const v = this._visionResult;
      resultHtml = `
        <div class="card" style="border-left: 5px solid ${v.anomalies_detected || v.security_alert ? '#f44336' : '#4caf50'}; margin-top: 20px;">
          <h3 style="margin-top:0;">
            ${v.security_alert ? '🚨 Alerte Visuelle !' : '👁️ Analyse Pixtral Terminée'}
          </h3>
          <p style="font-weight:600; font-size:1.05em;">${v.summary || ""}</p>
          <p style="color: var(--secondary-text-color);">${v.description || ""}</p>
          
          ${v.objects_detected && v.objects_detected.length > 0 ? `
            <div style="margin-top: 12px;">
              <strong>Objets détectés :</strong>
              <div class="chips-container" style="margin-top:6px;">
                ${v.objects_detected.map(obj => `<span class="chip" style="cursor:default;">🔍 ${obj}</span>`).join("")}
              </div>
            </div>
          ` : ''}
        </div>
      `;
    }

    return `
      <div style="max-width: 800px; margin: 0 auto;">
        <div class="card">
          <h2 style="margin-top:0;">👁️ Vision & Surveillance par IA (Pixtral)</h2>
          <p style="color: var(--secondary-text-color);">
            Analysez en direct un snapshot de vos caméras pour détecter colis, présences humaines ou anomalies visuelles.
          </p>

          <label style="font-weight:600; display:block; margin-bottom:6px;">Sélectionner une caméra :</label>
          <select class="input-field" id="vision-camera-select">
            <option value="">-- Choisir une caméra (${cameraEntities.length} disponibles) --</option>
            ${cameraEntities.map(id => `
              <option value="${id}" ${this._selectedCamera === id ? 'selected' : ''}>
                ${this._hass.states[id].attributes.friendly_name || id} (${id})
              </option>
            `).join("")}
          </select>

          <label style="font-weight:600; display:block; margin-bottom:6px;">Question / Consigne d'analyse :</label>
          <textarea class="input-field" id="vision-prompt-input" rows="2">${this._visionPrompt}</textarea>

          <div style="display:flex; justify-content:flex-end;">
            <button class="btn btn-primary" id="btn-do-vision" ${this._isAnalyzingVision ? "disabled" : ""}>
              ${this._isAnalyzingVision ? '<span class="spinner"></span>Analyse Pixtral en cours...' : '📸 Capturer & Analyser'}
            </button>
          </div>
        </div>

        ${resultHtml}
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     ONGLET 6 : SMART BRIEFING
     ═══════════════════════════════════════════════════════ */
  _renderBriefingTab() {
    let resultHtml = "";
    if (this._briefingResult) {
      const b = this._briefingResult;
      resultHtml = `
        <div class="card" style="border: 2px solid var(--primary-color, #03a9f4); margin-top: 20px;">
          <h2 style="margin-top:0; color: var(--primary-color, #03a9f4);">🎙️ ${b.title || "Smart Briefing"}</h2>
          <div style="font-size: 1.1em; line-height: 1.6; padding: 14px; background: rgba(3,169,244,0.06); border-radius: 8px; margin-bottom: 14px;">
            ${b.speech_text || ""}
          </div>

          ${b.highlights && b.highlights.length > 0 ? `
            <ul>
              ${b.highlights.map(h => `<li>${h}</li>`).join("")}
            </ul>
          ` : ''}

          <div style="display:flex; gap:12px; justify-content:flex-end; margin-top:16px;">
            <button class="btn btn-ignore" id="btn-copy-briefing">📋 Copier</button>
            <button class="btn btn-success" id="btn-speak-briefing">🔊 Écouter (Vocal)</button>
          </div>
        </div>
      `;
    }

    return `
      <div style="max-width: 800px; margin: 0 auto;">
        <div class="card">
          <h2 style="margin-top:0;">📰 Smart Briefing Quotidien</h2>
          <p style="color: var(--secondary-text-color);">
            Générez une synthèse vocale intelligente de votre maison (météo, lumières oubliées, fenêtres ouvertes, batteries faibles).
          </p>

          <label style="font-weight:600; display:block; margin-bottom:6px;">Moment du briefing :</label>
          <select class="input-field" id="briefing-time-select">
            <option value="auto" ${this._briefingTimeOfDay === 'auto' ? 'selected' : ''}>⏱️ Automatique (selon l'heure)</option>
            <option value="morning" ${this._briefingTimeOfDay === 'morning' ? 'selected' : ''}>☀️ Matin (Réveil & Météo)</option>
            <option value="evening" ${this._briefingTimeOfDay === 'evening' ? 'selected' : ''}>🌙 Soir (Bilan & Sécurité)</option>
          </select>

          <label style="font-weight:600; display:block; margin-bottom:6px;">Consigne particulière (optionnelle) :</label>
          <input type="text" class="input-field" id="briefing-custom-input" placeholder="Ex: Inclus une citation motivante, sois très concis..." value="${this._briefingCustom}">

          <div style="display:flex; justify-content:flex-end;">
            <button class="btn btn-primary" id="btn-do-briefing" ${this._isGeneratingBriefing ? "disabled" : ""}>
              ${this._isGeneratingBriefing ? '<span class="spinner"></span>Génération du briefing...' : '📰 Générer le Briefing'}
            </button>
          </div>
        </div>

        ${resultHtml}
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     MODAL MANUELLE & BOITE DE CONFIRMATION AVEC DIFF
     ═══════════════════════════════════════════════════════ */
  _renderModal() {
    if (!this._selectedIssue) return "";
    const x = this._modalPos.x !== null ? this._modalPos.x : (window.innerWidth - 470);
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

    if (this._confirmData.actions && Array.isArray(this._confirmData.actions)) {
      for (const act of this._confirmData.actions) {
        if (act.action_type === "yaml_edit" || act.file) {
          diffHtml += `
            <div class="diff-container">
              <div class="diff-file-label">📄 Fichier cible : ${act.file}</div>
              ${act.find ? `<div class="diff-line-remove"><strong>- À remplacer :</strong><br>${act.find}</div>` : ''}
              ${act.replace ? `<div class="diff-line-add"><strong>+ Nouveau code :</strong><br>${act.replace}</div>` : ''}
              ${act.content ? `<div class="diff-line-add"><strong>+ Code injecté :</strong><br>${act.content}</div>` : ''}
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
            <button class="btn ${hasAction ? 'btn-auto' : 'btn-primary'}" id="btn-confirm-ok">${hasAction ? 'Confirmer & Appliquer' : 'Compris'}</button>
          </div>
        </div>
      </div>
    `;
  }

  /* ═══════════════════════════════════════════════════════
     GESTIONNAIRE D'ÉVÉNEMENTS
     ═══════════════════════════════════════════════════════ */
  _attachEvents() {
    const root = this.shadowRoot;

    // Navigation entre les 6 onglets
    root.querySelectorAll("[data-tab]").forEach(btn => {
      btn.addEventListener("click", () => {
        this._activeTab = btn.dataset.tab;
        this._render();
      });
    });

    // Bouton Quick Scan / Audit
    const btnQuickScan = root.getElementById("btn-quick-scan");
    if (btnQuickScan) {
      btnQuickScan.addEventListener("click", () => {
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    const btnRunFullAudit = root.getElementById("btn-run-full-audit");
    if (btnRunFullAudit) {
      btnRunFullAudit.addEventListener("click", () => {
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    const btnGotoRepair = root.getElementById("btn-goto-repair");
    if (btnGotoRepair) {
      btnGotoRepair.addEventListener("click", () => {
        this._activeTab = "repair";
        this._render();
      });
    }

    // Filtres d'anomalies
    root.querySelectorAll("[data-filter]").forEach(btn => {
      btn.addEventListener("click", () => {
        this._repairFilter = btn.dataset.filter;
        this._render();
      });
    });

    // Actions sur les anomalies (Manuel / Auto / Ignorer)
    root.querySelectorAll("[data-action]").forEach(btn => {
      btn.addEventListener("click", () => {
        const action = btn.dataset.action;
        const id = btn.dataset.id;
        const all = [...this._issues, ...this._ignoredIssues];
        const issue = all.find(i => i.id === id);

        if (action === "ignore") {
          this._hass.callService("domolink_mistral", "ignore_issue", { issue_id: id });
        } else if (action === "unignore") {
          this._hass.callService("domolink_mistral", "unignore_issue", { issue_id: id });
        } else if (action === "manual" && issue) {
          this._selectedIssue = issue;
          this._modalPos = { x: null, y: null };
          this._render();
        } else if (action === "auto" && issue) {
          const hasFix = issue.auto_fix_script && issue.auto_fix_script.length > 0;
          if (hasFix) {
            this._confirmData = {
              title: `🔧 Réparation : ${issue.title}`,
              message: "Une sauvegarde de sécurité (.bak) sera créée avant d'appliquer ce correctif :",
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
              message: "Aucun correctif automatique disponible pour ce problème. Suivez le guide « 📖 Manuel ».",
              onConfirm: null
            };
          }
          this._render();
        }
      });
    });

    // All Auto
    const btnAllAuto = root.getElementById("btn-allauto");
    if (btnAllAuto) {
      btnAllAuto.addEventListener("click", () => {
        const fixable = this._issues.filter(i => i.auto_fix_script && i.auto_fix_script.length > 0);
        const allActs = [];
        fixable.forEach(f => { if (Array.isArray(f.auto_fix_script)) allActs.push(...f.auto_fix_script); });

        this._confirmData = {
          title: "⚡ Exécuter All Auto",
          message: `Une sauvegarde globale (.bak) sera créée puis ${fixable.length} correctif(s) seront appliqués :`,
          actions: allActs,
          onConfirm: () => {
            this._isApplying = true;
            this._render();
            this._hass.callService("domolink_mistral", "apply_all_fixes", {});
          }
        };
        this._render();
      });
    }

    // Generator Events
    root.querySelectorAll(".chip[data-prompt]").forEach(chip => {
      chip.addEventListener("click", () => {
        const text = chip.dataset.prompt;
        const textarea = root.getElementById("gen-prompt-input");
        if (textarea) { textarea.value = text; this._genPrompt = text; }
      });
    });

    const genInput = root.getElementById("gen-prompt-input");
    if (genInput) {
      genInput.addEventListener("input", (e) => { this._genPrompt = e.target.value; });
    }

    const btnDoGen = root.getElementById("btn-do-generate");
    if (btnDoGen) {
      btnDoGen.addEventListener("click", async () => {
        const prompt = this._genPrompt.trim();
        if (!prompt) return;
        this._isGenerating = true;
        this._render();

        try {
          const resp = await this._hass.callService("domolink_mistral", "generate_automation", { prompt });
          if (resp && resp.response) this._generatedAutomation = resp.response;
        } catch (e) {
          console.error(e);
        } finally {
          this._isGenerating = false;
          this._render();
        }
      });
    }

    const btnCopyYaml = root.getElementById("btn-copy-yaml");
    if (btnCopyYaml && this._generatedAutomation) {
      btnCopyYaml.addEventListener("click", () => {
        navigator.clipboard.writeText(this._generatedAutomation.yaml || "");
        btnCopyYaml.textContent = "✅ Copié !";
        setTimeout(() => { if (btnCopyYaml) btnCopyYaml.textContent = "📋 Copier le YAML"; }, 2000);
      });
    }

    const btnSaveAuto = root.getElementById("btn-save-automation");
    if (btnSaveAuto && this._generatedAutomation) {
      btnSaveAuto.addEventListener("click", () => {
        this._confirmData = {
          title: `💾 Enregistrer l'automation`,
          message: `L'automation "${this._generatedAutomation.title}" sera injectée dans automations.yaml :`,
          actions: [{ file: "automations.yaml", content: this._generatedAutomation.yaml }],
          onConfirm: () => {
            this._hass.callService("domolink_mistral", "save_automation", { yaml: this._generatedAutomation.yaml });
            this._confirmData = {
              title: "🎉 Succès !",
              message: "Votre automation a été enregistrée et rechargée dans Home Assistant !",
              onConfirm: null
            };
            this._render();
          }
        };
        this._render();
      });
    }

    // Assist Chat Events
    const chatInput = root.getElementById("chat-input-text");
    if (chatInput) {
      chatInput.addEventListener("input", (e) => { this._chatInput = e.target.value; });
      chatInput.addEventListener("keypress", (e) => {
        if (e.key === "Enter") {
          const btnSend = root.getElementById("btn-chat-send");
          if (btnSend) btnSend.click();
        }
      });
    }

    root.querySelectorAll(".chip[data-chat]").forEach(chip => {
      chip.addEventListener("click", () => {
        const text = chip.dataset.chat;
        const input = root.getElementById("chat-input-text");
        if (input) { input.value = text; this._chatInput = text; }
        const btnSend = root.getElementById("btn-chat-send");
        if (btnSend) btnSend.click();
      });
    });

    const btnChatSend = root.getElementById("btn-chat-send");
    if (btnChatSend) {
      btnChatSend.addEventListener("click", async () => {
        const text = this._chatInput.trim();
        const camSelect = root.getElementById("chat-camera-select");
        const camId = camSelect ? camSelect.value : "";

        // Si aucun texte et aucune caméra, on ne fait rien
        if (!text && !camId) return;

        // Message par défaut si image seule
        const promptText = text || "Décris ce que tu vois.";

        let userMsg = text;
        if (camId) {
          const camName = this._hass.states[camId]?.attributes?.friendly_name || camId;
          userMsg = `📸 [${camName}] ${promptText}`;
        }

        this._chatMessages.push({ role: "user", text: userMsg || promptText, services: [] });
        this._chatInput = "";
        this._isAssisting = true;
        this._render();

        try {
          if (camId) {
            // Analyse Vision Multimodale (Pixtral)
            const resp = await this._hass.callService("domolink_mistral", "analyze_image", {
              camera_entity_id: camId,
              prompt: promptText
            });

            if (resp && resp.response) {
              const v = resp.response;
              let replyHtml = `<strong style="color:var(--primary-color);">👁️ Analyse de l'image :</strong><br>${v.summary || ""}<br><br><span style="opacity:0.9">${v.description || ""}</span>`;
              if (v.objects_detected && v.objects_detected.length > 0) {
                 replyHtml += `<div style="margin-top:8px;"><strong>Objets détectés :</strong> ${v.objects_detected.join(", ")}</div>`;
              }
              if (v.security_alert || v.anomalies_detected) {
                 replyHtml = `<span style="color:#f44336;">🚨 <strong>ALERTE DE SÉCURITÉ :</strong></span><br>${replyHtml}`;
              }
              this._chatMessages.push({ role: "assistant", text: replyHtml, services: [] });
            } else {
              this._chatMessages.push({ role: "assistant", text: "Erreur lors de l'analyse d'image.", services: [] });
            }
            
            // Réinitialiser la sélection de la caméra après l'envoi
            if (camSelect) camSelect.value = "";
          } else {
            // Chat texte normal
            const resp = await this._hass.callWS({
              type: "conversation/process",
              text: text,
              agent_id: "conversation.domolink_mistral_mistral_ai"
            });

            const speech = resp?.response?.speech?.plain?.speech || "Action effectuée.";
            this._chatMessages.push({ role: "assistant", text: speech, services: [] });
          }
        } catch (e) {
          this._chatMessages.push({
            role: "assistant",
            text: "Erreur de communication avec Mistral AI ou Home Assistant.",
            services: []
          });
        } finally {
          this._isAssisting = false;
          this._render();
          const chatBox = this.shadowRoot.getElementById("chat-box");
          if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;
        }
      });
    }

    // Vision Events
    const camSelect = root.getElementById("vision-camera-select");
    if (camSelect) {
      camSelect.addEventListener("change", (e) => { this._selectedCamera = e.target.value; });
    }
    const visPrompt = root.getElementById("vision-prompt-input");
    if (visPrompt) {
      visPrompt.addEventListener("input", (e) => { this._visionPrompt = e.target.value; });
    }

    const btnDoVision = root.getElementById("btn-do-vision");
    if (btnDoVision) {
      btnDoVision.addEventListener("click", async () => {
        if (!this._selectedCamera) {
          alert("Veuillez sélectionner une caméra.");
          return;
        }
        this._isAnalyzingVision = true;
        this._render();

        try {
          const resp = await this._hass.callService("domolink_mistral", "analyze_image", {
            camera_entity_id: this._selectedCamera,
            prompt: this._visionPrompt
          });
          if (resp && resp.response) {
            this._visionResult = resp.response;
          }
        } catch (e) {
          console.error(e);
        } finally {
          this._isAnalyzingVision = false;
          this._render();
        }
      });
    }

    // Briefing Events
    const briefTime = root.getElementById("briefing-time-select");
    if (briefTime) {
      briefTime.addEventListener("change", (e) => { this._briefingTimeOfDay = e.target.value; });
    }
    const briefCustom = root.getElementById("briefing-custom-input");
    if (briefCustom) {
      briefCustom.addEventListener("input", (e) => { this._briefingCustom = e.target.value; });
    }

    const btnDoBriefing = root.getElementById("btn-do-briefing");
    if (btnDoBriefing) {
      btnDoBriefing.addEventListener("click", async () => {
        this._isGeneratingBriefing = true;
        this._render();

        try {
          const resp = await this._hass.callService("domolink_mistral", "generate_daily_briefing", {
            time_of_day: this._briefingTimeOfDay,
            custom_instruction: this._briefingCustom
          });
          if (resp && resp.response) {
            this._briefingResult = resp.response;
          }
        } catch (e) {
          console.error(e);
        } finally {
          this._isGeneratingBriefing = false;
          this._render();
        }
      });
    }

    const btnSpeakBriefing = root.getElementById("btn-speak-briefing");
    if (btnSpeakBriefing && this._briefingResult) {
      btnSpeakBriefing.addEventListener("click", () => {
        if ('speechSynthesis' in window) {
          const utter = new SpeechSynthesisUtterance(this._briefingResult.speech_text || "");
          utter.lang = "fr-FR";
          window.speechSynthesis.speak(utter);
        }
      });
    }

    const btnCopyBriefing = root.getElementById("btn-copy-briefing");
    if (btnCopyBriefing && this._briefingResult) {
      btnCopyBriefing.addEventListener("click", () => {
        navigator.clipboard.writeText(this._briefingResult.speech_text || "");
        btnCopyBriefing.textContent = "✅ Copié !";
        setTimeout(() => { if (btnCopyBriefing) btnCopyBriefing.textContent = "📋 Copier"; }, 2000);
      });
    }

    // Confirmation listeners
    const btnCancel = root.getElementById("btn-confirm-cancel");
    if (btnCancel) {
      btnCancel.addEventListener("click", () => { this._confirmData = null; this._render(); });
    }
    const btnOk = root.getElementById("btn-confirm-ok");
    if (btnOk) {
      btnOk.addEventListener("click", () => {
        const cb = this._confirmData ? this._confirmData.onConfirm : null;
        this._confirmData = null;
        this._render();
        if (cb) cb();
      });
    }

    // Modal listeners
    const modalClose = root.getElementById("modal-close");
    if (modalClose) {
      modalClose.addEventListener("click", () => { this._selectedIssue = null; this._render(); });
    }

    const modalHeader = root.getElementById("modal-header");
    const modal = root.getElementById("modal");
    if (modalHeader && modal) {
      modalHeader.addEventListener("mousedown", (e) => {
        this._isDragging = true;
        this._dragOffset = { x: e.clientX - modal.offsetLeft, y: e.clientY - modal.offsetTop };
        e.preventDefault();
      });
      const onMove = (e) => {
        if (!this._isDragging) return;
        this._modalPos = { x: e.clientX - this._dragOffset.x, y: e.clientY - this._dragOffset.y };
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
