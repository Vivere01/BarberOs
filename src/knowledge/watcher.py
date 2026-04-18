"""
BarberOS - Vault Watcher
========================
Monitora alterações nas pastas do Obsidian no servidor e dispara
a re-indexação do "Cérebro" automaticamente.
"""
import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from src.knowledge.indexer import VaultIndexer
from src.config.logging_config import get_logger

logger = get_logger("knowledge.watcher")

class VaultHandler(FileSystemEventHandler):
    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".md"):
            # Identifica qual barbearia foi alterada baseado no nome da pasta
            # Caminho esperado: knowledge/vaults/{owner_id}/arquivo.md
            parts = event.src_path.split(os.sep)
            try:
                # Localiza a pasta posterior a 'vaults'
                vaults_idx = parts.index("vaults")
                owner_id = parts[vaults_idx + 1]
                
                logger.info(f"WATCHER_DETECTED: Alteração no vault de {owner_id} ({os.path.basename(event.src_path)})")
                
                # Dispara indexação apenas para esta barbearia
                indexer = VaultIndexer(owner_id)
                indexer.index_vault()
            except (ValueError, IndexError):
                pass

def start_watcher():
    path = os.path.join("knowledge", "vaults")
    if not os.path.exists(path):
        os.makedirs(path)
        
    event_handler = VaultHandler()
    observer = Observer()
    observer.schedule(event_handler, path, recursive=True)
    
    logger.info(f"WATCHER_START: Monitorando vaults em {path}...")
    observer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    start_watcher()
