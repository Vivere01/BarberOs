"""
BarberOS - ChatBarber PRO Engine v2.0
======================================
Engine dedicada para o sistema ChatBarber PRO.
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
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from src.config.settings import get_settings
from contextvars import ContextVar
from src.integrations.chatbarber_pro.client import ChatBarberProClient
from src.config.logging_config import get_logger

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

def _get_datetime_context() -> str:
    now = _now_brasilia()
    return (
        f"Hoje é {_now_brasilia().strftime('%A')}, {now.day}/{now.month}/{now.year}.\n"
        f"Hora atual: {now.strftime('%H:%M')}.\n"
        f"PRÓXIMOS DIAS: {(now+timedelta(days=1)).strftime('%d/%m')} em diante.\n"
    )

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
    except: return "Erro ao listar serviços."

@tool
async def buscar_cliente(telefone: str) -> str:
    """Identifica cliente pelo telefone."""
    try:
        client = get_pro_client()
        res = await client.search_client_by_phone(telefone)
        if res.get("found"):
            return f"CLIENTE VIP: {res.get('name')} (ID: {res.get('id')}). Assinatura: {res.get('subscription', {}).get('status', 'Nenhum')}. Prossiga."
        return "Novo cliente. Peça Nome, Telefone e Nascimento."
    except: return "Erro na busca."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str, store_id: str = "") -> str:
    """Verifica horários disponíveis cruzando horários de funcionamento e agendamentos."""
    client = get_pro_client()
    try:
        stores = await client.list_stores()
        sel = next((s for s in stores if str(s.get("id")) == str(store_id)), (stores[0] if stores else None))
        if not sel: return "Selecione uma unidade."

        # Mapeamento do dia da semana (API usa 0=Seg ou 0=Dom? Vamos testar 0=Seg, 6=Dom padrão ISO)
        # Na API do Prisma/ChatBarber usamos Sunday=0. Python weekday() Monday=0.
        dt = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        # Ajuste: Sun=0, Mon=1... Sat=6
        day_api = (dt.weekday() + 1) % 7
        
        bh = next((h for h in sel.get("businessHours", []) if h.get("dayOfWeek") == day_api), None)
        if not bh or not bh.get("isOpen"): return f"Unidade fechada em {data_yyyy_mm_dd}."

        # CORREÇÃO: Chaves corretas vindas da API (openTime/closeTime)
        ot, ct = bh.get("openTime", "08:00"), bh.get("closeTime", "19:00")
        sh, sm = map(int, ot.split(":"))
        eh, em = map(int, ct.split(":"))

        staff = await client.list_staff()
        ustaff = [s for s in staff if str(s.get("storeId")) == str(sel.get("id"))]
        
        appts_res = await client.list_appointments(date=data_yyyy_mm_dd)
        apps = appts_res.get("appointments", [])
        
        ocup = {str(s["id"]): set() for s in ustaff}
        names = {str(s["id"]): s["name"] for s in ustaff}
        for a in apps:
            sid = str(a.get("staffId"))
            if sid in ocup: ocup[sid].add(str(a.get("scheduledAt", "")).split("T")[1][:5])

        now = _now_brasilia()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        min_n = now.hour * 60 + now.minute
        rel = [f"Agenda em '{sel.get('name')}' ({data_yyyy_mm_dd}):"]
        cnt = 0
        for sid, ocu in ocup.items():
            disp = []
            ch, cm = sh, sm
            while (ch * 60 + cm) < (eh * 60 + em):
                h_str = f"{ch:02d}:{cm:02d}"
                if not (is_today and (ch * 60 + cm) <= min_n + 15):
                    if h_str not in ocu: disp.append(h_str)
                cm += 30
                if cm >= 60: ch += 1; cm = 0
            if disp:
                rel.append(f"- {names[sid]} (ID: {sid}): {', '.join(disp)}")
                cnt += len(disp)
        
        return "\n".join(rel) if cnt > 0 else "Sem horários hoje."
    except Exception as e:
        logger.error(f"VERIFICAR_DISP_ERRO: {e}")
        return f"Não consegui ler a agenda da unidade (Erro: {e})"

@tool
async def cadastrar_cliente(nome: str, telefone: str, data_nascimento: str = "") -> str:
    """Cria novo cliente."""
    try:
        client = get_pro_client()
        # Fallback date
        if not data_nascimento: data_nascimento = "1990-01-01"
        res = await client.create_client({"name": nome, "phone": telefone, "birthDate": data_nascimento})
        return f"Sucesso! ID: {res.get('id')}. Pode agendar."
    except: return "Erro ao cadastrar. Tente agendar direto."

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """Agenda final. Requer IDs."""
    try:
        client = get_pro_client()
        res = await client.create_appointment({"clientId": client_id, "serviceId": service_id, "staffId": staff_id, "storeId": store_id, "scheduledAt": data_isostring})
        return "AGENDADO COM SUCESSO! ✅" if res.get("id") or res.get("success") else f"Erro: {res}"
    except: return "Erro na conexão final."

tools = [consultar_unidades, consultar_servicos, buscar_cliente, verificar_disponibilidade, cadastrar_cliente, agendar_horario]
tool_node = ToolNode(tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def call_model(state: AgentState):
    settings = get_settings()
    v = "knowledge/vaults/Brain/Helena"
    try:
        with open(f"{v}/Persona.md", "r", encoding="utf-8") as f: persona = f.read()
        with open(f"{v}/Rules.md", "r", encoding="utf-8") as f: rules = f.read()
        with open(f"{v}/Flows.md", "r", encoding="utf-8") as f: flows = f.read()
        brain = f"{persona}\n\n{rules}\n\n{flows}"
    except: brain = "Você é a Helena."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=str(settings.openai_api_key)).bind_tools(tools)
    sys = f"{brain}\n\nContexo: {state.get('context_data', {})} \nData/Hora: {_get_datetime_context()}"
    
    # Sanitização básica para evitar erros 400
    hist = [m for m in state["messages"] if not (isinstance(m, ToolMessage) and i == 0)]
    
    try:
        res = llm.invoke([SystemMessage(content=sys)] + hist[-15:])
        return {"messages": [res]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"Oscilação técnica: {e}. Poderia repetir?")]}

def should_continue(state: AgentState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls: return "tools"
    return END

def create_pro_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model); workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent"); workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())
