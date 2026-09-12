# 🧠 DomoLink-Mistral IA pour Home Assistant

[![HACS Compatible](https://img.shields.io/badge/HACS-Custom-blue.svg)](https://github.com/SocrateMobile/DomoLink-Mistral)
[![Version](https://img.shields.io/badge/version-2.9.5-green.svg)](https://github.com/SocrateMobile/DomoLink-Mistral/releases)

DomoLink-Mistral IA est une intégration puissante pour Home Assistant qui connecte votre maison intelligente à l'intelligence artificielle **Mistral AI**. Elle agit comme un **assistant de diagnostic, d'automatisation et d'optimisation** pour votre installation domotique.

L'intégration analyse intelligemment vos journaux d'erreurs (`system_log` et `homeassistant.log`), détecte les anomalies, et vous propose des solutions précises pas-à-pas pour les résoudre. Elle peut même appliquer certaines corrections automatiquement après avoir sécurisé votre configuration avec une sauvegarde !

## ✨ Fonctionnalités

### 🚀 Mises à Jour Automatiques 1-Clic
- **Pastille latérale dynamique** : Pastille d'alerte rouge `MAJ` injectée sur le menu et l'icône Home Assistant.
- **Entité native HA `update.domolink_mistral`** : Intégration officielle au centre de mises à jour de Home Assistant.
- **Bouton d'action et bandeau supérieur** : Affichage instantané dès qu'une release GitHub est publiée.
- **Modale avec Changelog complet** : Comparateur de versions, notes de release officielles et progression en direct.
- **Processus 1-clic ultra-sécurisé** : Sauvegarde locale automatique `.bak`, déploiement du ZIP et redémarrage avec reconnexion automatique.

### 🔍 Détection d'erreurs par l'IA
- Analyse automatique des logs Home Assistant via Mistral AI
- Détection des erreurs, avertissements et opportunités d'optimisation
- Classification par gravité (🔴 Critique, 🟠 Moyen, 🟢 Faible)

### 🔒 Sécurité intégrée
- **Filtre de confidentialité** : mots de passe, tokens, adresses IP et clés API sont masqués localement avant tout envoi
- **Whitelist de services** : seuls les services HA autorisés peuvent être exécutés automatiquement
- **Sauvegarde automatique** avant chaque correction

### 🎛️ Panneau de résolution interactif
Un panneau dédié **DomoLink-Mistral IA** dans la barre latérale de Home Assistant avec 6 onglets :
- **🛡️ Diagnostic & Audit** : analyse globale de santé
- **🔧 Réparation Sécurisée** : correctifs manuels, automatiques et All Auto
- **✨ Générateur IA** : création d'automations intelligentes en langage naturel
- **🎙️ Assist Vocal & Écrit** : agent conversationnel officiel HA Assist avec pilotage domotique
- **👁️ Vision & Caméras** : analyse de sécurité et snapshots avec Pixtral
- **📰 Smart Briefing** : synthèse vocale quotidienne intelligente

### ⏰ Planification flexible
- **Live** : analyse périodique (1 à 24 fois par jour)
- **Boot** : analyse automatique 3 minutes après chaque démarrage
- **Manuel** : uniquement à la demande via le bouton ou un service HA

## 📥 Installation

### Via HACS (Recommandé)
1. Ouvrez **HACS** dans Home Assistant
2. Cliquez sur **Intégrations** > ⋮ > **Dépôts personnalisés**
3. Ajoutez `https://github.com/SocrateMobile/DomoLink-Mistral` (catégorie : **Intégration**)
4. Installez **DomoLink-Mistral IA** et redémarrez Home Assistant
5. Allez dans *Paramètres > Appareils et services > Ajouter une intégration* > **DomoLink-Mistral IA**
6. Entrez votre clé API Mistral (disponible sur [console.mistral.ai](https://console.mistral.ai))

### Installation manuelle
1. Copiez le dossier `custom_components/domolink_mistral` dans votre répertoire `config/custom_components/`
2. Redémarrez Home Assistant
3. Configurez l'intégration via l'interface

## 🛠️ Utilisation

### Panneau DomoLink-Mistral IA
Après installation, un nouveau menu **"DomoLink-Mistral IA"** (🧠) apparaît dans votre barre latérale. C'est votre tableau de bord central.

### Carte Lovelace (Bouton)
Ajoutez un bouton sur votre dashboard pour déclencher l'analyse manuellement :

```yaml
type: button
name: 🧠 Analyser avec Mistral
icon: mdi:brain
tap_action:
  action: call-service
  service: domolink_mistral.analyze_now
hold_action:
  action: none
```

### Services disponibles
| Service | Description |
|---------|-------------|
| `domolink_mistral.analyze_now` | Lance une analyse immédiate des logs |
| `domolink_mistral.apply_fix` | Applique un correctif spécifique |
| `domolink_mistral.apply_all_fixes` | Sauvegarde puis corrige tout |
| `domolink_mistral.ignore_issue` | Ignore une erreur spécifique |
| `domolink_mistral.unignore_issue` | Réactive une erreur ignorée |

### Automatisations
Exemple : recevoir une notification si Mistral détecte des erreurs critiques :

```yaml
automation:
  - alias: "Alerte Mistral - Erreurs critiques"
    trigger:
      - platform: numeric_state
        entity_id: sensor.domolink_mistral_problemes_detectes
        above: 0
    action:
      - service: notify.mobile_app_mon_telephone
        data:
          title: "🧠 DomoLink-Mistral"
          message: "{{ states('sensor.domolink_mistral_problemes_detectes') }} problème(s) détecté(s) !"
```

## 📄 Licence

MIT License — Projet open source par [SocrateMobile](https://github.com/SocrateMobile).
