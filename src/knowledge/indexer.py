"""
BarberOS - Knowledge Indexer
============================
O "Bibliotecário" do sistema. Este script lê arquivos Markdown de uma pasta
(Obsidian Vault), gera embeddings e salva no ChromaDB para cada barbearia.
"""
import os
import glob
from typing import List
from langchain_community.document_loaders import TextLoader, DirectoryLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.config.settings import get_settings
from src.config.logging_config import get_logger

logger = get_logger("knowledge.indexer")

class VaultIndexer:
    def __init__(self, barbershop_id: str):
        self.barbershop_id = barbershop_id
        self.settings = get_settings()
        self.vault_path = os.path.join("knowledge", "vaults", barbershop_id)
        self.persist_dir = os.path.join(self.settings.chroma_persist_dir, barbershop_id)
        
        # Criar pastas se não existirem
        os.makedirs(self.vault_path, exist_ok=True)
        os.makedirs(self.persist_dir, exist_ok=True)

    def index_vault(self):
        """Lê os arquivos MD e atualiza a base vetorial."""
        logger.info(f"INDEX_START: Iniciando indexação do vault para {self.barbershop_id}")
        
        # 1. Carregar Documentos (.md)
        loader = DirectoryLoader(
            self.vault_path, 
            glob="**/*.md", 
            loader_cls=TextLoader,
            loader_kwargs={'encoding': 'utf-8'}
        )
        
        documents = loader.load()
        if not documents:
            logger.warning(f"INDEX_EMPTY: Nenhum arquivo .md encontrado em {self.vault_path}")
            return False

        # 2. Dividir em pedaços (Chunks)
        # Usamos 1000 caracteres com 200 de sobreposição para não perder contexto
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)
        
        # 3. Gerar Embeddings e Salvar no ChromaDB
        embeddings = OpenAIEmbeddings(openai_api_key=self.settings.openai_api_key)
        
        # Limpa coleção anterior antes de re-indexar (estratégia simples)
        vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=embeddings,
            persist_directory=self.persist_dir,
            collection_name=f"vault_{self.barbershop_id}"
        )
        
        logger.info(f"INDEX_SUCCESS: {len(splits)} trechos indexados para {self.barbershop_id}")
        return True

def index_all_vaults():
    """Percorre todas as pastas de barbearias e atualiza os índices."""
    vaults_root = os.path.join("knowledge", "vaults")
    if not os.path.exists(vaults_root):
        os.makedirs(vaults_root)
        return

    for barbershop_id in os.listdir(vaults_root):
        owner_path = os.path.join(vaults_root, barbershop_id)
        if os.path.isdir(owner_path):
            indexer = VaultIndexer(barbershop_id)
            indexer.index_vault()

if __name__ == "__main__":
    # Quando rodado diretamente, indexa todos os vaults existentes
    index_all_vaults()
