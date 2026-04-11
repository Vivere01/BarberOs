"""
BarberOS - Full Engine (Brain Node)
===================================
Fundindo Persona (N8N) + Anti-Alucinação (BarberOS)
"""
from typing import Annotated, TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from src.config.settings import get_settings

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Historico"]
    context_data: dict # Contém 'persona' e 'system_info'
    needs_human: bool

def call_model(state: AgentState):
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model, 
        temperature=settings.openai_temperature,
        openai_api_key=str(settings.openai_api_key)
    )
    
    # Extraindo o que veio do N8N
    persona = state.get("context_data", {}).get("persona", "Você é um recepcionista amigável.")
    base_de_dados = state.get("context_data", {}).get("system_info", {})

    # CRIANDO O SUPER PROMPT (Híbrido)
    system_message = SystemMessage(content=(
        f"--- PERSONA E COMPORTAMENTO ---\n{persona}\n\n"
        "--- REGRAS CRÍTICAS ANTI-ALUCINAÇÃO ---\n"
        "1. Se baseie APENAS nos dados fornecidos abaixo para responder sobre preços e serviços.\n"
        "2. Se a informação não estiver nos 'DADOS REAIS', diga que não tem acesso no momento.\n"
        "3. Nunca invente ou prometa nada que não esteja nos dados.\n\n"
        f"--- DADOS REAIS DO SISTEMA (Fatos) ---\n{base_de_dados}"
    ))
    
    messages = [system_message] + state["messages"]
    response = llm.invoke(messages)
    
    return {"messages": [response]}

def create_full_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)
    
    return workflow.compile(checkpointer=MemorySaver())
