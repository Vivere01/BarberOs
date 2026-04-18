"""
BarberOS - Full Engine (Multi-Agent Structure)
==============================================
Esta versão implementa a estrutura multi-agentes solicitada,
conectando-se diretamente ao ChatBarber PRO e removendo o N8N.

Fluxo:
1. Router Node: Classifica a intenção (Agendamento, FAQ, Saudação).
2. Specialized Nodes: Processam a solicitação usando o ChatBarber PRO Client.
3. Tool Node: Executa as chamadas reais de sistema bi-direcionais.
"""
from typing import Annotated, TypedDict, List, Optional, Any, Union
from contextvars import ContextVar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from src.config.settings import get_settings
from src.config.logging_config import get_logger
from src.integrations.chatbarber_pro.client import ChatBarberProClient
from src.agent.nodes.knowledge import retrieve_knowledge
from src.agent.state import AgentState

logger = get_logger("agent.full_engine")

# ===================================================================
# Contexto de Sessão ChatBarber PRO
# ===================================================================
_session_ctx: ContextVar[dict] = ContextVar("barberos_session", default={})

def set_session_context(
    api_token: Optional[str] = None,
    owner_id: Optional[str] = None,
    inbox: Optional[str] = None,
    contact_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    system_info: Optional[dict] = None
):
    """Configura as credenciais e contexto para o request atual."""
    _session_ctx.set({
        "api_token": api_token,
        "owner_id": owner_id,
        "inbox": inbox,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
        "system_info": system_info or {},
    })

def _ctx() -> dict:
    return _session_ctx.get({})

def get_pro_client() -> ChatBarberProClient:
    ctx = _ctx()
    token = ctx.get("api_token")
    owner = ctx.get("owner_id")
    if not token or not owner:
        # Fallback para settings se não estiver no contexto (para testes)
        settings = get_settings()
        token = token or settings.uzapi_token # Exemplo
        owner = owner or "default_owner"
    return ChatBarberProClient(api_token=token, owner_id=owner)

# ===================================================================
# Helpers de Data/Hora (Brasília)
# ===================================================================
_TZ = ZoneInfo("America/Sao_Paulo")

def _get_datetime_context() -> str:
    now = datetime.now(_TZ)
    return (
        f"Hoje é {now.strftime('%A, %d de %B de %Y')}.\n"
        f"Hora atual: {now.strftime('%H:%M')} (Brasília).\n"
        f"Referência ISO: {now.strftime('%Y-%m-%d')}"
    )

# ===================================================================
# Ferramentas (Tools) conectadas ao ChatBarber PRO
# ===================================================================

@tool
async def consultar_unidades() -> list:
    "Consulta as unidades (lojas) disponíveis para obter o store_id correto."
    client = get_pro_client()
    return await client.list_stores()

@tool
async def buscar_cliente(telefone: str) -> dict:
    "Busca cadastro do cliente pelo telefone no ChatBarber PRO."
    client = get_pro_client()
    return await client.search_client_by_phone(telefone)

@tool
async def consultar_servicos() -> list:
    "Lista todos os serviços e preços da barbearia."
    client = get_pro_client()
    return await client.list_services()

@tool
async def consultar_profissionais() -> list:
    "Lista os profissionais (barbeiros) disponíveis."
    client = get_pro_client()
    return await client.list_staff()

@tool
async def buscar_disponibilidade(data: str) -> list:
    "Busca horários vagos para uma data específica (YYYY-MM-DD)."
    client = get_pro_client()
    # No PRO, list_appointments retorna ocupados, temos que inferir vagos
    res = await client.list_appointments(date_filter=data)
    # Lógica simplificada de disponibilidade: assume 08h-20h
    ocupados = [a.get("scheduledAt", "").split("T")[-1][:5] for a in res if "scheduledAt" in a]
    horarios = []
    for h in range(8, 20):
        for m in ["00", "30"]:
            time = f"{h:02d}:{m}"
            if time not in ocupados:
                horarios.append(time)
    return horarios[:10]

@tool
async def realizar_agendamento(
    client_id: str, 
    service_id: str, 
    staff_id: str, 
    store_id: str, 
    data_hora: str
) -> dict:
    "Cria um agendamento real no ChatBarber PRO. Requer confirmação prévia."
    client = get_pro_client()
    return await client.create_appointment(
        client_id=client_id,
        service_id=service_id,
        staff_id=staff_id,
        store_id=store_id,
        scheduled_at=data_hora
    )

tools = [
    consultar_unidades,
    buscar_cliente,
    consultar_servicos,
    consultar_profissionais,
    buscar_disponibilidade,
    realizar_agendamento
]
tool_node = ToolNode(tools)

