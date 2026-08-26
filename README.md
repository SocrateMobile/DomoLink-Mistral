# DomoLink-Mistral pour Home Assistant

DomoLink-Mistral est une intégration puissante pour Home Assistant qui connecte votre maison intelligente à l'intelligence artificielle de Mistral AI. Elle agit comme un **assistant de diagnostic et d'optimisation** pour votre installation.

L'intégration analyse intelligemment vos journaux d'erreurs (`system_log` et `homeassistant.log`), détecte les anomalies, et vous propose des solutions précises pas-à-pas pour les résoudre. Elle peut même appliquer certaines corrections automatiquement après avoir sécurisé votre configuration avec une sauvegarde !

## ✨ Fonctionnalités

*   **Détection d'erreurs par l'IA :** Analyse automatique de vos logs Home Assistant.
*   **Filtre de confidentialité :** Vos mots de passe, tokens et adresses IP sont expurgés localement avant tout envoi vers les serveurs de Mistral.
*   **Panneau de résolution interactif :**
    *   *Ignorer :* Masque les erreurs mineures.
    *   *Manuel :* Affiche un guide pas-à-pas généré par Mistral en surimpression pendant que vous travaillez.
    *   *Automatique :* Lance une sauvegarde native de HA, puis exécute le script correctif généré par Mistral.
    *   *All Auto :* Sauvegarde et corrige toutes les erreurs listées d'un seul coup.
*   **Planification flexible :** Scans en direct (plusieurs fois par jour), au démarrage, ou à la demande via un service HA.

## 📥 Installation

### Via HACS (Recommandé)
1. Ouvrez HACS dans Home Assistant.
2. Cliquez sur **Intégrations**.
3. Cliquez sur les 3 points en haut à droite > **Dépôts personnalisés**.
4. Ajoutez l'URL de ce dépôt (`https://github.com/SocrateMobile/DomoLink-Mistral`) avec la catégorie **Intégration**.
5. Cliquez sur installer et redémarrez Home Assistant.
6. Allez dans *Paramètres > Appareils et services > Ajouter une intégration*, et cherchez **DomoLink-Mistral**. Vous aurez besoin de votre clé API Mistral.

## 🛠️ Utilisation et Carte Lovelace (Dashboard)

En attendant la finalisation du panneau latéral interactif complet, vous pouvez ajouter ce bouton sur votre tableau de bord (Lovelace) pour déclencher une analyse manuellement à tout moment.

Ajoutez une carte **Manuel** (Manual card) et collez ce code YAML :

```yaml
type: button
name: Analyser les logs avec Mistral
icon: mdi:brain
tap_action:
  action: call-service
  service: domolink_mistral.analyze_now
hold_action:
  action: none
```

Vous pouvez également intégrer ce service `domolink_mistral.analyze_now` dans vos propres automatisations (par exemple, pour recevoir une notification si Mistral trouve une erreur grave).
