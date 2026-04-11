"""
BarberOS - Full Engine (Brain Node)
===================================
Versão otimizada para ser o "Cérebro" do N8N.
"""
from typing import Annotated, TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from src.config.settings import get_settings

# --- Estado do Agente ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Historico"]
    context_data: Optional[dict]
    needs_human: bool

# --- Lógica do Modelo ---
def call_model(state: AgentState):
    settings = get_settings()
    
    # CORREÇÃO: Usando a chave diretamente como string
    llm = ChatOpenAI(
        model=settings.openai_model, 
        temperature=settings.openai_temperature,
        openai_api_key=str(settings.openai_api_key)
    )
    
    context_str = ""
    if state.get("context_data"):
        context_str = f"\n\nFONTE DE VERDADE (DADOS REAIS DO SISTEMA):\n{state['context_data']}"

    system_message = SystemMessage(content=(
        "Você é o recepcionista virtual inteligente da barbearia.\n"
        "Sua tarefa é responder o cliente de forma amigável e profissional.\n"
        "NUNCA invente preços, horários ou serviços.\n"
        "Use apenas as informações fornecidas e, se não souber, peça para aguardar um humano."
        f"{context_str}"
    ))
    
    messages = [system_message] + state["messages"]
    response = llm.invoke(messages)
    
    return {"messages": [response]}

# --- Construindo o Grafo ---
def create_full_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)
    
    return workflow.compile(checkpointer=MemorySaver())
