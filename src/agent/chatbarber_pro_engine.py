"""
BarberOS - ChatBarber PRO Engine v2.7 (Tank Edition)
===================================================
Versão final de estabilidade: Busca flexível de lojas, 
exposição de horários no prompt e resiliência total.
"""
import base64, tempfile, os
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
        audio_bytes = base64.b64decode(audio_base64)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_bytes); p = tmp.name
        try:
            with open(p, "rb") as f:
                res = await client.audio.transcriptions.create(model="whisper-1", file=f, language="pt")
            return res.text
        finally: 
            if os.path.exists(p): os.remove(p)
    except: return ""

def _now_br() -> datetime:
    return datetime.now(BR_TZ)

@tool
async def consultar_unidades() -> str:
    """Retorna unidades COM horários de funcionamento detalhados."""
    try:
        stores = await get_pro_client().list_stores()
        if not stores: return "Nenhuma unidade cadastrada."
        res = []
        for s in stores:
            bh_str = []
            for bh in s.get("businessHours", []):
                if bh.get("isOpen"):
                    # Tradução amigável do dia da semana se possível
                    dias = {0: "Dom", 1: "Seg", 2: "Ter", 3: "Qua", 4: "Qui", 5: "Sex", 6: "Sáb", 7: "Dom"}
                    d_val = bh.get('dayOfWeek')
                    d_name = dias.get(int(d_val)) if str(d_val).isdigit() else d_val
                    bh_str.append(f"{d_name}: {bh.get('openTime') or bh.get('startTime')}-{bh.get('closeTime') or bh.get('endTime')}")
            res.append(f"UNIDADE: {s.get('name')} (ID: {s.get('id')})\nEndereço: {s.get('address')}\nHorários: {', '.join(bh_str)}")
        return "\n\n".join(res)
    except Exception as e: return f"Erro ao listar lojas: {e}"

@tool
async def consultar_servicos() -> str:
    """Lista serviços e preços."""
    try: return str(await get_pro_client().list_services())
    except: return "Serviços indisponíveis."

