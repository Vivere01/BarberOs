"""
BarberOS - ChatBarber PRO Engine v2.0
======================================
Engine dedicada para o sistema ChatBarber PRO.

Correções v2.0:
  - Filtro de horários passados (não oferece 09:00 se já são 15:00)
  - Fluxo de cadastro correto (nome + telefone + data de nascimento)
  - Identificação automática por telefone (sem pedir dados a clientes conhecidos)
  - Transcrição de áudio funcional (fix do campo OPENAI_API_KEY)
  - Agendamento imediato após confirmação (sem redundância)
  - Client com retry/timeout/pool
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

# Contexto de sessão PRO — isolado por coroutine
_pro_session_ctx: ContextVar[dict] = ContextVar("chatbarber_pro_session", default={})

def get_pro_client() -> ChatBarberProClient:
    """Retorna um cliente instanciado com as credenciais do contexto atual."""
    ctx = _pro_session_ctx.get({})
    token = ctx.get("api_token")
    owner = ctx.get("owner_id")
    
    from src.config.settings import get_settings
    settings = get_settings()
    
    if not token or not owner:
        # Fallback para configurações globais se ausente no contexto
        token = token or settings.openai_api_key
        owner = owner or settings.evolution_instance_name # Use instance_name como default se for o caso
        
    return ChatBarberProClient(
        api_token=token, 
        owner_id=owner,
        base_url=settings.cashbarber_base_url
    )

def set_pro_context(api_token: str, owner_id: str):
    """Define as credenciais para o request atual."""
    _pro_session_ctx.set({
        "api_token": api_token,
        "owner_id": owner_id
    })

# ===================================================================
# Helpers de Data/Hora — Brasília (UTC-3)
# ===================================================================
_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira",
            "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

_TZ_BRASILIA = ZoneInfo("America/Sao_Paulo")

def _now_brasilia() -> datetime:
    """Retorna datetime atual em Brasília."""
    return datetime.now(_TZ_BRASILIA)

def _get_datetime_context() -> str:
    """
    Retorna bloco de data/hora para o system prompt.
    Inclui hora exata (para filtro de horários passados) e próximos 7 dias.
    """
    now = _now_brasilia()
    dia_semana = _DIAS_PT[now.weekday()]
    mes = _MESES_PT[now.month - 1]
    
    # Próximos 7 dias
    proximos = []
    for i in range(1, 8):
        d = now + timedelta(days=i)
        proximos.append(f"  {_DIAS_PT[d.weekday()]}: {d.strftime('%d/%m/%Y')}")
    proximos_str = "\n".join(proximos)
    
    return (
        f"--- DATA E HORA ATUAL (Brasília / UTC-3) ---\n"
        f"Hoje é {dia_semana}, {now.day} de {mes} de {now.year}.\n"
        f"Hora atual: {now.strftime('%H:%M')} (BRT).\n"
        f"Data ISO: {now.strftime('%Y-%m-%d')}\n\n"
        f"PRÓXIMOS 7 DIAS:\n{proximos_str}\n\n"
        f"REGRA OBRIGATÓRIA: Ao chamar ferramentas, use datas no formato ISO 8601: YYYY-MM-DD.\n"
        f"REGRA DE HORÁRIOS: Hoje é dia {now.strftime('%Y-%m-%d')} e já são {now.strftime('%H:%M')}.\n"
        f"NUNCA ofereça horários iguais ou anteriores a {now.strftime('%H:%M')} para o dia de HOJE.\n"
        f"Para dias futuros, qualquer horário comercial é válido.\n"
    )

# ===================================================================
# Tools do ChatBarber PRO
# ===================================================================

def _limit_output(result: Any, max_len: int = 4000) -> str:
    res_str = str(result)
    if len(res_str) > max_len:
        logger.warning(f"TOOL_PAYLOAD_TOO_LARGE: Truncando de {len(res_str)} para {max_len}")
        return res_str[:max_len] + "... [TRUNCADO]"
    return res_str

@tool
async def consultar_unidades() -> str:
    """Consulta as unidades (lojas) disponíveis para obter o store_id correto. Use se houver dúvida sobre qual barbearia o cliente deseja."""
    try:
        client = get_pro_client()
        result = await client.list_stores()
        return _limit_output(result)
    except Exception as e:
        logger.error(f"TOOL_ERROR (consultar_unidades): {str(e)}")
        return "Não consegui listar as unidades."

@tool
async def consultar_servicos() -> str:
    """Consulta os serviços disponíveis (nome, preço, ID). Use antes de agendar para obter o serviceId correto."""
    try:
        client = get_pro_client()
        result = await client.list_services()
        if isinstance(result, dict) and result.get("error"):
            return "Serviçoes temporariamente indisponíveis. Pergunte ao cliente qual serviço deseja e siga em frente."
        return _limit_output(result)
    except Exception as e:
        logger.error(f"TOOL_ERROR (consultar_servicos): {str(e)}")
        return "Serviços indisponíveis no momento."

@tool
async def consultar_profissionais() -> str:
    """Consulta os barbeiros/profissionais disponíveis para obter um staffId válido. Seja discreto com nomes."""
    try:
        client = get_pro_client()
        result = await client.list_staff()
        if isinstance(result, dict) and result.get("error"):
            return ""
        return _limit_output(result)
    except Exception as e:
        logger.error(f"TOOL_ERROR (consultar_profissionais): {str(e)}")
        return ""

@tool
async def buscar_cliente(telefone: str) -> str:
    """
    Busca cadastro do cliente pelo telefone. SEMPRE use esta ferramenta na PRIMEIRA mensagem!
    Se encontrar: cumprimente pelo nome e não peça dados de cadastro.
    Se NÃO encontrar: peça nome completo, telefone e data de nascimento (DD/MM/AAAA).
    """
    try:
        client = get_pro_client()
        result = await client.search_client_by_phone(telefone)
        
        if result and result.get("found"):
            name = result.get("name", "")
            client_id = result.get("id", "")
            return (
                f"CLIENTE ENCONTRADO! Nome: {name}, ID: {client_id}. "
                f"Chame-o pelo nome de forma amigável. NÃO peça dados de cadastro. "
                f"Pergunte diretamente o que ele deseja agendar."
            )
        
        return (
            "CLIENTE NÃO CADASTRADO. Prossiga com o fluxo de cadastro:\n"
            "1. Peça o NOME COMPLETO\n"
            "2. Confirme o TELEFONE (já temos o WhatsApp)\n"
            "3. Peça a DATA DE NASCIMENTO (formato DD/MM/AAAA)\n"
            "Só depois disso, use a ferramenta 'cadastrar_cliente' para registrar."
        )
    except Exception as e:
        logger.error(f"TOOL_ERROR (buscar_cliente): {str(e)}")
        return "Não consegui verificar o cadastro. Pergunte o nome do cliente para prosseguir."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str) -> str:
    """
    Verifica horários DISPONÍVEIS para uma data (formato: YYYY-MM-DD).
    Retorna SOMENTE horários futuros e vagos (filtra ocupados e horários passados).
    """
    try:
        client = get_pro_client()
        # Filtra na fonte para evitar 'Payload Too Large'
        raw_data = await client.list_appointments(date_filter=data_yyyy_mm_dd)
        
        if isinstance(raw_data, dict) and raw_data.get("error"):
            return f"Indisponibilidade temporária para {data_yyyy_mm_dd}. Sugira horários próximos ao que o cliente deseja."
        
        # Extrai lista de agendamentos
        appts = raw_data.get("appointments", []) if isinstance(raw_data, dict) else (
            raw_data if isinstance(raw_data, list) else []
        )
        
        # Coleta horários ocupados (HH:MM)
        ocupados = set()
        for app in appts:
            sched = app.get("scheduledAt", "")
            if data_yyyy_mm_dd in sched and "T" in sched:
                # Exemplo: 2024-04-17T10:30:00 -> 10:30
                hm = sched.split("T")[1][:5]
                ocupados.add(hm)
        
        now = _now_brasilia()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        hora_atual_minutos = now.hour * 60 + now.minute
        
        # Define grade de horários comercial (08:00 às 19:30)
        disponiveis = []
        for h in range(8, 21):
            for m in [0, 30]:
                horario = f"{h:02d}:{m:02d}"
                horario_minutos = h * 60 + m
                
                # Se for hoje, pula horários passados (com margem de 15 min)
                if is_today and horario_minutos <= (hora_atual_minutos + 15):
                    continue
                
                if horario not in ocupados:
                    disponiveis.append(horario)
                    
        if not disponiveis:
            return f"Não há horários disponíveis para {data_yyyy_mm_dd}. Tente outro dia."
            
        horarios_str = ", ".join(disponiveis[:15]) # Limita para não estourar contexto
        
        if is_today:
            return f"Para HOJE ({data_yyyy_mm_dd}), temos: {horarios_str}."
        return f"Para o dia {data_yyyy_mm_dd}, temos: {horarios_str}."
            
    except Exception as e:
        logger.error(f"TOOL_ERROR (verificar_disponibilidade): {str(e)}")
        return "Não consegui acessar a agenda. Pergunte qual horário o cliente prefere."

@tool
async def cadastrar_cliente(nome: str, telefone: str, data_nascimento: str = "") -> str:
    """
    Cadastra um novo cliente no sistema.
    Parâmetros:
    - nome: Nome completo do cliente
    - telefone: Telefone com DDD (ex: 11999998888)
    - data_nascimento: Data de nascimento no formato YYYY-MM-DD (convertido de DD/MM/AAAA)
    """
    try:
        client = get_pro_client()
        raw_data = await client.create_client(
            name=nome, 
            phone=telefone,
            birth_date=data_nascimento if data_nascimento else None
        )
        
        if isinstance(raw_data, dict) and raw_data.get("error"):
            return f"Erro ao cadastrar: {raw_data.get('detail', 'erro desconhecido')}. Prossiga e tente agendar mesmo assim."
        
        # Tenta extrair o ID do cliente criado
        client_id = ""
        if isinstance(raw_data, dict):
            client_id = raw_data.get("id", raw_data.get("clientId", ""))
        
        return f"Cliente '{nome}' cadastrado com sucesso! ID: {client_id}. Agora prossiga para o agendamento."
    except Exception as e:
        logger.error(f"TOOL_ERROR (cadastrar_cliente): {str(e)}")
        return "Erro no cadastro, mas vamos prosseguir com o agendamento."

@tool
async def agendar_horario(client_id: str, service_id: str, data_isostring: str, staff_id: str = "", store_id: str = "") -> str:
    """CONFIRMA e cria o agendamento no sistema. SÓ use após o cliente dizer 'SIM' ou autorizar. Tente incluir staff_id e store_id se possível."""
    client = get_pro_client()
    try:
        if not store_id:
            stores = await client.list_stores()
            if isinstance(stores, list) and len(stores) == 1:
                store_id = str(stores[0].get("id", ""))
                
        if not staff_id:
            staff = await client.list_staff()
            if isinstance(staff, list) and len(staff) == 1:
                staff_id = str(staff[0].get("id", ""))
                
        if not store_id or not staff_id:
            return "ERRO DE VALIDAÇÃO: Faltou 'staff_id' ou 'store_id'. Use 'consultar_unidades' e 'consultar_profissionais' para descobrir os IDs, e pergunte ao cliente se necessário."

        res = await client.create_appointment(
            client_id=client_id,
            service_id=service_id,
            staff_id=staff_id,
            store_id=store_id,
            scheduled_at=data_isostring
        )
        
        if isinstance(res, dict):
            if res.get("status") in ["success", "created"] or "id" in res or "appointment" in res:
                return "SUCESSO: Agendamento realizado com êxito."
            err = res.get("error") or res.get("detail") or res.get("message")
            return f"ERRO: A API retornou: {err or 'Erro desconhecido'}"
            
        return f"ERRO: Resposta da API inesperada: {res}"
    except Exception as e:
        logger.error(f"TOOL_ERROR (agendar_horario): {str(e)}")
        return f"ERRO_CONEXAO: {str(e)}"


# ===================================================================
# Transcrição de Áudio
# ===================================================================
async def transcribe_audio(audio_base64: str) -> str:
    """Transcreve áudio base64 usando Whisper da OpenAI com diagnóstico profundo."""
    from openai import AsyncOpenAI
    from src.config.settings import get_settings
    import base64
    import tempfile
    import os
    
    settings = get_settings()
    # Pega qualquer uma das duas variáveis de chave (prioriza minúscula)
    api_key = settings.openai_api_key or settings.OPENAI_API_KEY
    
    if not api_key:
        logger.error("TRANSCRIPTION_ERROR: Chave OpenAI (OPENAI_API_KEY) não encontrada nas configurações.")
        return "[Sistema sem chave de API para áudio]"
        
    # Diagnóstico seguro da chave
    masked_key = f"{api_key[:7]}...{api_key[-4:]}" if len(api_key) > 10 else "INVÁLIDA"
    logger.info(f"AUDIO_DEBUG: Iniciando transcrição. Chave={masked_key}. Base64={len(audio_base64)} chars")
        
    client = AsyncOpenAI(api_key=api_key)
    tmp_path = None
    try:
        audio_data = base64.b64decode(audio_base64)
        # WhatsApp envia OGG/Opus. Whisper aceita .ogg.
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name
            
        try:
            with open(tmp_path, "rb") as audio_file:
                res = await client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file,
                    language="pt"
                )
            logger.info(f"TRANSCRIPTION_SUCCESS: '{res.text[:50]}...'")
            return res.text
        finally:
            if tmp_path and os.path.exists(tmp_path):
                os.remove(tmp_path)
    except Exception as e:
        logger.error("TRANSCRIPTION_FAILED", error=str(e))
        return ""


# ===================================================================
# Registro de Tools
# ===================================================================
tools = [
    consultar_unidades,
    consultar_servicos, 
    consultar_profissionais, 
    buscar_cliente, 
    verificar_disponibilidade, 
    cadastrar_cliente, 
    agendar_horario
]
tool_node = ToolNode(tools)

# ===================================================================
# Estado do Agente
# ===================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

# ===================================================================
# Sanitizador de Mensagens (Anti-400 da OpenAI)
# ===================================================================
def _sanitize_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
    """Remove ToolMessages órfãos do início da fatia que causam erro 400."""
    if not messages:
        return messages
    start = 0
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            has_ai_parent = False
            for j in range(i - 1, -1, -1):
                if isinstance(messages[j], AIMessage) and getattr(messages[j], "tool_calls", None):
                    has_ai_parent = True
                    break
                if isinstance(messages[j], HumanMessage):
                    break
            if not has_ai_parent:
                start = i + 1
        else:
            break
    if start > 0:
        logger.warning(f"SANITIZE: Removidas {start} ToolMessages órfãs")
    return messages[start:]

# ===================================================================
# Lógica do Modelo
# ===================================================================
def call_model(state: AgentState):
    settings = get_settings()
    
    # Carregamento do Cérebro via Obsidian Wiki (LLM Wiki)
    vault_path = "knowledge/vaults/Brain/Helena"
    try:
        with open(f"{vault_path}/Persona.md", "r", encoding="utf-8") as f:
            persona_content = f.read()
        with open(f"{vault_path}/Rules.md", "r", encoding="utf-8") as f:
            rules_content = f.read()
        with open(f"{vault_path}/Flows.md", "r", encoding="utf-8") as f:
            flows_content = f.read()
            
        base_persona = f"{persona_content}\n\n{rules_content}\n\n{flows_content}"
    except Exception as e:
        logger.warning(f"Wiki Brain não encontrado em {vault_path}, usando fallback: {e}")
        base_persona = "Você é a Helena, recepcionista virtual simpática."

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=str(settings.openai_api_key),
        max_retries=1,
        request_timeout=30
    )
    llm = llm.bind_tools(tools)
    
    telefone_cliente = state.get('context_data', {}).get('telefone_cliente', '')
    datetime_ctx = _get_datetime_context()
    
    system_content = f"""{base_persona}

--- CONTEXTO OPERACIONAL EM TEMPO REAL ---
{datetime_ctx}
Telefone do Cliente: {telefone_cliente}

Lembre-se: Você deve agir exatamente conforme as regras e fluxos definidos no seu Cérebro Obsidian acima.
"""

    system_msg = SystemMessage(content=system_content)

    # Janela de memória: últimas 15 mensagens, sanitizadas
    history = state["messages"][-15:]
    history = _sanitize_messages(history)
    messages = [system_msg] + history
    
    try:
        response = llm.invoke(messages)
        return {"messages": [response]}
    except Exception as e:
        logger.error(f"PRO_BRAIN_INVOKE_ERROR: {str(e)}")
        return {"messages": [AIMessage(content="Poxa, deu uma oscilação aqui no meu sistema, você me perdoa? Poderia repetir o que deseja? 😊")]}

# ===================================================================
# Verificador de Fluxo
# ===================================================================
def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if hasattr(last_message, "tool_calls") and last_message.tool_calls:
        return "tools"
    return END

# ===================================================================
# Construção do Grafo
# ===================================================================
def create_pro_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())
