import re
with open("custom_components/domolink_mistral/reparator.py", "r") as f:
    content = f.read()

bad_block = """        try:
            shutil.copy2(target_path, backup_path)
            _LOGGER.info("DomoLink-Mistral: Backup créé -> %s", backup_path)
        except Exception as e:

        except Exception as e:
            return {"success": False, "reason": f"Échec de la sauvegarde préalable: {e}"}"""

good_block = """        try:
            shutil.copy2(target_path, backup_path)
            _LOGGER.info("DomoLink-Mistral: Backup créé -> %s", backup_path)
        except Exception as e:
            return {"success": False, "reason": f"Échec de la sauvegarde préalable: {e}"}"""

content = content.replace(bad_block, good_block)

with open("custom_components/domolink_mistral/reparator.py", "w") as f:
    f.write(content)
