"""
BarberOS - Router Node
=======================
Classifica a intenção do usuário com precisão absoluta.
Usa temperatura 0 e JSON schema para forçar o motor a ser determinístico.
"""
from typing import Any, Dict
import json

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.agent.state import AgentState, IntentType
from src.config.settings import get_settings
from src.config.logging_config import get_logger

logger = get_logger("agent.nodes.router")

async def route_intent(state: AgentState) -> Dict[str, Any]:
    """
    Analisa a última mensagem e classifica em uma das intenções permitidas.
    """
    settings = get_settings()
    
    # Setup LLM com temperatura 0 para classificação
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0, 
        api_key=settings.openai_api_key
    )

    # Prompt de classificação rigoroso
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Você é um classificador de intenções para uma recepção de barbearia.\n"
            "Sua única tarefa é ler a mensagem do cliente e retornar um JSON com a intenção.\n\n"
            "INTENÇÕES PERMITIDAS:\n"
            "- greeting: Saudações iniciais (Oi, Olá, Bom dia)\n"
            "- schedule_appointment: Desejo de agendar (Quero cortar, tem horário?)\n"
            "- cancel_appointment: Desejo de cancelar\n"
            "- query_services: Pergunta sobre o que fazem ou preços\n"
            "- query_hours: Pergunta sobre quando abre/fecha\n"
            "- human_handoff: Pedido explícito por humano ou reclamação\n"
            "- unknown: Não se encaixa em nada\n\n"
            "COMO RESPONDER:\n"
            'Retorne APENAS um JSON no formato: {{"intent": "nome_da_intencao", "confidence": 0.95}}'
        )),
        ("placeholder", "{messages}")
    ])

    chain = prompt | llm
    
    try:
        response = await chain.ainvoke({"messages": state["messages"]})
        
        # Parse da resposta (tratando possíveis MD blocks do LLM)
        content = response.content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)
        
        intent = data.get("intent", "unknown")
        confidence = data.get("confidence", 0.0)
        
        logger.info(f"Intenção detectada: {intent} ({confidence})")
        
        return {
            "current_intent": intent,
            "intent_confidence": confidence,
            "turn_count": state["turn_count"] + 1
        }
    except Exception as e:
        logger.error(f"Erro no roteador: {str(e)}")
        return {"current_intent": "unknown", "intent_confidence": 0.0}
