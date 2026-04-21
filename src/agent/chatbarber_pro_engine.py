"""
BarberOS - ChatBarber PRO Engine v2.0 (Resilient Edition)
=========================================================
Engine otimizada para evitar erro 400 (OpenAI slicing error).
"""
from typing import Annotated, TypedDict, List, Optional, Any
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from src.config.settings import get_settings
from contextvars import ContextVar
from src.integrations.chatbarber_pro.client import ChatBarberProClient
from src.config.logging_config import get_logger
from langchain_core.tools import tool

logger = get_logger("agent.chatbarber_pro")

_pro_session_ctx: ContextVar[dict] = ContextVar("chatbarber_pro_session", default={})

def get_pro_client() -> ChatBarberProClient:
    ctx = _pro_session_ctx.get({})
    from src.config.settings import get_settings
    s = get_settings()
    return ChatBarberProClient(
        api_key=ctx.get("api_token") or s.chatbarber_api_key, 
        owner_id=ctx.get("owner_id") or s.chatbarber_owner_slug or s.chatbarber_owner_id,
        base_url=s.chatbarber_base_url
    )

def _now_brasilia() -> datetime:
    return datetime.now(ZoneInfo("America/Sao_Paulo"))

@tool
async def consultar_unidades() -> str:
    """Retorna lista de unidades e seus IDs."""
    try:
        client = get_pro_client()
        return str(await client.list_stores())
    except: return "Erro ao listar unidades."

@tool
async def consultar_servicos() -> str:
    """Retorna lista de serviços e IDs."""
    try:
        client = get_pro_client()
        return str(await client.list_services())
    except: return "Serviços indisponíveis."

@tool
async def buscar_cliente(telefone: str) -> str:
    """Identifica cliente pelo telefone."""
    try:
        client = get_pro_client()
        res = await client.search_client_by_phone(telefone)
        if res.get("found"):
            return f"CLIENTE: {res.get('name')} (ID: {res.get('id')})."
        return "Cliente novo."
    except: return "Erro na busca."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str, store_id: str = "") -> str:
    """Agenda de horários."""
    try:
        client = get_pro_client()
        stores = await client.list_stores()
        sel = next((s for s in stores if str(s.get("id")) == str(store_id)), (stores[0] if stores else None))
        if not sel: return "Defina unidade."
        
        staff = await client.list_staff()
        ustaff = [s for s in staff if str(s.get("storeId")) == str(sel.get("id"))]
        appts = (await client.list_appointments(date=data_yyyy_mm_dd)).get("appointments", [])
        
        # Mapeamento Domingo=0
        dt = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        day_api = (dt.weekday() + 1) % 7
        bh = next((h for h in sel.get("businessHours", []) if h.get("dayOfWeek") == day_api), None)
        if not bh or not bh.get("isOpen"): return "Fechado."

        sh, sm = map(int, bh.get("openTime", "08:00").split(":"))
        eh, em = map(int, bh.get("closeTime", "19:00").split(":"))

        ocup = {str(s["id"]): set() for s in ustaff}
        names = {str(s["id"]): s["name"] for s in ustaff}
        for a in appts:
            sid = str(a.get("staffId"))
            if sid in ocup: ocup[sid].add(str(a.get("scheduledAt", "")).split("T")[1][:5])

        now = _now_brasilia()
        rel = [f"Agenda {sel.get('name')} {data_yyyy_mm_dd}:"]
        for sid, ocu in ocup.items():
            disp = []
            ch, cm = sh, sm
            while (ch * 60 + cm) < (eh * 60 + em):
                h = f"{ch:02d}:{cm:02d}"
                if data_yyyy_mm_dd != now.strftime("%Y-%m-%d") or (ch * 60 + cm) > (now.hour * 60 + now.minute + 10):
                    if h not in ocu: disp.append(h)
                cm += 30
                if cm >= 60: ch += 1; cm = 0
            if disp: rel.append(f"- {names[sid]} (ID: {sid}): {', '.join(disp)}")
        
        return "\n".join(rel) if len(rel) > 1 else "Sem horários."
    except Exception as e: return f"Erro: {e}"

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """Confirma agendamento."""
    try:
        client = get_pro_client()
        res = await client.create_appointment({"clientId": client_id, "serviceId": service_id, "staffId": staff_id, "storeId": store_id, "scheduledAt": data_isostring})
        return "Agendado!" if res.get("id") or res.get("success") else "Erro no sistema."
    except: return "Erro de conexão."

tools = [consultar_unidades, consultar_servicos, buscar_cliente, verificar_disponibilidade, agendar_horario]
tool_node = ToolNode(tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def call_model(state: AgentState):
    settings = get_settings()
    v = "knowledge/vaults/Brain/Helena"
    try:
        with open(f"{v}/Persona.md", "r", encoding="utf-8") as f: p = f.read()
        with open(f"{v}/Rules.md", "r", encoding="utf-8") as f: r = f.read()
        brain = f"{p}\n\n{r}"
    except: brain = "Você é a Helena."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=str(settings.openai_api_key)).bind_tools(tools)
    
    # --- RESILIÊNCIA DE HISTÓRICO (O PULHO DO GATO) ---
    all_msgs = state["messages"]
    # Se cortarmos os últimos 15, precisamos garantir que o primeiro NÃO seja um ToolMessage órfão
    cut = 15
    if len(all_msgs) > cut:
        subset = all_msgs[-cut:]
        # Remove ToolMessages órfãs no início do bloco cortado
        while subset and isinstance(subset[0], ToolMessage):
            subset = subset[1:]
        # Garante que temos pelo menos uma mensagem humana se o subset ficou vazio
        messages_to_send = subset if subset else all_msgs[-1:]
    else:
        messages_to_send = all_msgs

    sys = f"{brain}\n\nContexto: {state.get('context_data', {})}\nHoje: {_now_brasilia().strftime('%d/%m/%Y %H:%M')}"
    
    try:
        res = llm.invoke([SystemMessage(content=sys)] + messages_to_send)
        return {"messages": [res]}
    except Exception as e:
        logger.error(f"ENGINE_CRITICAL_ERROR: {e}")
        return {"messages": [AIMessage(content=f"Desculpe, tive um problema técnico (Err: {str(e)[:50]}). Pode tentar de novo?")]}

def should_continue(state: AgentState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls: return "tools"
    return END

def create_pro_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model); workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent"); workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())
