"""
BarberOS - Knowledge Retrieval Node (The "Brain")
================================================
Implementa a busca semântica (RAG) no Obsidian Vault da barbearia.
Inspirado no conceito de 'Second Brain' e LLM Wiki.
"""
from typing import Any, Dict, List
import os
from langchain_openai import OpenAIEmbeddings
from langchain_community.vectorstores import Chroma
from src.agent.state import AgentState
from src.config.settings import get_settings
from src.config.logging_config import get_logger

logger = get_logger("agent.nodes.knowledge")

async def retrieve_knowledge(state: AgentState) -> Dict[str, Any]:
    """
    Busca informações relevantes no Obsidian Vault (ChromaDB)
    específico desta barbearia.
    """
    settings = get_settings()
    last_message = state["messages"][-1].content
    
    # Identifica a barbearia para buscar no cofre certo
    barbershop_id = state.get("barbershop_id", "default")
    
    # Caminho do persist_dir específico por barbearia
    persist_dir = os.path.join(settings.chroma_persist_dir, barbershop_id)
    
    # Se não existe pasta de conhecimento para este dono, retorna vazio
    if not os.path.exists(persist_dir):
        logger.debug(f"KNOWLEDGE_MISSING: Nenhuma base de conhecimento para {barbershop_id}")
        return {"retrieved_knowledge": []}

    try:
        api_key = settings.openai_api_key or settings.OPENAI_API_KEY
        embeddings = OpenAIEmbeddings(openai_api_key=api_key)
        vectorstore = Chroma(
            persist_directory=persist_dir,
            embedding_function=embeddings,
            collection_name=f"vault_{barbershop_id}"
        )
        
        # Busca semântica: top 3 trechos mais relevantes
        docs = vectorstore.similarity_search(last_message, k=3)
        knowledge_chunks = [d.page_content for d in docs]
        
        logger.info(f"KNOWLEDGE_HIT: {len(knowledge_chunks)} trechos encontrados para {barbershop_id}")
        
        return {"retrieved_knowledge": knowledge_chunks}
        
    except Exception as e:
        logger.error(f"KNOWLEDGE_ERROR: {str(e)}")
        return {"retrieved_knowledge": []}
