# 🧠 DomoLink-Mistral IA pour Home Assistant

[![HACS](https://img.shields.io/badge/HACS-Default-blue.svg)](https://github.com/SocrateMobile/DomoLink-Mistral)
[![Version](https://img.shields.io/badge/version-1.1.14-green.svg)](https://github.com/SocrateMobile/DomoLink-Mistral/releases)
[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Socrate-FFDD00?logo=buy-me-a-coffee&logoColor=000000)](https://buymeacoffee.com/Socrate)

[![Buy Me A Coffee](https://img.buymeacoffee.com/button-api/?text=Buy+me+a+coffee&emoji=☕&slug=Socrate&button_colour=FFDD00&font_colour=000000&font_family=Poppins&outline_colour=000000&coffee_colour=ffffff)](https://www.buymeacoffee.com/Socrate)

DomoLink-Mistral IA est une intégration puissante pour Home Assistant qui connecte votre maison intelligente à l'intelligence artificielle **Mistral AI**. Elle agit comme un **assistant de diagnostic, d'automatisation et d'optimisation** pour votre installation domotique.

L'intégration analyse intelligemment vos journaux d'erreurs (`system_log` et `homeassistant.log`), détecte les anomalies, et vous propose des solutions précises pas-à-pas pour les résoudre. Elle peut également exécuter certaines corrections de services automatiquement après confirmation.

## ✨ Fonctionnalités

### 🔍 Détection d'erreurs par l'IA
- Analyse automatique des logs Home Assistant via Mistral AI
- Détection des erreurs, avertissements et opportunités d'optimisation
- Classification par gravité (🔴 Critique, 🟠 Moyen, 🟢 Faible)

### 🔒 Sécurité intégrée
- **Filtre de confidentialité** : mots de passe, tokens, adresses IP et clés API sont masqués localement avant tout envoi
- **Whitelist de services** : seuls les services HA autorisés peuvent être exécutés automatiquement
- **Sauvegarde automatique** avant l'application de correctifs

### 🎛️ Panneau de résolution interactif
Un panneau dédié **DomoLink-Mistral IA** dans la barre latérale de Home Assistant avec 6 onglets :
- **🛡️ Diagnostic & Audit** : analyse globale de santé
- **🔧 Réparation Sécurisée** : guides manuels et correctifs de services validés
- **✨ Générateur IA** : création d'automations intelligentes en langage naturel via l'API Home Assistant
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
2. Recherchez **DomoLink-Mistral IA** et cliquez sur **Télécharger**
   *(Si l'intégration n'est pas encore visible dans le catalogue par défaut : cliquez sur **⋮** > **Dépôts personnalisés**, ajoutez `https://github.com/SocrateMobile/DomoLink-Mistral` en catégorie **Intégration**, puis téléchargez-la)*
3. Redémarrez Home Assistant
4. Allez dans *Paramètres > Appareils et services > Ajouter une intégration* > **DomoLink-Mistral IA**
5. Entrez votre clé API Mistral (disponible sur [console.mistral.ai](https://console.mistral.ai))

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
| `domolink_mistral.apply_fix` | Applique un correctif de service spécifique |
| `domolink_mistral.apply_all_fixes` | Applique tous les correctifs de services disponibles |
| `domolink_mistral.ignore_issue` | Ignore une erreur spécifique |
| `domolink_mistral.unignore_issue` | Réactive une erreur ignorée |
| `domolink_mistral.generate_automation` | Génère une automation en langage naturel |
| `domolink_mistral.analyze_image` | Analyse une image ou caméra avec Pixtral Vision |
| `domolink_mistral.generate_daily_briefing` | Génère le briefing quotidien de la maison |

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
---

## ☕ Soutenir le projet / Support

Si vous appréciez cette intégration et souhaitez soutenir son développement continu ainsi que la maintenance des futures versions :

<a href="https://buymeacoffee.com/Socrate" target="_blank">
  <img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50" width="210">
</a>

## 📄 Licence

MIT License — Projet open source par [SocrateMobile](https://github.com/SocrateMobile).
