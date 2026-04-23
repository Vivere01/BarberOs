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
from dateutil import parser
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
DEFAULT_TZ = "America/Sao_Paulo"

def _now_br(tz_name: str = None): 
    try:
        return datetime.now(ZoneInfo(tz_name or DEFAULT_TZ))
    except:
        return datetime.now(ZoneInfo(DEFAULT_TZ))

def _get_calendar_reference():
    """Gera uma tabela de referência de dias da semana para os próximos 14 dias."""
    now = _now_br()
    days = ["Segunda-feira", "Terça-feira", "Quarta-feira", "Quinta-feira", "Sexta-feira", "Sábado", "Domingo"]
    lines = [f"CALENDÁRIO DE REFERÊNCIA (HOJE É {days[now.weekday()]}, {now.strftime('%d/%m/%Y')}):"]
    for i in range(1, 15):
        d = now + timedelta(days=i)
        lines.append(f"- {d.strftime('%d/%m/%Y')}: {days[d.weekday()]}")
    return "\n".join(lines)

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

# A função _now_br agora é dinâmica e reside no topo do arquivo.

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
    """Lista serviços com ID e Preço."""
    try:
        res = await get_pro_client().list_services()
        out = ["Serviços disponíveis:"]
        for s in res:
            out.append(f"- {s.get('name')} (ID: {s.get('id')}) - R$ {s.get('price')}")
        return "\n".join(out)
    except: return "Serviços indisponíveis no momento."

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
        
        # Mapeamento do dia da semana resiliente
        dt = datetime.strptime(data_yyyy_mm_dd, "%Y-%m-%d")
        day_py = dt.weekday() 
        days_to_check = [
            str(day_py),             # 0=Seg (Padrão Python)
            str((day_py + 1) % 7),   # 0=Dom (Padrão JS/API)
            str(day_py + 1)          # 1=Seg (Padrão ISO)
        ]
        
        # Busca o horário de funcionamento (Business Hours)
        bhs = sel.get("businessHours", [])
        # MAPEAMENTO ROBUSTO DE DIAS (Suporta Número ou Nome em PT/EN)
        day_map = {
            "0": ["0", "domingo", "sunday"],
            "1": ["1", "segunda", "monday", "segunda-feira"],
            "2": ["2", "terça", "tuesday", "terça-feira"],
            "3": ["3", "quarta", "wednesday", "quarta-feira"],
            "4": ["4", "quinta", "thursday", "quinta-feira"],
            "5": ["5", "sexta", "friday", "sexta-feira"],
            "6": ["6", "sábado", "saturday"]
        }
        
        target_day = str(dt.weekday())
        bh = next((h for h in bhs if str(h.get("dayOfWeek")).lower() in day_map.get(target_day, [])), None)
        
        # FALLBACK PARA 20:00 (Conforme configuração do cliente)
        if not bh or not bh.get("isOpen", True):
            o_t, c_t = "08:00", "20:00"
            is_fallback = True
        else:
            o_t = bh.get("openTime") or bh.get("startTime") or bh.get("start") or "08:00"
            c_t = bh.get("closeTime") or bh.get("endTime") or bh.get("end") or "20:00"
            is_fallback = False
        
        # DETECÇÃO DE FUSO HORÁRIO DINÂMICO
        tz_name = sel.get("timezone") or sel.get("ianaTimezone") or DEFAULT_TZ
        try:
            tz = ZoneInfo(tz_name)
        except:
            tz = ZoneInfo(DEFAULT_TZ)
        now_local = datetime.now(tz)

        # LOG CIRÚRGICO DE ENTRADA [AGENDAMENTO_DEBUG]
        diag_log = {
            "timestamp_requisicao": now_local.isoformat(),
            "timezone_detectado": tz_name,
            "unidade_solicitada": store_id,
            "data_hora_solicitada": data_yyyy_mm_dd,
            "etapa": "INICIO_CONSULTA"
        }
        logger.info("AGENDAMENTO_DEBUG", **diag_log)

        try:
            sh, sm = map(int, o_t.split(":"))
            eh, em = map(int, c_t.split(":"))
        except Exception as e:
            logger.error("AGENDAMENTO_DEBUG_PARSE_ERROR", error=str(e), open_time=o_t, close_time=c_t)
            sh, sm, eh, em = 8, 0, 19, 0

        ocup = {str(s["id"]): set() for s in ustaff}
        names = {str(s["id"]): s["name"] for s in ustaff}
        
        for a in appts:
            sid = str(a.get("staffId"))
            if sid in ocup and a.get("scheduledAt"):
                try:
                    # Tenta parsear ISO ou extrair hora direto
                    if "T" in a["scheduledAt"]:
                        # Tratamos o horário da API como 'Relógio de Parede' (Naive)
                        # Ignoramos o offset para evitar que 10:00 vire 07:00 ao ler do banco
                        item_dt = parser.parse(a['scheduledAt']).replace(tzinfo=None)
                        h_str = item_dt.strftime("%H:%M")
                    else:
                        h_str = a["scheduledAt"][:5]
                    ocup[sid].add(h_str)
                except: continue

        is_today = data_yyyy_mm_dd == now_local.strftime("%Y-%m-%d")
        cutoff_min = now_local.hour * 60 + now_local.minute + 5 # 5 min de antecedência mínima
        
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
                rel.append(f"- {names[sid]} (ID: {sid}): {', '.join(slots)}")
                found_any = True
        
        # LOG CIRÚRGICO DE SAÍDA [AGENDAMENTO_DEBUG] (Mantemos os detalhes no log do servidor)
        final_slots = [row for row in rel if row.startswith("- ")]
        diag_log_out = {
            "unidade_id_resolvido": sel.get("id"),
            "unidade_nome_resolvido": sel.get("name"),
            "horario_funcionamento_encontrado": {"open": o_t, "close": c_t, "is_fallback": is_fallback},
            "resultado_verificacao_disponibilidade": found_any,
            "motivo_indisponibilidade": "SEM_SLOTS_LIVRES" if not found_any else None,
            "slots_disponiveis_encontrados": final_slots,
            "etapa": "FIM_CONSULTA"
        }
        logger.info("AGENDAMENTO_DEBUG", **diag_log_out)
        
        # RETORNO PARA A IA: Limpo e sem dados técnicos que causem confusão
        if not found_any:
            return f"[FONTE_DE_VERDADE_API] Status: INDISPONÍVEL. Motivo: Todos os horários (das {o_t} às {c_t}) na unidade {sel.get('name')} para {data_yyyy_mm_dd} já estão ocupados ou o horário solicitado já passou. PARE e ofereça outro dia."
            
        return f"[FONTE_DE_VERDADE_API] Status: DISPONÍVEL (Unidade {sel.get('name')} aberta das {o_t} às {c_t}). Slots livres encontrados:\n" + "\n".join(final_slots)
    except Exception as e:
        logger.error("AGENDAMENTO_DEBUG_CRITICAL_ERROR", error=str(e), exc_info=True)
        return f"Houve um problema técnico ao consultar a agenda (Motivo: {str(e)}). Por favor, aguarde um instante ou peça para falar com um atendente humano."

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """Confirma o agendamento no sistema."""
    if not service_id or service_id == "None":
        return "Para concluir, por favor, pergunte ao cliente qual serviço ele deseja realizar (ex: Corte, Barba, etc) e mostre as opções se necessário."
    
    client = get_pro_client()
    
    # RESOLUÇÃO DE IDS (Suporta lista para Combos)
    try:
        if store_id and not (len(store_id) > 20 and store_id.startswith("cmn")):
            ss = await client.list_stores()
            f = next((s for s in ss if store_id.lower() in s["name"].lower()), None)
            if f: store_id = f["id"]

        # Resolver Service IDs (Separa por vírgula, ' e ', '&')
        import re
        # Normaliza separadores para vírgula
        raw_services = re.split(r',| e | & ', service_id, flags=re.IGNORECASE)
        names_to_resolve = [s.strip() for s in raw_services if s.strip()]
        
        resolved_ids = []
        svs = await client.list_services()
        for name in names_to_resolve:
            # Se já for um ID (formato comum de UUID ou ID da API)
            if len(name) > 20: 
                resolved_ids.append(name)
                continue
            
            # Busca por nome (case insensitive e parcial)
            f = next((s for s in svs if name.lower() in s["name"].lower()), None)
            if f: 
                resolved_ids.append(f["id"])
            else:
                # Tenta busca reversa: se o nome do serviço da API está contido no que o cliente disse
                f_rev = next((s for s in svs if s["name"].lower() in name.lower()), None)
                if f_rev: resolved_ids.append(f_rev["id"])

        if not resolved_ids:
            return f"Não consegui identificar os serviços '{service_id}' no sistema. Por favor, use nomes como aparecem na lista."
        
        service_id = ",".join(resolved_ids)
        
        # Resolver Staff
        if not staff_id or not (len(staff_id) > 20 and staff_id.startswith("cmn")):
            stf = await client.list_staff()
            f = next((s for s in stf if staff_id and staff_id.lower() in s["name"].lower()), None)
            if not f and stf: f = stf[0]
            if f: staff_id = f["id"]
    except: pass

    # MODO RELÓGIO DE PAREDE (Garante o 'T' para o ISO 8601 estrito)
    try:
        # Substitui espaço por T se necessário
        if " " in data_isostring:
            data_isostring = data_isostring.replace(" ", "T")
        
        clean_date = data_isostring.split(".")[0]
        if "T" not in clean_date: # Caso venha apenas a data
             return "Erro: Formato de hora inválido. Certifique-se de ter a hora escolhida."
             
        if len(clean_date) > 19: clean_date = clean_date[:19]
        data_isostring = f"{clean_date}.000Z"
    except Exception as e:
        logger.error("DATE_FORMAT_ERROR", date=data_isostring, error=str(e))

    try:
        # Enviamos para a API. Se a API não suportar lista, o primeiro serviço será priorizado o erro será logado.
        res = await client.create_appointment({
            "clientId": client_id, 
            "serviceId": service_id, # Enviando a lista separada por vírgula
            "staffId": staff_id, 
            "storeId": store_id, 
            "scheduledAt": data_isostring
        })
        
        if res.get("id") or res.get("success"):
            return "AGENDADO COM SUCESSO! ✅ Lembre o cliente de chegar 5 min antes."
        return f"Erro técnico na API: {res.get('message') or res.get('error') or 'Desconhecido'}."
    except Exception as e:
        logger.error("AGENDAMENTO_FINAL_ERROR", error=str(e), payload={
            "clientId": client_id, "serviceId": service_id, "staffId": staff_id, "storeId": store_id, "scheduledAt": data_isostring
        }, exc_info=True)
        return f"Erro técnico ao registrar no banco de dados (Motivo: {str(e)}). Por favor, tente novamente ou fale com um humano."