@tool
async def buscar_cliente(telefone: str) -> str:
    """Busca cliente cadastrado."""
    try:
        res = await get_pro_client().search_client_by_phone(telefone)
        return f"CLIENTE_ENCONTRADO: {res.get('name')} (ID: {res.get('id')})" if res.get("found") else "CLIENTE_NAO_CADASTRADO."
    except: return "Erro na busca."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str, store_id: str = "") -> str:
    """Verifica agenda de uma unidade específica. Use YYYY-MM-DD."""
    try:
        if not data_yyyy_mm_dd: return "Por favor, informe a data no formato YYYY-MM-DD."
        client = get_pro_client()
        stores = await client.list_stores()
        
        if not stores: return "Nenhuma unidade encontrada no sistema."

        # Busca flexível por ID ou por Parte do Nome
        sel = next((s for s in stores if str(s.get("id")) == str(store_id) or (store_id and str(store_id).lower() in str(s.get("name")).lower())), None)
        if not sel:
            if len(stores) == 1: sel = stores[0]
            else: return f"Por favor, especifique qual unidade: {', '.join([s['name'] for s in stores])}"

        staff = await client.list_staff()
        # Filtro de staff resiliente: se a loja selecionada for a única ou o staff não tiver storeId, inclui
        ustaff = [s for s in staff if str(s.get("storeId")) == str(sel.get("id"))]
        if not ustaff and len(stores) == 1: ustaff = staff # Fallback para única unidade
        
        if not ustaff:
            return f"Não encontramos profissionais disponíveis para a unidade {sel.get('name')}."

        appts_res = await client.list_appointments(date=data_yyyy_mm_dd)
        appts = appts_res.get("appointments", [])
        
        # Mapeamento do dia da semana (API costuma usar 0-6 ou 1-7)
        dt = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        day_py = dt.weekday() # 0=Seg, 6=Dom
        day_0_sun = (day_py + 1) % 7 # 0=Dom, 1=Seg
        day_1_mon = day_py + 1 # 1=Seg, 7=Dom
        
        # Busca o horário de funcionamento (Business Hours)
        bhs = sel.get("businessHours", [])
        bh = next((h for h in bhs if str(h.get("dayOfWeek")) in [str(day_0_sun), str(day_1_mon)]), None)
        
        if not bh or not bh.get("isOpen"):
            # Diagnostic message para o log/IA
            dias_abertos = [str(h.get("dayOfWeek")) for h in bhs if h.get("isOpen")]
            return f"A unidade {sel.get('name')} não possui expediente aberto para o dia informado ({data_yyyy_mm_dd}). Tente outro dia."

        # Suporte a diferentes nomes de campos de horário
        o_t = bh.get("openTime") or bh.get("startTime") or "08:00"
        c_t = bh.get("closeTime") or bh.get("endTime") or "19:00"
        
        try:
            sh, sm = map(int, o_t.split(":"))
            eh, em = map(int, c_t.split(":"))
        except:
            sh, sm, eh, em = 8, 0, 19, 0

        ocup = {str(s["id"]): set() for s in ustaff}
        names = {str(s["id"]): s["name"] for s in ustaff}
        
        for a in appts:
            sid = str(a.get("staffId"))
            if sid in ocup and a.get("scheduledAt"):
                try:
                    # Tenta parsear ISO ou extrair hora direto
                    if "T" in a["scheduledAt"]:
                        dt_utc = datetime.fromisoformat(a["scheduledAt"].replace("Z", "+00:00"))
                        dt_br = dt_utc.astimezone(BR_TZ)
                        h_str = dt_br.strftime("%H:%M")
                    else:
                        h_str = a["scheduledAt"][:5]
                    ocup[sid].add(h_str)
                except: continue

        now = _now_br()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        cutoff_min = now.hour * 60 + now.minute + 15 # 15 min de antecedência mínima
        
        rel = [f"Disponibilidade em {sel.get('name')} para {data_yyyy_mm_dd}:"]
        found_any = False
        
        for sid, ocu in ocup.items():
            slots = []
            ch, cm = sh, sm
            while (ch * 60 + cm) < (eh * 60 + em):
                h_str = f"{ch:02d}:{cm:02d}"
                if not is_today or (ch * 60 + cm) > cutoff_min:
                    if h_str not in ocu: slots.append(h_str)
                cm += 30
                if cm >= 60: ch += 1; cm = 0
            if slots:
                rel.append(f"- {names[sid]}: {', '.join(slots)}")
                found_any = True
        
        if not found_any:
            return f"Infelizmente todos os horários para {data_yyyy_mm_dd} na unidade {sel.get('name')} já estão ocupados."
            
        return "\n".join(rel)
    except Exception as e:
        logger.error(f"ERRO_DISPONIBILIDADE: {e}")
        return f"Erro técnico ao verificar agenda: {e}"

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """Confirma o agendamento no sistema."""
    try:
        res = await get_pro_client().create_appointment({"clientId": client_id, "serviceId": service_id, "staffId": staff_id, "storeId": store_id, "scheduledAt": data_isostring})
        return "AGENDADO COM SUCESSO! ✅" if res.get("id") or res.get("success") else "Erro ao finalizar."
    except: return "Erro de comunicação."

tools = [consultar_unidades, consultar_servicos, buscar_cliente, verificar_disponibilidade, agendar_horario]
tool_node = ToolNode(tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def call_model(state: AgentState):
    s = get_settings()
    try:
        with open("knowledge/vaults/Brain/Helena/Persona.md", "r", encoding="utf-8") as f: p = f.read()
        with open("knowledge/vaults/Brain/Helena/Rules.md", "r", encoding="utf-8") as f: r = f.read()
        brain = f"{p}\n\n{r}"
    except: brain = "Helena, recepcionista oficial."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=str(s.openai_api_key or s.OPENAI_API_KEY)).bind_tools(tools)
    
    # Limpeza de histórico para evitar Erro 400
    msgs = state["messages"]
    window = msgs[-10:] # Janela menor e mais segura
    while window and isinstance(window[0], ToolMessage): window = window[1:]
    
    sys = f"{brain}\n\nContexo: {state.get('context_data', {})}\nData/Hora Agora: {_now_br().strftime('%d/%m/%Y %H:%M')}"
    try:
        return {"messages": [llm.invoke([SystemMessage(content=sys)] + (window if window else msgs[-1:]))]}
    except Exception as e:
        return {"messages": [AIMessage(content="Puxa, tivemos uma oscilação. Pode repetir seu pedido?")]}

def should_continue(state: AgentState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls: return "tools"
    return END

def create_pro_brain():
    wf = StateGraph(AgentState)
    wf.add_node("agent", call_model); wf.add_node("tools", tool_node)
    wf.set_entry_point("agent"); wf.add_conditional_edges("agent", should_continue); wf.add_edge("tools", "agent")
    return wf.compile(checkpointer=MemorySaver())
