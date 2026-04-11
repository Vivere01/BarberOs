"""
BarberOS - Full Engine (Brain Node)
===================================
Versão com Detecção de Intenção para o N8N.
"""
from typing import Annotated, TypedDict, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.pydantic_v1 import BaseModel, Field
from src.config.settings import get_settings

# --- Esquema para saída estruturada ---
class BookingIntent(BaseModel):
    is_booking: bool = Field(description="Verdadeiro se o cliente confirmou um agendamento")
    service: Optional[str] = Field(description="Nome do serviço confirmado")
    date: Optional[str] = Field(description="Data confirmada")
    time: Optional[str] = Field(description="Hora confirmada")

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Historico"]
    context_data: dict
    intent: Optional[BookingIntent]
    needs_human: bool

def call_model(state: AgentState):
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model, 
        temperature=settings.openai_temperature,
        openai_api_key=str(settings.openai_api_key)
    )
    
    # Adicionamos uma instrução para a IA detectar o agendamento
    persona = state.get("context_data", {}).get("persona", "Você é a Ana.")
    base_de_dados = state.get("context_data", {}).get("system_info", {})

    system_message = SystemMessage(content=(
        f"--- PERSONA ---\n{persona}\n\n"
        "--- DADOS DO SISTEMA ---\n{base_de_dados}\n\n"
        "--- REGRAS ---\n"
        "Se o cliente confirmar um serviço e horário, finalize educadamente.\n"
        "IMPORTANTE: Você deve identificar se houve uma confirmação de agendamento."
    ))
    
    messages = [system_message] + state["messages"]
    
    # Chamada dupla: uma para o texto e outra (interna/ferramenta) para o sinal
    response = llm.invoke(messages)
    
    # Mini-classificador de intenção rápido
    intent_llm = llm.with_structured_output(BookingIntent)
    intent_signal = intent_llm.invoke([
        SystemMessage(content="Analise a última mensagem do assistente e do humano e diga se houve uma confirmação de agendamento."),
        messages[-1], # Última do humano
        response      # Resposta da Ana
    ])

    return {
        "messages": [response],
        "intent": intent_signal
    }

def create_full_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.set_entry_point("agent")
    workflow.add_edge("agent", END)
    
    return workflow.compile(checkpointer=MemorySaver())