tools = [consultar_unidades, consultar_servicos, buscar_cliente, verificar_disponibilidade, agendar_horario]
tool_node = ToolNode(tools)

class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

async def call_model(state: AgentState):
    s = get_settings()
    try:
        with open("knowledge/vaults/Brain/Helena/Persona.md", "r", encoding="utf-8") as f: p = f.read()
        with open("knowledge/vaults/Brain/Helena/Rules.md", "r", encoding="utf-8") as f: r = f.read()
        brain = f"{p}\n\n{r}"
    except: brain = "Helena, recepcionista oficial."

    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0, openai_api_key=str(s.openai_api_key or s.OPENAI_API_KEY)).bind_tools(tools)
    
    messages = state["messages"]
    # Janela maior (40) para suportar combos de serviços e evitar quebra de protocolo ToolCall
    window = messages[-40:] 
    
    # Prevenção de ToolMessage Órfã: Se a janela começar com ToolMessage, removemos para evitar erro 400
    while window and isinstance(window[0], ToolMessage):
        window = window[1:]
    
    # Tenta pegar o fuso da primeira loja para o prompt (Data/Hora Agora)
    client = get_pro_client()
    try:
        stores_prompt = await client.list_stores()
        main_tz = stores_prompt[0].get("timezone") or stores_prompt[0].get("ianaTimezone") if stores_prompt else DEFAULT_TZ
    except:
        main_tz = DEFAULT_TZ
        
    now_str = _now_br(main_tz).strftime("%d/%m/%Y %H:%M")
    cal = _get_calendar_reference() # O calendário também usa _now_br internamente
    
    sys = f"{brain}\n\n{cal}\n\n"
    sys += "PROTOCOLO DE ATENDIMENTO (OBRIGATÓRIO):\n"
    sys += "1. IDENTIFICAÇÃO: Se o cliente não for reconhecido pelo telefone, peça o nome.\n"
    sys += "2. UNIDADE: SEMPRE confirme a Unidade física antes de mostrar horários.\n"
    sys += "3. PREFERÊNCIA: Pergunte explicitamente se o cliente tem preferência por algum barbeiro específico.\n"
    sys += "4. DISPONIBILIDADE: Mostre os horários baseados na unidade e profissional escolhido.\n"
    sys += "5. COMBOS: Se o cliente pedir vários serviços (ex: Corte e Barba), envie TODOS os IDs de serviço separados por vírgula no agendamento.\n\n"
    sys += f"[DADO VERIFICADO PELA API - NÃO QUESTIONE]\nContexo: {state.get('context_data', {})}\nData/Hora Agora: {now_str}\n\n"
    sys += "REGRA ABSOLUTA: Confie exclusivamente nos retornos marcados como [FONTE_DE_VERDADE_API].\n"
    sys += "REGRA DE FLUXO: Se uma ferramenta retornar que precisa de mais informações (como o serviço), NÃO peça desculpas por erro técnico. Apenas pergunte ao cliente de forma natural.\n"
    sys += "REGRA DE PREFERÊNCIA: Respeite SEMPRE a preferência do cliente por um barbeiro. Se ele mencionar um nome (ex: Juarez), use o staffId dele."
    
    try:
        response = llm.invoke([SystemMessage(content=sys)] + window)
        
        # LOG DE DECISÃO DO AGENTE [AGENT_DECISION]
        logger.info("AGENT_DECISION", 
            pergunta_usuario=window[-1].content if window else "",
            resposta_gerada=response.content,
            usou_ferramenta=bool(response.tool_calls)
        )
        
        return {"messages": [response]}
    except Exception as e:
        logger.error("AGENT_DECISION_ERROR", error=str(e))
        return {"messages": [AIMessage(content="Puxa, tivemos uma oscilação técnica. Pode repetir seu pedido?")]}

def should_continue(state: AgentState):
    if hasattr(state["messages"][-1], "tool_calls") and state["messages"][-1].tool_calls: return "tools"
    return END

def create_pro_brain():
    wf = StateGraph(AgentState)
    wf.add_node("agent", call_model); wf.add_node("tools", tool_node)
    wf.set_entry_point("agent"); wf.add_conditional_edges("agent", should_continue); wf.add_edge("tools", "agent")
    return wf.compile(checkpointer=MemorySaver())
