"""
BarberOS - ChatBarber PRO Engine v2.6 (Precision Edition)
=========================================================
Engine com correção de Timezone UTC -> Brasília nos agendamentos 
e suporte a horários de pausa.
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
BR_TZ = ZoneInfo("America/Sao_Paulo")

_pro_session_ctx: ContextVar[dict] = ContextVar("chatbarber_pro_session", default={})

def set_pro_context(api_token: str, owner_id: str):
    _pro_session_ctx.set({"api_token": api_token, "owner_id": owner_id})

def get_pro_client() -> ChatBarberProClient:
    ctx = _pro_session_ctx.get({})
    s = get_settings()
    return ChatBarberProClient(
        api_key=ctx.get("api_token") or s.chatbarber_api_key, 
        owner_id=ctx.get("owner_id") or s.chatbarber_owner_slug or s.chatbarber_owner_id,
        base_url=s.chatbarber_base_url
    )

async def transcribe_audio(audio_base64: str) -> str:
    from openai import AsyncOpenAI
    s = get_settings(); key = s.openai_api_key or s.OPENAI_API_KEY
    if not key: return ""
    client = AsyncOpenAI(api_key=str(key))
    try:
        res = await client.audio.transcriptions.create(model="whisper-1", file=("audio.ogg", base64.b64decode(audio_base64)), language="pt")
        return res.text
    except: return ""

def _now_br() -> datetime:
    return datetime.now(BR_TZ)

@tool
async def consultar_unidades() -> str:
    """Lista lojas."""
    try: return str(await get_pro_client().list_stores())
    except: return "Erro lojas."

@tool
async def consultar_servicos() -> str:
    """Lista serviços."""
    try: return str(await get_pro_client().list_services())
    except: return "Erro serviços."

@tool
async def buscar_cliente(telefone: str) -> str:
    """Identifica cliente."""
    try:
        res = await get_pro_client().search_client_by_phone(telefone)
        return f"CLIENTE: {res.get('name')} (ID: {res.get('id')})" if res.get("found") else "CLIENTE_NOVO."
    except: return "Erro busca."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str, store_id: str = "") -> str:
    """Calcula horários livres considerando Timezone BR e Staff."""
    try:
        client = get_pro_client()
        stores = await client.list_stores()
        sel = next((s for s in stores if str(s.get("id")) == str(store_id)), (stores[0] if stores else None))
        if not sel: return "Selecione unidade."
        
        # 1. Obter Staff e Appointments
        staff = await client.list_staff()
        ustaff = [s for s in staff if str(s.get("storeId")) == str(sel.get("id"))]
        appts = (await client.list_appointments(date=data_yyyy_mm_dd)).get("appointments", [])
        
        # 2. Configurar Horário de Funcionamento (Hoje: Tuesday=2 em SQL standard Sun=0)
        dt = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        day_api = (dt.weekday() + 1) % 7 
        bh = next((h for h in sel.get("businessHours", []) if h.get("dayOfWeek") == day_api), None)
        
        if not bh or not bh.get("isOpen"):
            return f"A unidade {sel.get('name')} está fechada na data {data_yyyy_mm_dd}."

        sh, sm = map(int, bh.get("openTime", "08:00").split(":"))
        eh, em = map(int, bh.get("closeTime", "19:00").split(":"))
        b_start = bh.get("breakStart"); b_end = bh.get("breakEnd")

        # 3. Mapear Agendamentos (CONVERSÃO UTC -> BRASÍLIA)
        ocup = {str(s["id"]): set() for s in ustaff}
        names = {str(s["id"]): s["name"] for s in ustaff}
        for a in appts:
            sid = str(a.get("staffId"))
            if sid in ocup:
                # Converte string ISO (UTC) para Local (Brasil)
                dt_utc = datetime.fromisoformat(a["scheduledAt"].replace("Z", "+00:00"))
                dt_br = dt_utc.astimezone(BR_TZ)
                ocup[sid].add(dt_br.strftime("%H:%M"))

        # 4. Gerar Slots
        now = _now_br()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        min_cutoff = now.hour * 60 + now.minute + 15 # 15 min de antecedência
        
        rel = [f"Horários em {sel.get('name')} ({data_yyyy_mm_dd}):"]
        cnt = 0
        for sid, ocu in ocup.items():
            slots = []
            ch, cm = sh, sm
            while (ch * 60 + cm) < (eh * 60 + em):
                h_str = f"{ch:02d}:{cm:02d}"
                val = ch * 60 + cm
                
                # Regra 1: Não mostrar se já passou (se for hoje)
                if not is_today or val > min_cutoff:
                    # Regra 2: Não mostrar se estiver ocupado
                    if h_str not in ocu:
                        # Regra 3: Não mostrar se for horário de pausa
                        in_break = False
                        if b_start and b_end:
                            bsh, bsm = map(int, b_start.split(":"))
                            beh, bem = map(int, b_end.split(":"))
                            if (bsh*60+bsm) <= val < (beh*60+bem): in_break = True
                        
                        if not in_break: slots.append(h_str)
                
                cm += 30
                if cm >= 60: ch += 1; cm = 0
            
            if slots:
                rel.append(f"- {names[sid]} (ID: {sid}): {', '.join(slots)}")
                cnt += len(slots)

        return "\n".join(rel) if cnt > 0 else "Nenhum horário disponível para esta data."
    except Exception as e:
        logger.error(f"DISPO_ERR: {e}")
        return f"Erro ao ler agenda: {str(e)}"

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """Finaliza o agendamento."""
    try:
        res = await get_pro_client().create_appointment({"clientId": client_id, "serviceId": service_id, "staffId": staff_id, "storeId": store_id, "scheduledAt": data_isostring})
        return "SUCESSO! ✅ Agendamento realizado." if res.get("id") or res.get("success") else "Erro ao agendar."
    except: return "Erro conexão."

tools = [consultar_unidades, consultar_servicos, buscar_cliente, verificar_disponibilidade, agendar_horario]
tool_node = ToolNode(tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def call_model(state: AgentState):
    s = get_settings(); v = "knowledge/vaults/Brain/Helena"
    try:
        with open(f"{v}/Persona.md", "r", encoding="utf-8") as f: p = f.read()
        with open(f"{v}/Rules.md", "r", encoding="utf-8") as f: r = f.read()
        brain = f"{p}\n\n{r}"
    except: brain = "Helena, recepcionista."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=str(s.openai_api_key or s.OPENAI_API_KEY)).bind_tools(tools)
    
    all_msgs = state["messages"]
    window = all_msgs[-12:]
    while window and isinstance(window[0], ToolMessage): window = window[1:]
    
    sys = f"{brain}\n\nContexto: {state.get('context_data', {})}\nHoje: {_now_br().strftime('%d/%m/%Y %H:%M')}"
    try:
        return {"messages": [llm.invoke([SystemMessage(content=sys)] + (window if window else all_msgs[-1:]))]}
    except Exception as e:
        return {"messages": [AIMessage(content=f"Oscilação: {str(e)[:50]}. Tente de novo.")]}

def should_continue(state: AgentState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls: return "tools"
    return END

def create_pro_brain():
    wf = StateGraph(AgentState)
    wf.add_node("agent", call_model); wf.add_node("tools", tool_node)
    wf.set_entry_point("agent"); wf.add_conditional_edges("agent", should_continue); wf.add_edge("tools", "agent")
    return wf.compile(checkpointer=MemorySaver())
