"""
BarberOS - Validator Node
==========================
O coração do sistema. Verifica se a resposta gerada é baseada em fatos.
Compara a resposta com os dados de agendamento (Scraping) vindos do N8N.
"""
from typing import Any, Dict
import re

from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from src.agent.state import AgentState
from src.config.settings import get_settings
from src.config.logging_config import get_logger

logger = get_logger("agent.nodes.validator")

async def validate_response(state: AgentState) -> Dict[str, Any]:
    """
    Compara a resposta da IA com o contexto real.
    """
    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, temperature=0)
    
    agent_response = state.get("agent_response", "")
    real_data = state.get("scheduling_data", {})
    
    # Prompt do Juiz
    prompt = ChatPromptTemplate.from_messages([
        ("system", (
            "Sua tarefa é agir como um AUDITOR CRÍTICO.\n"
            "Verifique se a resposta da IA contém informações que NÃO estão nos DADOS REAIS.\n\n"
            "DADOS REAIS (SCRAPING):\n"
            "{real_data}\n\n"
            "RESPOSTA DA IA:\n"
            "{agent_response}\n\n"
            "REGRAS:\n"
            "1. Se a IA citar um preço não listado, é ALUCINAÇÃO.\n"
            "2. Se a IA citar um horário não disponível, é ALUCINAÇÃO.\n"
            "3. Se a IA prometer algo não explícito, é VIOLAÇÃO.\n\n"
            "Retorne APENAS um JSON: {{\"hallucination\": true/false, \"error_reason\": \"...\"}}"
        ))
    ])
    
    chain = prompt | llm
    
    try:
        response = await chain.ainvoke({
            "real_data": str(real_data),
            "agent_response": agent_response
        })
        
        import json
        content = response.content.replace("```json", "").replace("```", "").strip()
        result = json.loads(content)
        
        hallucination = result.get("hallucination", False)
        
        if hallucination:
            logger.warning(f"⚠️ Alucinação detectada: {result.get('error_reason')}")
            # Em caso de alucinação, mudamos a resposta ou pedimos handoff
            return {
                "guardrail_result": {
                    "hallucination_detected": True,
                    "reason": result.get("error_reason"),
                    "confidence": 0.0
                },
                "metadata": {"needs_human": True},
                "agent_response": "Perdão, estou com dificuldades em processar essa informação agora. Vou te passar para um humano nos ajudar aqui! 🙏"
            }
            
        return {
            "guardrail_result": {
                "hallucination_detected": False,
                "confidence": 1.0
            }
        }
    except Exception as e:
        logger.error(f"Erro na validação: {str(e)}")
        return {"guardrail_result": {"hallucination_detected": False, "confidence": 0.5}}
