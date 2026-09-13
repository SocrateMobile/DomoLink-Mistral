/**
 * DomoLink-Mistral IA — Panneau Frontend Ultime pour Home Assistant
 *
 * 6 Onglets intégrés :
 * 1. 🛡️ Diagnostic & Audit (Logs, YAML, !includes, ESPHome, Blueprints, Entités)
 * 2. 🔧 Réparation Sécurisée (Actions 1-clic, Diff visuel avant/après, All Auto, Ignorés)
 * 3. ✨ Générateur IA (Création d'automations en langage naturel avec vraies entités)
 * 4. 🎙️ Assist Vocal & Écrit (Chat interactif avec tool-calling pour piloter la maison)
 * 5. 👁️ Vision & Surveillance (Analyse de caméras via Mistral Pixtral : colis, personnes, anomalies)
 * 6. 📰 Smart Briefing (Synthèse matinale/soirée avec lecture vocale TTS et résumé)
 *
 * Système de Mise à Jour Automatique 1-Clic :
 * - Détection des releases GitHub
 * - Pastille MAJ dans le menu latéral Home Assistant
 * - Bouton d'action dans le bandeau supérieur
 * - Bannière de notification et modale de Changelog
 * - Déploiement sécurisé avec sauvegarde et redémarrage automatique
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
    this._lastError = null;
    this._showIgnored = false;
    this._confirmData = null;
    this._initialized = false;
    this._repairFilter = "all"; // "all" | "high" | "medium" | "low"

    // Système de mise à jour
    this._updateInfo = null;
    this._showUpdateModal = false;
    this._isUpdatingComponent = false;
    this._updateStepText = "";
    this._updateProgress = 0;
    this._rebootCountdown = 0;
    this._sidebarInterval = null;

    // Onglet Générateur
    this._genPrompt = "";
    this._generatedAutomation = null;

    // Onglet Assist Chat
    this._chatInput = "";
    this._chatMessages = [
      {
        role: "assistant",
        text: "Bonjour ! Je suis votre assistant DomoLink-Mistral IA. Que puis-je faire pour vous aujourd'hui ?",
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

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    this._render();

    // Vérification initiale des mises à jour
    setTimeout(() => {
      this._checkUpdate();
    }, 1000);

    // Injection périodique et observateur de mutations dans la barre latérale HA
    this._sidebarInterval = setInterval(() => {
      this._injectSidebarBadge();
    }, 2500);

    try {
      const ha = document.querySelector("home-assistant");
      const main = ha && ha.shadowRoot && ha.shadowRoot.querySelector("home-assistant-main");
      const sidebar = main && main.shadowRoot && main.shadowRoot.querySelector("ha-sidebar");
      if (sidebar && sidebar.shadowRoot && !this._sidebarObserver) {
        this._sidebarObserver = new MutationObserver(() => {
          this._injectSidebarBadge();
        });
        this._sidebarObserver.observe(sidebar.shadowRoot, { childList: true, subtree: true });
      }
    } catch (e) {}

    // Écouter les événements bus HA
    if (window && window.addEventListener) {
      window.addEventListener("domolink_mistral_update_event", (e) => {
        if (e.detail) {
          this._updateInfo = e.detail;
          this._render();
          this._injectSidebarBadge();
        }
      });

      window.addEventListener("domolink_mistral_analysis_error", (e) => {
        if (e.detail && e.detail.error) {
          this._lastError = e.detail.error;
          this._isAnalyzing = false;
          this._render();
        }
      });
    }
  }

  disconnectedCallback() {
    if (this._sidebarInterval) {
      clearInterval(this._sidebarInterval);
    }
  }

  set hass(hass) {
    this._hass = hass;
    try {
      const changed = this._updateFromSensor();
      this._checkUpdateFromEntities();

      if (!this._initialized || changed) {
        this._initialized = true;
        this._render();
        this._injectSidebarBadge();
      }
    } catch (err) {
      console.error("DomoLink-Mistral IA set hass error:", err);
    }
  }

  _checkUpdateFromEntities() {
    if (!this._hass) return;
    const updateEntityId = Object.keys(this._hass.states).find(
      (id) => id.startsWith("update.") && id.includes("domolink")
    );
    if (updateEntityId && this._hass.states[updateEntityId]) {
      const stateObj = this._hass.states[updateEntityId];
      const attrs = stateObj.attributes || {};
      const hasUpdate = stateObj.state === "on";

      if (!this._updateInfo || this._updateInfo.has_update !== hasUpdate) {
        this._updateInfo = {
          has_update: hasUpdate,
          current_version: attrs.installed_version || "2.9.13",
          latest_version: attrs.latest_version || attrs.installed_version || "2.9.13",
          release_tag: `v${attrs.latest_version || "2.9.13"}`,
          release_url: attrs.release_url || "https://github.com/SocrateMobile/DomoLink-Mistral/releases",
          changelog: attrs.release_summary || "Notes de version disponibles sur GitHub.",
          is_updating: attrs.in_progress || false
        };
        this._injectSidebarBadge();
      }
    }
  }

  async _checkUpdate() {
    if (!this._hass) return;
    try {
      const res = await this._hass.callService("domolink_mistral", "check_update", {});
      if (res && res.response) {
        this._updateInfo = res.response;
        this._render();
        this._injectSidebarBadge();
      }
    } catch (e) {
      console.debug("DomoLink-Mistral IA: Check update skipped:", e);
    }
  }

  async _startAutoUpdate() {
    this._isUpdatingComponent = true;
    this._updateProgress = 15;
    this._updateStepText = "📦 [1/4] Téléchargement de la release GitHub...";
    this._render();

    try {
      setTimeout(() => {
        if (this._isUpdatingComponent) {
          this._updateProgress = 45;
          this._updateStepText = "🛡️ [2/4] Création de la sauvegarde locale du composant...";
          this._render();
        }
      }, 1500);

      setTimeout(() => {
        if (this._isUpdatingComponent) {
          this._updateProgress = 75;
          this._updateStepText = "⚡ [3/4] Déploiement des nouveaux fichiers...";
          this._render();
        }
      }, 3000);

      try {
        await this._hass.callService("domolink_mistral", "perform_update", {
          restart: true,
          backup: true,
        });
      } catch (err) {
        await this._hass.callService("domolink_mistral", "install_update", {
          restart: true,
          backup: true,
        });
      }

      this._updateProgress = 100;
      this._updateStepText = "🔄 [4/4] Redémarrage de Home Assistant...";
      this._render();

      this._startRebootSequence();

    } catch (e) {
      this._isUpdatingComponent = false;
      this._updateStepText = `❌ Échec : ${e.message || e}`;
      this._render();
    }
  }

  _startRebootSequence() {
    this._rebootCountdown = 30;
    const interval = setInterval(() => {
      this._rebootCountdown--;
      this._render();

      if (this._rebootCountdown <= 20) {
        fetch("/api/states", { method: "HEAD", cache: "no-store" })
          .then((r) => {
            if (r.ok || r.status === 401 || r.status === 200) {
              clearInterval(interval);
              window.location.reload();
            }
          })
          .catch(() => {});
      }

      if (this._rebootCountdown <= 0) {
        clearInterval(interval);
        window.location.reload();
      }
    }, 1000);
  }

  _injectSidebarBadge() {
    try {
      const hasUpdate = Boolean(this._updateInfo && this._updateInfo.has_update);
      const ha = document.querySelector("home-assistant");
      const main = ha && ha.shadowRoot && ha.shadowRoot.querySelector("home-assistant-main");
      const sidebar = main && main.shadowRoot && main.shadowRoot.querySelector("ha-sidebar");
      if (!sidebar || !sidebar.shadowRoot) return;

      const integrations = [
        {
          key: "domolink_mistral",
          patterns: ["domolink_mistral", "domolink-mistral"],
          entityIds: ["update.domolink_mistralia", "update.domolink_mistral", "update.domolink_mistral_mise_a_jour"],
          hasUpdate: hasUpdate,
        },
        {
          key: "domolink_alarm",
          patterns: ["domolink_alarm", "domolink-alarm"],
          entityIds: ["update.domolink_alarm", "update.domolink_alarm_mise_a_jour"],
          hasUpdate: undefined,
        },
        {
          key: "domolink_backup",
          patterns: ["domolink_backup", "domolink-backup"],
          entityIds: ["update.domolink_backup", "update.domolink_backup_mise_a_jour"],
          hasUpdate: undefined,
        },
        {
          key: "flipr_pool",
          patterns: ["flipr_pool", "flipr-pool", "flipr-pool-control", "flipr"],
          entityIds: ["update.flipr_pool_control", "update.flipr_pool", "update.flipr_pool_mise_a_jour"],
          hasUpdate: undefined,
        },
      ];

      const container = sidebar.shadowRoot.querySelector("paper-listbox, ha-md-list, nav, div.menu, div.items");
      const items = (container || sidebar.shadowRoot).querySelectorAll("paper-icon-item, ha-md-list-item, ha-sidebar-item, a");

      integrations.forEach((integ) => {
        let isUpdateAvail = integ.hasUpdate;
        if (isUpdateAvail === undefined && this._hass && this._hass.states) {
          isUpdateAvail = integ.entityIds.some((id) => {
            const st = this._hass.states[id];
            return st && (st.state === "on" || (st.attributes && st.attributes.update_available === true));
          });
        }

        for (const item of items) {
          const href = item.getAttribute("href") || (item.dataset && (item.dataset.panel || item.dataset.href)) || "";
          const id = item.id || "";
          const ariaLabel = item.getAttribute("aria-label") || "";
          const text = (item.textContent || "").toLowerCase();

          const isMatch = integ.patterns.some((pat) => {
            const p = pat.toLowerCase();
            return href.toLowerCase().includes(p) ||
                   id.toLowerCase().includes(p) ||
                   ariaLabel.toLowerCase().includes(p.replace(/_/g, " ")) ||
                   (p === "flipr" && text.includes("flipr"));
          });

          if (isMatch) {
            let badge = item.querySelector(".domolink-sidebar-badge");
            if (isUpdateAvail) {
              if (!badge) {
                badge = document.createElement("span");
                badge.className = "badge domolink-sidebar-badge";
                badge.setAttribute("slot", "end");
                badge.style.cssText = "background: linear-gradient(135deg, #ef4444, #f59e0b); color: white; border-radius: 9999px; padding: 2px 7px; font-size: 10px; font-weight: 800; box-shadow: 0 2px 6px rgba(239,68,68,0.4); margin-left: auto; letter-spacing: 0.5px; z-index: 10; display: inline-block;";
                badge.textContent = "MAJ";
                badge.title = "Mise à jour disponible !";
                item.appendChild(badge);
              }
            } else if (badge) {
              badge.remove();
            }
          }
        }
      });
    } catch (e) {
      // Ignorer les erreurs de traversée DOM
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
      const newLastError = attrs.last_error || null;
      const newIssues = attrs.issues || [];
      const newIgnored = attrs.ignored_issues || [];

      const changed = (
        newLast !== this._lastAnalysis ||
        newStatus !== this._currentStatus ||
        newLastError !== this._lastError ||
        newIssues.length !== this._issues.length ||
        newIgnored.length !== this._ignoredIssues.length
      );

      this._issues = newIssues;
      this._ignoredIssues = newIgnored;
      this._lastAnalysis = newLast;
      this._currentStatus = newStatus;
      this._lastError = newLastError;

      // Arrêter les spinners
      if (this._isAnalyzing && (newStatus.includes("terminée") || newStatus.includes("Erreur") || newStatus.includes("✅") || newStatus.includes("❌") || newStatus.includes("🚫"))) {
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

  _escapeHtml(str) {
    if (!str) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
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

        /* ── Bouton Animation MAJ ── */
        .btn-update-pulse {
          background: linear-gradient(135deg, #ff416c, #ff4b2b);
          color: white;
          border: none;
          padding: 10px 18px;
          border-radius: 8px;
          font-weight: 700;
          font-size: 0.9em;
          cursor: pointer;
          display: inline-flex;
          align-items: center;
          gap: 8px;
          box-shadow: 0 4px 15px rgba(255, 65, 108, 0.4);
          animation: btn-pulse 2s infinite;
          transition: transform 0.2s, box-shadow 0.2s;
        }
        .btn-update-pulse:hover {
          transform: translateY(-2px);
          box-shadow: 0 6px 20px rgba(255, 65, 108, 0.6);
        }

        @keyframes btn-pulse {
          0% { box-shadow: 0 0 0 0 rgba(255, 65, 108, 0.7); }
          70% { box-shadow: 0 0 0 12px rgba(255, 65, 108, 0); }
          100% { box-shadow: 0 0 0 0 rgba(255, 65, 108, 0); }
        }

        /* ── Bannière de Mise à Jour ── */
        .update-banner {
          background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%);
          color: white;
          padding: 16px 20px;
          border-radius: 12px;
          margin-bottom: 20px;
          display: flex;
          align-items: center;
          justify-content: space-between;
          flex-wrap: wrap;
          gap: 14px;
          box-shadow: 0 6px 18px rgba(30, 60, 114, 0.25);
          border-left: 6px solid #ff4b2b;
        }

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
        .btn:hover { opacity: 0.9; }
        .btn:disabled { opacity: 0.5; cursor: not-allowed; }
        .btn-primary { background: var(--primary-color, #03a9f4); }
        .btn-success { background: #4caf50; }
        .btn-warning { background: #ff9800; }
        .btn-danger { background: #f44336; }
        .btn-secondary { background: var(--secondary-text-color, #757575); }

        .stats-bar {
          display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap;
        }
        .stat-chip {
          background: var(--card-background-color, #fff);
          padding: 8px 16px; border-radius: 20px; font-size: 0.85em;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: flex; align-items: center; gap: 6px;
        }

        .card {
          background: var(--card-background-color, #fff);
          border-radius: 12px;
          padding: 20px;
          box-shadow: 0 2px 8px rgba(0,0,0,0.08);
          margin-bottom: 16px;
        }

        .issue-card {
          background: var(--card-background-color, #fff);
          border-radius: 10px;
          padding: 16px;
          margin-bottom: 12px;
          box-shadow: 0 2px 6px rgba(0,0,0,0.06);
          border-left: 5px solid #9e9e9e;
          transition: transform 0.15s;
        }
        .issue-card:hover { transform: translateY(-2px); }

        .badge {
          display: inline-block; padding: 3px 8px; border-radius: 4px;
          font-size: 0.75em; font-weight: bold; color: white;
        }

        .code-block {
          background: #1e1e1e; color: #d4d4d4; padding: 12px;
          border-radius: 8px; font-family: monospace; font-size: 0.85em;
          white-space: pre-wrap; overflow-x: auto; margin: 10px 0;
        }

        /* ── Modales ── */
        .modal-overlay {
          position: fixed; top: 0; left: 0; width: 100vw; height: 100vh;
          background: rgba(0,0,0,0.5); z-index: 9999;
          display: flex; align-items: center; justify-content: center;
        }
        .modal {
          background: var(--card-background-color, #fff);
          border-radius: 12px; padding: 24px;
          max-width: 650px; width: 90%; max-height: 85vh;
          overflow-y: auto; box-shadow: 0 8px 32px rgba(0,0,0,0.25);
        }

        .modal-floating {
          position: fixed;
          width: 480px;
          max-width: 90vw;
          max-height: 80vh;
          background: var(--card-background-color, #ffffff);
          border-radius: 12px;
          box-shadow: 0 8px 32px rgba(0,0,0,0.25);
          z-index: 10000;
          display: flex;
          flex-direction: column;
          border: 1px solid var(--divider-color, #e0e0e0);
          overflow: hidden;
        }

        /* Barre de progression */
        .progress-bar-bg {
          background: #e0e0e0;
          border-radius: 8px;
          height: 12px;
          overflow: hidden;
          margin: 16px 0;
        }
        .progress-bar-fill {
          background: linear-gradient(90deg, #4caf50, #8bc34a);
          height: 100%;
          transition: width 0.4s ease;
        }

        .loading-overlay {
          display: flex; flex-direction: column; align-items: center; justify-content: center;
          padding: 60px 20px; text-align: center;
        }
        .spinner {
          display: inline-block; width: 16px; height: 16px;
          border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff;
          border-radius: 50%; animation: spin 0.8s linear infinite;
        }
        .big-spinner {
          width: 48px; height: 48px; border: 4px solid var(--divider-color, #e0e0e0);
          border-top-color: var(--primary-color, #03a9f4); border-radius: 50%;
          animation: spin 0.8s linear infinite; margin-bottom: 20px;
        }
        @keyframes spin { to { transform: rotate(360deg); } }

        @media (max-width: 700px) {
          :host { padding: 12px; }
          .modal { width: calc(100% - 24px) !important; left: 12px !important; }
        }
      </style>

      ${this._renderHeader()}
      ${this._renderUpdateBanner()}
      ${this._renderErrorBanner()}
      ${this._renderTabs()}

      ${this._renderActiveTabContent()}

      ${this._renderModal()}
      ${this._renderConfirmDialog()}
      ${this._renderUpdateModal()}
    `;

    this._attachEvents();
  }

  _renderErrorBanner() {
    if (!this._lastError && !(this._currentStatus && this._currentStatus.startsWith("❌"))) return "";
    const errorText = this._lastError || this._currentStatus.replace(/^❌\s*/, "");
    const isRateLimit = errorText.includes("429") || errorText.toLowerCase().includes("too many requests") || errorText.toLowerCase().includes("quota");

    return `
      <div style="background: linear-gradient(135deg, #c62828, #b71c1c); color: white; padding: 16px 20px; border-radius: 12px; margin-bottom: 20px; box-shadow: 0 4px 15px rgba(198, 40, 40, 0.35); border-left: 6px solid #ffeb3b;">
        <div style="display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; flex-wrap: wrap;">
          <div style="display: flex; gap: 12px; align-items: flex-start; flex: 1; min-width: 280px;">
            <span style="font-size: 1.8em;">${isRateLimit ? "🚫" : "⚠️"}</span>
            <div>
              <div style="font-weight: 700; font-size: 1.05em; margin-bottom: 4px;">
                ${isRateLimit ? "Limite de requêtes Mistral AI atteinte (HTTP 429 : Too Many Requests)" : "Erreur de communication avec Mistral AI"}
              </div>
              <div style="font-size: 0.9em; line-height: 1.4; opacity: 0.95;">
                ${this._escapeHtml(errorText)}
              </div>
              ${isRateLimit ? `
                <div style="margin-top: 10px; font-size: 0.85em; background: rgba(0,0,0,0.25); padding: 8px 12px; border-radius: 6px; line-height: 1.4;">
                  💡 <strong>Comment résoudre :</strong> Votre palier de requêtes par minute ou vos crédits API sont temporairement épuisés.<br/>
                  Consultez votre consommation et vos quotas sur <a href="https://console.mistral.ai" target="_blank" rel="noopener" style="color: #ffeb3b; text-decoration: underline; font-weight: bold;">console.mistral.ai</a> ou patientez 1 à 2 minutes avant de relancer l'audit.
                </div>
              ` : `
                <div style="margin-top: 8px; font-size: 0.85em; opacity: 0.9;">
                  💡 Vérifiez votre connexion internet ou votre clé API dans les paramètres de l'intégration.
                </div>
              `}
            </div>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <button class="btn btn-warning" id="btn-retry-scan" style="background: white; color: #b71c1c; font-weight: bold;">
              🔄 Relancer l'Audit
            </button>
            <button id="btn-dismiss-error" style="background: none; border: none; color: white; font-size: 1.4em; cursor: pointer; opacity: 0.8;" title="Fermer cette alerte">&times;</button>
          </div>
        </div>
      </div>
    `;
  }

  _renderHeader() {
    const hasUpdate = this._updateInfo && this._updateInfo.has_update;
    return `
      <div class="header">
        <div style="display: flex; align-items: center; gap: 12px;">
          <img src="/domolink_mistral_frontend/icon.png" alt="Logo" style="width: 38px; height: 38px; border-radius: 8px;" />
          <div>
            <h1 style="margin: 0; font-size: 1.4em; line-height: 1.2;">
              DomoLink-Mistral IA
              <span style="font-size: 0.6em; color: var(--secondary-text-color, #757575); font-weight: normal; margin-left: 8px; vertical-align: middle;">
                v${this._updateInfo?.current_version || "2.9.13"}
              </span>
            </h1>
            <div class="header-info">Dernière analyse : ${this._timeAgo(this._lastAnalysis)}</div>
          </div>
        </div>
        <div style="display: flex; align-items: center; gap: 10px;">
          ${hasUpdate ? `
            <button class="btn-update-pulse" id="btn-header-update">
              🚀 Mise à jour ${this._updateInfo.release_tag}
            </button>
          ` : ""}
          <button class="btn btn-primary" id="btn-quick-scan" ${this._isAnalyzing ? "disabled" : ""}>
            ${this._isAnalyzing ? '<span class="spinner"></span>Audit en cours...' : "🔍 Lancer l'Audit"}
          </button>
        </div>
      </div>
    `;
  }

  _renderUpdateBanner() {
    if (!this._updateInfo || !this._updateInfo.has_update) return "";
    return `
      <div class="update-banner">
        <div style="display: flex; align-items: center; gap: 14px;">
          <span style="font-size: 2em;">🚀</span>
          <div>
            <div style="font-weight: 700; font-size: 1.1em; color: #ffeb3b;">
              Nouvelle version disponible : ${this._updateInfo.release_tag}
            </div>
            <div style="font-size: 0.85em; opacity: 0.95;">
              Version actuelle : v${this._updateInfo.current_version} &bull; Sauvegarde préalable automatique et déploiement 1-clic.
            </div>
          </div>
        </div>
        <div style="display: flex; gap: 8px;">
          <button class="btn btn-secondary" id="btn-banner-changelog" style="background: rgba(255,255,255,0.2);">
            📋 Changelog
          </button>
          <button class="btn btn-warning" id="btn-banner-update" style="background: #ff4b2b; color: white; font-weight: bold;">
            ⚡ Mettre à jour en 1-Clic
          </button>
        </div>
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
            DomoLink-Mistral IA inspecte en continu vos logs, votre configuration YAML récursive, vos périphériques ESPHome, vos Blueprints et l'état de toutes vos entités.
          </p>

          <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 14px; margin: 20px 0;">
            <div style="background: rgba(3,169,244,0.06); padding: 14px; border-radius: 10px; border: 1px solid rgba(3,169,244,0.15);">
              <div style="font-size: 1.3em;">📜 <strong>Journaux & Erreurs</strong></div>
              <p style="font-size: 0.85em; color: var(--secondary-text-color); margin: 6px 0 0 0;">
                Analyse sémantique des stacktraces et warnings Home Assistant.
              </p>
            </div>
            <div style="background: rgba(76,175,80,0.06); padding: 14px; border-radius: 10px; border: 1px solid rgba(76,175,80,0.15);">
              <div style="font-size: 1.3em;">📑 <strong>YAML & Includes</strong></div>
              <p style="font-size: 0.85em; color: var(--secondary-text-color); margin: 6px 0 0 0;">
                Inspection récursive de configuration.yaml, scripts, scenes et packages.
              </p>
            </div>
            <div style="background: rgba(255,152,0,0.06); padding: 14px; border-radius: 10px; border: 1px solid rgba(255,152,0,0.15);">
              <div style="font-size: 1.3em;">⚡ <strong>ESPHome & Blueprints</strong></div>
              <p style="font-size: 0.85em; color: var(--secondary-text-color); margin: 6px 0 0 0;">
                Contrôle des devices hors-ligne et schémas d'automations communautaires.
              </p>
            </div>
          </div>

          <div style="display: flex; gap: 10px; flex-wrap: wrap; align-items: center; margin-top: 20px;">
            <button class="btn btn-primary" id="btn-tab-audit-scan">
              🔍 Lancer un Audit Complet
            </button>
            <button class="btn btn-secondary" id="btn-tab-repair-goto">
              🔧 Accéder aux ${this._issues.length} Réparation(s)
            </button>
            <button class="btn btn-secondary" id="btn-check-update-manual" style="margin-left: auto;">
              🔄 Vérifier les Mises à Jour
            </button>
          </div>
        </div>
      </div>
    `;
  }

  _renderRepairTab() {
    let filtered = this._issues;
    if (this._repairFilter !== "all") {
      filtered = filtered.filter(i => i.severity === this._repairFilter);
    }

    const autoFixCount = this._issues.filter(i => i.auto_fix_script && i.auto_fix_script.length > 0).length;

    return `
      <div>
        <div style="display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px; margin-bottom: 16px;">
          <div style="display: flex; gap: 8px; flex-wrap: wrap;">
            <button class="btn ${this._repairFilter === "all" ? "btn-primary" : "btn-secondary"}" id="btn-filter-all">
              Toutes (${this._issues.length})
            </button>
            <button class="btn ${this._repairFilter === "high" ? "btn-danger" : "btn-secondary"}" id="btn-filter-high">
              🔴 Critiques
            </button>
            <button class="btn ${this._repairFilter === "medium" ? "btn-warning" : "btn-secondary"}" id="btn-filter-med">
              🟠 Moyennes
            </button>
            <button class="btn ${this._repairFilter === "low" ? "btn-success" : "btn-secondary"}" id="btn-filter-low">
              🟢 Faibles
            </button>
          </div>



          <div style="display: flex; gap: 8px;">
            <button class="btn btn-warning" id="btn-repair-all" ${autoFixCount === 0 || this._isApplying ? "disabled" : ""}>
              ⚡ Corriger Tout (All Auto: ${autoFixCount})
            </button>
            <button class="btn btn-danger" id="btn-rollback" title="Annuler la dernière modification YAML">
              ⏪ Rollback
            </button>

            <button class="btn btn-secondary" id="btn-toggle-ignored">

              ${this._showIgnored ? "Masquer les ignorés" : `Afficher les ignorés (${this._ignoredIssues.length})`}
            </button>
          </div>
        </div>

        ${filtered.length === 0 ? `
          <div class="card" style="text-align: center; padding: 40px 20px;">
            <div style="font-size: 3em; margin-bottom: 10px;">🎉</div>
            <h3>Aucune anomalie détectée dans cette catégorie !</h3>
            <p style="color: var(--secondary-text-color);">Votre installation Home Assistant est saine et optimisée.</p>
          </div>
        ` : filtered.map(issue => this._renderIssueCard(issue)).join("")}

        ${this._showIgnored && this._ignoredIssues.length > 0 ? `
          <div style="margin-top: 30px;">
            <h3>Erreurs ignorées</h3>
            ${this._ignoredIssues.map(id => `
              <div class="issue-card" style="opacity: 0.7;">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <span>ID : <code>${this._escapeHtml(id)}</code></span>
                  <button class="btn btn-secondary btn-unignore" data-id="${this._escapeHtml(id)}">
                    ↩️ Réactiver
                  </button>
                </div>
              </div>
            `).join("")}
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderIssueCard(issue) {
    const hasAuto = issue.auto_fix_script && issue.auto_fix_script.length > 0;
    const borderColor = this._severityColor(issue.severity);

    return `
      <div class="issue-card" style="border-left-color: ${borderColor};">
        <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 8px;">
          <div>
            <span class="badge" style="background: ${borderColor};">${this._severityLabel(issue.severity)}</span>
            <span class="badge" style="background: rgba(0,0,0,0.1); color: var(--primary-text-color); margin-left: 6px;">
              ${this._categoryIcon(issue.category)}
            </span>
            <h3 style="margin: 8px 0 4px 0; font-size: 1.1em;">${this._escapeHtml(issue.title || "Anomalie détectée")}</h3>
          </div>
          <div style="display: flex; gap: 6px;">
            <button class="btn btn-secondary btn-ignore" data-id="${this._escapeHtml(issue.id)}" title="Ignorer cette alerte">
              👁️ Ignorer
            </button>
            <button class="btn btn-primary btn-manual" data-id="${this._escapeHtml(issue.id)}">
              📖 Manuel
            </button>
            ${hasAuto ? `
              <button class="btn btn-success btn-autofix" data-id="${this._escapeHtml(issue.id)}">
                ⚡ Auto-Fix
              </button>
            ` : ""}
          </div>
        </div>

        <p style="margin: 6px 0; font-size: 0.9em; color: var(--primary-text-color);">
          ${this._escapeHtml(issue.description || "")}
        </p>

        ${issue.file ? `
          <div style="font-size: 0.8em; color: var(--secondary-text-color); margin-top: 6px;">
            📁 Fichier concerné : <code>${this._escapeHtml(issue.file)}</code> ${issue.line ? `(Ligne ${issue.line})` : ""}
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderGeneratorTab() {
    return `
      <div class="card">
        <h2 style="margin-top:0;">✨ Générateur d'Automations par IA</h2>
        <p style="color: var(--secondary-text-color);">
          Décrivez ce que vous souhaitez automatiser en langage naturel. Mistral générera le code YAML adapté en utilisant vos véritables entités.
        </p>

        <textarea id="gen-prompt-input" rows="4" style="width: 100%; border-radius: 8px; padding: 12px; font-family: inherit; font-size: 0.95em; border: 1px solid var(--divider-color, #ccc); box-sizing: border-box;" placeholder="Exemple : Quand la porte du garage s'ouvre après 22h, allume les lumières du salon en rouge et envoie une notification sur mon téléphone.">${this._escapeHtml(this._genPrompt)}</textarea>

        <div style="margin-top: 14px;">
          <button class="btn btn-primary" id="btn-do-generate" ${this._isGenerating ? "disabled" : ""}>
            ${this._isGenerating ? '<span class="spinner"></span>Génération en cours...' : "✨ Générer l'automation"}
          </button>
        </div>

        ${this._generatedAutomation ? `
          <div style="margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--divider-color, #e0e0e0);">
            <h3>${this._escapeHtml(this._generatedAutomation.title || "Nouvelle automation")}</h3>
            <p>${this._escapeHtml(this._generatedAutomation.description || "")}</p>
            <div class="code-block">${this._escapeHtml(this._generatedAutomation.yaml || "")}</div>
            <button class="btn btn-success" id="btn-save-generated-auto">
              💾 Injecter dans automations.yaml
            </button>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderAssistTab() {
    return `
      <div class="card" style="display: flex; flex-direction: column; height: 600px;">
        <h2 style="margin-top:0;">🎙️ DomoLink Assist Agent</h2>
        <div id="chat-box" style="flex: 1; overflow-y: auto; padding: 12px; background: rgba(0,0,0,0.02); border-radius: 8px; margin-bottom: 12px; display: flex; flex-direction: column; gap: 10px;">
          ${this._chatMessages.map(msg => `
            <div style="align-self: ${msg.role === "user" ? "flex-end" : "flex-start"}; background: ${msg.role === "user" ? "var(--primary-color, #03a9f4)" : "var(--card-background-color, #fff)"}; color: ${msg.role === "user" ? "#fff" : "var(--primary-text-color)"}; padding: 10px 14px; border-radius: 12px; max-width: 80%; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
              <div>${this._escapeHtml(msg.text)}</div>
              ${msg.services && msg.services.length > 0 ? `
                <div style="margin-top: 6px; font-size: 0.75em; opacity: 0.85;">
                  ⚡ Action exécutée : <code>${this._escapeHtml(msg.services.join(", "))}</code>
                </div>
              ` : ""}
            </div>
          `).join("")}
        </div>

        <div style="display: flex; gap: 8px;">
          <input type="text" id="chat-input" value="${this._escapeHtml(this._chatInput)}" placeholder="Tapez une commande ou posez une question..." style="flex: 1; padding: 10px 14px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); font-family: inherit;" />
          <button class="btn btn-primary" id="btn-chat-send" ${this._isAssisting ? "disabled" : ""}>
            ${this._isAssisting ? '<span class="spinner"></span>' : 'Envoyer'}
          </button>
        </div>
      </div>
    `;
  }

  _renderVisionTab() {
    const cameras = this._hass && this._hass.states ? Object.keys(this._hass.states).filter(id => id.startsWith("camera.")) : [];

    return `
      <div class="card">
        <h2 style="margin-top:0;">👁️ Surveillance Intelligente Pixtral Vision</h2>
        <p style="color: var(--secondary-text-color);">
          Analysez instantanément les flux de vos caméras pour détecter colis, présences suspectes ou anomalies.
        </p>

        <div style="margin-bottom: 14px;">
          <label style="font-weight: 600; font-size: 0.9em; display: block; margin-bottom: 6px;">Sélectionner une caméra :</label>
          <select id="vision-camera-select" style="width: 100%; padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); font-family: inherit;">
            <option value="">-- Choisir une caméra --</option>
            ${cameras.map(cam => `
              <option value="${cam}" ${this._selectedCamera === cam ? "selected" : ""}>${cam}</option>
            `).join("")}
          </select>
        </div>

        <div style="margin-bottom: 14px;">
          <label style="font-weight: 600; font-size: 0.9em; display: block; margin-bottom: 6px;">Instructions pour Pixtral :</label>
          <input type="text" id="vision-prompt-input" value="${this._escapeHtml(this._visionPrompt)}" style="width: 100%; padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); font-family: inherit; box-sizing: border-box;" />
        </div>

        <button class="btn btn-primary" id="btn-do-vision" ${this._isAnalyzingVision ? "disabled" : ""}>
          ${this._isAnalyzingVision ? '<span class="spinner"></span>Analyse de l\'image...' : "📸 Analyser la caméra"}
        </button>

        ${this._visionResult ? `
          <div style="margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--divider-color, #e0e0e0);">
            <h3>Résultat de l'analyse</h3>
            <p><strong>Résumé :</strong> ${this._escapeHtml(this._visionResult.summary || "")}</p>
            <p><strong>Détails :</strong> ${this._escapeHtml(this._visionResult.description || "")}</p>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderBriefingTab() {
    return `
      <div class="card">
        <h2 style="margin-top:0;">📰 Smart Daily Briefing</h2>
        <p style="color: var(--secondary-text-color);">
          Mistral compile l'état de votre maison (météo, lumières, ouvertures, batteries) et vous offre une synthèse vocale et visuelle personnalisée.
        </p>

        <div style="display: flex; gap: 12px; margin-bottom: 14px; flex-wrap: wrap;">
          <select id="briefing-time-select" style="padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); font-family: inherit;">
            <option value="auto" ${this._briefingTimeOfDay === "auto" ? "selected" : ""}>Automatique</option>
            <option value="morning" ${this._briefingTimeOfDay === "morning" ? "selected" : ""}>Matin</option>
            <option value="evening" ${this._briefingTimeOfDay === "evening" ? "selected" : ""}>Soir</option>
          </select>
          <input type="text" id="briefing-custom-input" placeholder="Instruction spéciale (ex: Ajoute une citation motivante)" value="${this._escapeHtml(this._briefingCustom)}" style="flex: 1; min-width: 250px; padding: 10px; border-radius: 8px; border: 1px solid var(--divider-color, #ccc); font-family: inherit;" />
        </div>

        <button class="btn btn-primary" id="btn-do-briefing" ${this._isGeneratingBriefing ? "disabled" : ""}>
          ${this._isGeneratingBriefing ? '<span class="spinner"></span>Génération du briefing...' : '📰 Générer le Briefing'}
        </button>

        ${this._briefingResult ? `
          <div style="margin-top: 24px; padding-top: 20px; border-top: 1px solid var(--divider-color, #e0e0e0);">
            <h3>${this._escapeHtml(this._briefingResult.title || "Smart Briefing")}</h3>
            <p style="font-size: 1.05em; line-height: 1.5;">${this._escapeHtml(this._briefingResult.speech_text || "")}</p>
            <div style="display: flex; gap: 8px; margin-top: 14px;">
              <button class="btn btn-success" id="btn-speak-briefing">🔊 Écouter</button>
              <button class="btn btn-secondary" id="btn-copy-briefing">📋 Copier</button>
            </div>
          </div>
        ` : ""}
      </div>
    `;
  }

  _renderUpdateModal() {
    if (!this._showUpdateModal || !this._updateInfo) return "";

    return `
      <div class="modal-overlay">
        <div class="modal" style="max-width: 600px;">
          <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
            <h2 style="margin: 0; display: flex; align-items: center; gap: 8px;">
              🚀 Mise à jour DomoLink-Mistral IA
            </h2>
            ${!this._isUpdatingComponent ? `
              <button id="btn-close-update-modal" style="background: none; border: none; font-size: 1.4em; cursor: pointer;">&times;</button>
            ` : ""}
          </div>

          <div style="background: rgba(3,169,244,0.08); padding: 12px 16px; border-radius: 8px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center;">
            <div>
              <strong>Version installée :</strong> v${this._escapeHtml(this._updateInfo.current_version)}
            </div>
            <div style="font-size: 1.2em;">➔</div>
            <div>
              <strong>Nouvelle version :</strong> <span style="color: #ff416c; font-weight: bold;">${this._escapeHtml(this._updateInfo.release_tag)}</span>
            </div>
          </div>

          ${this._isUpdatingComponent ? `
            <div style="text-align: center; padding: 20px 0;">
              <div class="big-spinner" style="margin: 0 auto 16px auto;"></div>
              <h3 style="margin: 0 0 8px 0;">Mise à jour en cours...</h3>
              <p style="color: var(--primary-color, #03a9f4); font-weight: 600;">
                ${this._escapeHtml(this._updateStepText)}
              </p>

              <div class="progress-bar-bg">
                <div class="progress-bar-fill" style="width: ${this._updateProgress}%;"></div>
              </div>

              ${this._rebootCountdown > 0 ? `
                <div style="margin-top: 14px; font-size: 0.9em; color: var(--secondary-text-color);">
                  Reconnexion automatique dans <strong>${this._rebootCountdown}s</strong>...
                </div>
              ` : ""}
            </div>
          ` : `
            <div>
              <h4 style="margin: 12px 0 6px 0;">📋 Notes de version & Nouveautés :</h4>
              <div class="code-block" style="max-height: 250px; background: #252526;">${this._escapeHtml(this._updateInfo.changelog || "Mise à jour d'optimisation et de sécurité.")}</div>

              <div style="background: rgba(76,175,80,0.08); padding: 12px; border-radius: 8px; margin: 16px 0; font-size: 0.85em; color: var(--secondary-text-color);">
                🛡️ <strong>Sécurité garantie :</strong> Une sauvegarde locale préalable de votre dossier d'intégration sera automatiquement créée avant tout remplacement de fichier.
              </div>

              <div style="display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px;">
                <button class="btn btn-secondary" id="btn-cancel-update-modal">Annuler</button>
                <button class="btn-update-pulse" id="btn-modal-install-update" style="padding: 10px 20px;">
                  ⚡ Lancer la mise à jour (1-Clic)
                </button>
              </div>
            </div>
          `}
        </div>
      </div>
    `;
  }

  _renderModal() {
    if (!this._selectedIssue) return "";
    const issue = this._selectedIssue;

    return `
      <div class="modal-floating" id="modal" style="left: ${this._modalPos.x !== null ? this._modalPos.x + "px" : "calc(50vw - 240px)"}; top: ${this._modalPos.y !== null ? this._modalPos.y + "px" : "100px"};">
        <div id="modal-header" style="padding: 12px 16px; background: var(--primary-color, #03a9f4); color: white; cursor: move; display: flex; justify-content: space-between; align-items: center; user-select: none;">
          <h3 style="margin: 0; font-size: 1em;">📖 Guide de Résolution Manuel</h3>
          <button id="modal-close" style="background: none; border: none; color: white; font-size: 1.2em; cursor: pointer;">&times;</button>
        </div>
        <div style="padding: 16px; overflow-y: auto;">
          <h4>${this._escapeHtml(issue.title)}</h4>
          <p>${this._escapeHtml(issue.description)}</p>

          ${issue.file ? `
            <p><strong>Fichier :</strong> <code>${this._escapeHtml(issue.file)}</code> ${issue.line ? `(Ligne ${issue.line})` : ""}</p>
          ` : ""}

          ${issue.manual_guide ? `
            <div style="background: rgba(0,0,0,0.03); padding: 12px; border-radius: 8px; font-size: 0.9em; margin-top: 10px;">
              <strong>Étapes à suivre :</strong>
              <div style="white-space: pre-wrap; margin-top: 6px;">${this._escapeHtml(issue.manual_guide)}</div>
            </div>
          ` : ""}
        </div>
      </div>
    `;
  }

  _renderConfirmDialog() {
    if (!this._confirmData) return "";
    return `
      <div class="modal-overlay">
        <div class="modal" style="max-width: 450px;">
          <h3 style="margin-top:0;">${this._escapeHtml(this._confirmData.title || "Confirmation")}</h3>
          <p>${this._escapeHtml(this._confirmData.message || "Voulez-vous continuer ?")}</p>
          <div style="display: flex; justify-content: flex-end; gap: 8px; margin-top: 20px;">
            <button class="btn btn-secondary" id="btn-confirm-cancel">Annuler</button>
            <button class="btn btn-warning" id="btn-confirm-ok">Confirmer</button>
          </div>
        </div>
      </div>
    `;
  }

  _attachEvents() {
    const root = this.shadowRoot;

    // Error banner retry and dismiss
    const btnRetry = root.getElementById("btn-retry-scan");
    if (btnRetry) {
      btnRetry.addEventListener("click", () => {
        this._lastError = null;
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    const btnDismiss = root.getElementById("btn-dismiss-error");
    if (btnDismiss) {
      btnDismiss.addEventListener("click", () => {
        this._lastError = null;
        if (this._currentStatus && this._currentStatus.startsWith("❌")) {
          this._currentStatus = "En attente";
        }
        this._render();
      });
    }

    // Header Quick Scan
    const btnQuick = root.getElementById("btn-quick-scan");
    if (btnQuick) {
      btnQuick.addEventListener("click", () => {
        this._lastError = null;
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    // Header Update Button
    const btnHeaderUpdate = root.getElementById("btn-header-update");
    if (btnHeaderUpdate) {
      btnHeaderUpdate.addEventListener("click", () => {
        this._showUpdateModal = true;
        this._render();
      });
    }

    // Banner Update Buttons
    const btnBannerUpdate = root.getElementById("btn-banner-update");
    if (btnBannerUpdate) {
      btnBannerUpdate.addEventListener("click", () => {
        this._showUpdateModal = true;
        this._render();
      });
    }
    const btnBannerChangelog = root.getElementById("btn-banner-changelog");
    if (btnBannerChangelog) {
      btnBannerChangelog.addEventListener("click", () => {
        this._showUpdateModal = true;
        this._render();
      });
    }

    // Modal Update Buttons
    const btnCloseUpdateModal = root.getElementById("btn-close-update-modal");
    if (btnCloseUpdateModal) {
      btnCloseUpdateModal.addEventListener("click", () => {
        this._showUpdateModal = false;
        this._render();
      });
    }
    const btnCancelUpdateModal = root.getElementById("btn-cancel-update-modal");
    if (btnCancelUpdateModal) {
      btnCancelUpdateModal.addEventListener("click", () => {
        this._showUpdateModal = false;
        this._render();
      });
    }
    const btnModalInstall = root.getElementById("btn-modal-install-update");
    if (btnModalInstall) {
      btnModalInstall.addEventListener("click", () => {
        this._startAutoUpdate();
      });
    }

    // Manual check update from Audit tab
    const btnCheckUpdateManual = root.getElementById("btn-check-update-manual");
    if (btnCheckUpdateManual) {
      btnCheckUpdateManual.addEventListener("click", async () => {
        btnCheckUpdateManual.textContent = "⏳ Recherche...";
        await this._checkUpdate();
        setTimeout(() => {
          if (btnCheckUpdateManual) btnCheckUpdateManual.textContent = "🔄 Vérifier les Mises à Jour";
        }, 1500);
      });
    }

    // Navigation Tabs
    root.querySelectorAll(".tab-btn").forEach(btn => {
      btn.addEventListener("click", (e) => {
        this._activeTab = e.currentTarget.dataset.tab;
        this._render();
      });
    });

    const btnTabAuditScan = root.getElementById("btn-tab-audit-scan");
    if (btnTabAuditScan) {
      btnTabAuditScan.addEventListener("click", () => {
        this._isAnalyzing = true;
        this._render();
        this._hass.callService("domolink_mistral", "analyze_now", {});
      });
    }

    const btnTabRepairGoto = root.getElementById("btn-tab-repair-goto");
    if (btnTabRepairGoto) {
      btnTabRepairGoto.addEventListener("click", () => {
        this._activeTab = "repair";
        this._render();
      });
    }

    // Repair Filter Buttons
    const fAll = root.getElementById("btn-filter-all");
    if (fAll) fAll.addEventListener("click", () => { this._repairFilter = "all"; this._render(); });
    const fHigh = root.getElementById("btn-filter-high");
    if (fHigh) fHigh.addEventListener("click", () => { this._repairFilter = "high"; this._render(); });
    const fMed = root.getElementById("btn-filter-med");
    if (fMed) fMed.addEventListener("click", () => { this._repairFilter = "medium"; this._render(); });
    const fLow = root.getElementById("btn-filter-low");
    if (fLow) fLow.addEventListener("click", () => { this._repairFilter = "low"; this._render(); });

    // All Auto Repair
    const btnRepairAll = root.getElementById("btn-repair-all");
    if (btnRepairAll) {
      btnRepairAll.addEventListener("click", () => {
        this._confirmData = {
          title: "⚡ Appliquer tous les correctifs automatiques ?",
          message: "Une sauvegarde globale sera effectuée avant d'appliquer l'ensemble des correctifs.",
          onConfirm: () => {
            this._isApplying = true;
            this._render();
            this._hass.callService("domolink_mistral", "apply_all_fixes", {});
          }
        };
        this._render();
      });
    }

    // Toggle Ignored
    const btnToggleIgnored = root.getElementById("btn-toggle-ignored");
    if (btnToggleIgnored) {
      btnToggleIgnored.addEventListener("click", () => {
        this._showIgnored = !this._showIgnored;
        this._render();
      });
    }

    // Single Issue Actions
    root.querySelectorAll(".btn-autofix").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.dataset.id;
        const issue = this._issues.find(i => i.id === id);
        if (!issue) return;

        this._confirmData = {
          title: `⚡ Corriger "${issue.title}" ?`,
          message: "Une sauvegarde sera effectuée avant d'appliquer ce correctif.",
          onConfirm: () => {
            this._isApplying = true;
            this._render();
            this._hass.callService("domolink_mistral", "apply_fix", {
              fix_script: issue.auto_fix_script,
              issue_id: issue.id
            });
          }
        };
        this._render();
      });
    });

    root.querySelectorAll(".btn-manual").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.dataset.id;
        this._selectedIssue = this._issues.find(i => i.id === id);
        this._render();
      });
    });

    root.querySelectorAll(".btn-ignore").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.dataset.id;
        this._hass.callService("domolink_mistral", "ignore_issue", { issue_id: id });
      });
    });

    root.querySelectorAll(".btn-unignore").forEach(btn => {
      btn.addEventListener("click", (e) => {
        const id = e.currentTarget.dataset.id;
        this._hass.callService("domolink_mistral", "unignore_issue", { issue_id: id });
      });
    });

    // Generator Events
    const genPrompt = root.getElementById("gen-prompt-input");
    if (genPrompt) {
      genPrompt.addEventListener("input", (e) => { this._genPrompt = e.target.value; });
    }
    const btnDoGen = root.getElementById("btn-do-generate");
    if (btnDoGen) {
      btnDoGen.addEventListener("click", async () => {
        if (!this._genPrompt.trim()) return;
        this._isGenerating = true;
        this._render();

        try {
          const resp = await this._hass.callService("domolink_mistral", "generate_automation", {
            prompt: this._genPrompt
          });
          if (resp && resp.response) {
            this._generatedAutomation = resp.response;
          }
        } catch (e) {
          console.error(e);
        } finally {
          this._isGenerating = false;
          this._render();
        }
      });
    }

    const btnSaveGen = root.getElementById("btn-save-generated-auto");
    if (btnSaveGen && this._generatedAutomation) {
      btnSaveGen.addEventListener("click", async () => {
        await this._hass.callService("domolink_mistral", "save_automation", {
          yaml: this._generatedAutomation.yaml
        });
        btnSaveGen.textContent = "✅ Enregistré dans automations.yaml !";
        setTimeout(() => { if (btnSaveGen) btnSaveGen.textContent = "💾 Injecter dans automations.yaml"; }, 2500);
      });
    }

    // Assist Chat Events
    const chatIn = root.getElementById("chat-input");
    if (chatIn) {
      chatIn.addEventListener("input", (e) => { this._chatInput = e.target.value; });
      chatIn.addEventListener("keydown", (e) => {
        if (e.key === "Enter") {
          const btnSend = root.getElementById("btn-chat-send");
          if (btnSend) btnSend.click();
        }
      });
    }

    const btnChatSend = root.getElementById("btn-chat-send");
    if (btnChatSend) {
      btnChatSend.addEventListener("click", async () => {
        const text = this._chatInput.trim();
        if (!text) return;

        this._chatMessages.push({ role: "user", text, services: [] });
        this._chatInput = "";
        this._isAssisting = true;
        this._render();

        const chatBox = this.shadowRoot.getElementById("chat-box");
        if (chatBox) chatBox.scrollTop = chatBox.scrollHeight;

        try {
          let agentId = "conversation.domolink_mistral_ia";
          if (this._hass && this._hass.states) {
            const found = Object.keys(this._hass.states).find(
              k => k.startsWith("conversation.") && k.includes("domolink")
            );
            if (found) agentId = found;
          }

          const res = await this._hass.callWS({
            type: "conversation/process",
            text: text,
            agent_id: agentId,
            language: "fr"
          });

          if (res && res.response && res.response.speech) {
            const speech = res.response.speech.plain.speech || "Action effectuée.";
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