# ===================================================================
# Estado do Agente
# ===================================================================
# AgentState importado de src.agent.state

# ===================================================================
# NODES DA ESTRUTURA MULTI-AGENTE
# ===================================================================

async def router_node(state: AgentState):
    """Analisa a entrada e decide qual sub-agente deve responder."""
    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, temperature=0)
    
    last_msg = state["messages"][-1].content
    
    system_prompt = (
        "Você é o roteador de uma barbearia. Classifique a intenção do cliente:\n"
        "- agendamento: se ele quiser marcar, trocar ou ver horários.\n"
        "- saudacao: se for apenas um Oi/Geral.\n"
        "- faq: se for dúvida de localização ou preços.\n"
        "Responda apenas com a palavra-chave."
    )
    
    res = await llm.ainvoke([SystemMessage(content=system_prompt), HumanMessage(content=last_msg)])
    intent = res.content.lower().strip()
    
    # Determina o próximo nó baseado na intenção
    if "agendamento" in intent:
        return {"current_intent": intent} # O Grafo decidirá baseado no intent
    
    return {"current_intent": intent}

async def receptionist_node(state: AgentState):
    """Agente de Boas-vindas e FAQ."""
    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, temperature=0.7).bind_tools(tools)
    
    dt_ctx = _get_datetime_context()
    persona = state.get("metadata", {}).get("persona", "Você é a Ana, recepcionista da barbearia.")
    knowledge = "\n".join(state.get("retrieved_knowledge", []))
    
    system_msg = SystemMessage(content=(
        f"{dt_ctx}\n\n"
        f"--- PERSONA ---\n{persona}\n\n"
        f"--- CONHECIMENTO ADICIONAL (WIKI) ---\n{knowledge}\n\n"
        "Seu objetivo é ser simpática e identificar o que o cliente deseja.\n"
        "Use o conhecimento acima para responder dúvidas sobre a barbearia."
    ))
    
    messages = [system_msg] + state["messages"]
    res = await llm.ainvoke(messages)
    return {"messages": [res]}

async def scheduler_node(state: AgentState):
    """Agente Especialista em Agendamento."""
    settings = get_settings()
    llm = ChatOpenAI(model=settings.openai_model, temperature=0).bind_tools(tools)
    
    dt_ctx = _get_datetime_context()
    knowledge = "\n".join(state.get("retrieved_knowledge", []))
    
    system_msg = SystemMessage(content=(
        f"{dt_ctx}\n\n"
        f"--- REGRAS DA BARBEARIA ---\n{knowledge}\n\n"
        "Você é o especialista em agendamentos.\n"
        "Siga o fluxo:\n"
        "1. Identifique serviço e profissional.\n"
        "2. Mostre horários com 'buscar_disponibilidade'.\n"
        "3. Peça confirmação clara.\n"
        "4. Use 'realizar_agendamento' NO MOMENTO da confirmação.\n\n"
        "NUNCA invente horários. Use sempre as ferramentas."
    ))
    
    messages = [system_msg] + state["messages"]
    res = await llm.ainvoke(messages)
    return {"messages": [res]}

# ===================================================================
# Configuração do Grafo
# ===================================================================

def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

def route_to_agent(state: AgentState):
    intent = state.get("current_intent", "greeting")
    if "agendamento" in intent:
        return "scheduler"
    return "receptionist"

def create_full_brain():
    workflow = StateGraph(AgentState)
    
    # Adiciona nós
    workflow.add_node("router", router_node)
    workflow.add_node("knowledge", retrieve_knowledge)
    workflow.add_node("receptionist", receptionist_node)
    workflow.add_node("scheduler", scheduler_node)
    workflow.add_node("tools", tool_node)
    
    # Define bordas
    workflow.set_entry_point("router")
    
    # Roteia para o cérebro primeiro para ganhar contexto
    workflow.add_edge("router", "knowledge")
    
    # Depois do cérebro, vai para o agente especializado
    workflow.add_conditional_edges("knowledge", route_to_agent)
    
    workflow.add_conditional_edges("receptionist", should_continue)
    workflow.add_conditional_edges("scheduler", should_continue)
    
    # Tools sempre respondem para o nó que os chamou (neste caso scheduler)
    workflow.add_edge("tools", "scheduler")
    
    # Nota: SqliteSaver real requer async context manager no main.py
    # Por segurança no teste síncrono, mantemos MemorySaver aqui
    from langgraph.checkpoint.memory import MemorySaver
    return workflow.compile(checkpointer=MemorySaver())
