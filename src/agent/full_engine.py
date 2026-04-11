"""
BarberOS - Full Engine (Autonomous Agent)
=========================================
Ana agora consegue buscar horários, criar agendamentos e cancelar.
"""
from typing import Annotated, TypedDict, List, Optional, Union
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.config.settings import get_settings
from src.integrations.n8n_webhooks import N8NWebhookClient

# Instanciamos o cliente uma vez
n8n = N8NWebhookClient()

# --- Definição das Ferramentas (Tools) ---

@tool
async def buscar_disponibilidade(data_inicio: str, data_fim: str, id_agenda: int, id_filial: int, duracao_total_minutos: int):
    """
    Busca horários livres no sistema. Use quando o cliente perguntar 'tem horário para amanhã?' 
    ou 'quais horários você tem?'.
    As datas devem estar no formato ISO 8601 (Ex: 2025-06-10T09:00:00-03:00).
    """
    return await n8n.buscar_horarios(data_inicio, data_fim, id_agenda, id_filial, duracao_total_minutos)

@tool
async def realizar_agendamento(data_inicio: str, duracao_minutos: int, servicos_ids: List[int], id_agenda: int, id_filial: int, cliente_fone: str, titulo: str):
    """
    Cria um agendamento real no sistema. Use APENAS quando o cliente confirmar o interesse.
    """
    desc = f"Agendamento via Ana AI. Tel: {cliente_fone}"
    return await n8n.criar_agendamento(data_inicio, duracao_minutos, titulo, desc, id_agenda, servicos_ids, id_filial)

@tool
async def consultar_meu_agendamento(data_inicio: str, data_fim: str, id_agenda: int, id_filial: int, duracao_minutos: int):
    """Consulta se o cliente já tem algo marcado em um período."""
    return await n8n.buscar_agendamento_contato(data_inicio, data_fim, id_agenda, duracao_minutos, id_filial)

@tool
async def cancelar_meu_agendamento(telefone: str, motivo: str, id_agenda: int, id_evento: str):
    """Cancela um agendamento existente."""
    return await n8n.cancelar_agendamento(telefone, motivo, id_agenda, id_evento)

tools = [buscar_disponibilidade, realizar_agendamento, consultar_meu_agendamento, cancelar_meu_agendamento]
tool_node = ToolNode(tools)

# --- Estado do Agente ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Historico"]
    context_data: dict
    needs_human: bool

# --- Lógica do Modelo ---
def call_model(state: AgentState):
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model, 
        temperature=0, # Temperatura 0 para ferramentas ser mais preciso
        openai_api_key=str(settings.openai_api_key)
    ).bind_tools(tools)
    
    persona = state.get("context_data", {}).get("persona", "Você é a Ana.")
    # Injetamos IDs importantes que o N8N pode ter enviado (id_filial, id_agenda)
    system_info = state.get("context_data", {}).get("system_info", {})

    system_message = SystemMessage(content=(
        f"--- PERSONA ---\n{persona}\n\n"
        f"--- DADOS TÉCNICOS DA FILIAL ---\n{system_info}\n\n"
        "--- INSTRUÇÕES DE FERRAMENTAS ---\n"
        "1. Para buscar horários, use 'buscar_disponibilidade'.\n"
        "2. Para marcar, use 'realizar_agendamento'.\n"
        "3. Sempre use os IDs de filial e agenda que estão nos 'DADOS TÉCNICOS' se não souber o do cliente.\n"
        "4. Formate datas em ISO 8601 com timezone -03:00 sempre.\n"
        "NUNCA invente horários. Se o sistema retornar vazio, diga ao cliente."
    ))
    
    messages = [system_message] + state["messages"]
    response = llm.invoke(messages)
    
    return {"messages": [response]}

# --- Verificador de Fluxo ---
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END

# --- Construindo o Grafo ---
def create_full_brain():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    workflow.set_entry_point("agent")
    
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent") # Volta para o agente para ele falar o resultado
    
    return workflow.compile(checkpointer=MemorySaver())
