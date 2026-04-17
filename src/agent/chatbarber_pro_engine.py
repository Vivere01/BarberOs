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
    
    if not token or not owner:
        raise ValueError("Credenciais PRO ausentes no contexto da sessão.")
        
    return ChatBarberProClient(api_token=token, owner_id=owner)

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
    Retorna SOMENTE horários futuros (filtra horários já passados no dia de hoje).
    """
    try:
        client = get_pro_client()
        raw_data = await client.list_appointments()
        
        if isinstance(raw_data, dict) and raw_data.get("error"):
            return f"Erro ao consultar agenda para {data_yyyy_mm_dd}. Sugira horários como 10h, 14h ou 16h."
        
        appts = raw_data.get("appointments", []) if isinstance(raw_data, dict) else (
            raw_data if isinstance(raw_data, list) else []
        )
        
        # Coleta horários já ocupados nesta data
        ocupados = set()
        for app in appts:
            sched = app.get("scheduledAt", "")
            if data_yyyy_mm_dd in sched:
                # Extrai HH:MM do scheduledAt
                try:
                    dt = datetime.fromisoformat(sched.replace("Z", "+00:00"))
                    dt_brasilia = dt.astimezone(_TZ_BRASILIA)
                    ocupados.add(dt_brasilia.strftime("%H:%M"))
                except Exception:
                    ocupados.add(sched)
        
        # ========== FIX BUG #2: Filtro de horários passados ==========
        now = _now_brasilia()
        is_today = data_yyyy_mm_dd == now.strftime("%Y-%m-%d")
        hora_atual_minutos = now.hour * 60 + now.minute
        
        # Gera grade de horários comerciais (08:00 às 20:00, intervalos de 30min)
        todos_horarios = []
        for h in range(8, 20):
            for m in [0, 30]:
                horario = f"{h:02d}:{m:02d}"
                horario_minutos = h * 60 + m
                
                # Se é hoje, filtra horários que já passaram (com margem de 30 min)
                if is_today and horario_minutos <= (hora_atual_minutos + 30):
                    continue
                    
                if horario not in ocupados:
                    todos_horarios.append(horario)
        
        if not todos_horarios:
            return f"Na data {data_yyyy_mm_dd}, não há horários disponíveis. Sugira outra data ao cliente."
        
        horarios_str = ", ".join(todos_horarios[:10])  # Limita a 10 sugestões
        
        if is_today:
            return (
                f"Como já são {now.strftime('%H:%M')}, os horários disponíveis para HOJE ({data_yyyy_mm_dd}) são: "
                f"{horarios_str}. Ofereça essas opções ao cliente."
            )
        
        return (
            f"Na data {data_yyyy_mm_dd}, os horários disponíveis são: {horarios_str}. "
            f"Apresente ao cliente e pergunte qual prefere."
        )
        
    except Exception as e:
        logger.error(f"TOOL_ERROR (verificar_disponibilidade): {str(e)}")
        return f"Não consegui verificar a agenda para {data_yyyy_mm_dd}. Sugira horários genéricos ao cliente."

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
async def agendar_horario(cliente_id: str, servico_id: str, profissional_id: str, horario_completo: str) -> str:
    """
    Realiza o agendamento final.
    Parâmetros:
    - cliente_id: ID do cliente (obtido de buscar_cliente ou cadastrar_cliente)
    - servico_id: ID do serviço (obtido de consultar_servicos)
    - profissional_id: ID do profissional/staffId (obtido de consultar_profissionais)
    - horario_completo: Data e hora no formato YYYY-MM-DDTHH:MM:00Z (ex: 2026-04-17T15:30:00Z)
    """
    try:
        client = get_pro_client()
        ctx = _pro_session_ctx.get({})
        store_id = ctx.get("owner_id", "default")
        
        raw_data = await client.create_appointment(
            client_id=cliente_id,
            service_id=servico_id,
            staff_id=profissional_id,
            store_id=store_id,
            scheduled_at=horario_completo
        )
        
        if isinstance(raw_data, dict) and raw_data.get("error"):
            return (
                f"FALHA NO AGENDAMENTO: {raw_data.get('detail', 'IDs inválidos ou erro técnico')}. "
                f"Verifique se os IDs de serviço e profissional estão corretos."
            )
        
        return (
            f"AGENDAMENTO CRIADO COM SUCESSO! "
            f"Confirme ao cliente com entusiasmo que está tudo pronto."
        )
    except Exception as e:
        logger.error(f"TOOL_ERROR (agendar_horario): {str(e)}")
        return f"FALHA: {str(e)}. Verifique IDs corretos de serviço e profissional."


# ===================================================================
# Transcrição de Áudio
# ===================================================================
async def transcribe_audio(audio_base64: str) -> str:
    """Transcrição usando OpenAI Whisper."""
    settings = get_settings()
    
    # FIX BUG #4: Usa o campo correto — openai_api_key (minúsculo, via pydantic)
    api_key = settings.openai_api_key or settings.OPENAI_API_KEY
    
    if not api_key:
        logger.error("TRANSCRIPTION_ERROR: OPENAI_API_KEY não configurada.")
        return ""
        
    try:
        import base64
        import tempfile
        import os
        from openai import OpenAI
        
        client = OpenAI(api_key=str(api_key))
        
        audio_data = base64.b64decode(audio_base64)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
            tmp_file.write(audio_data)
            tmp_path = tmp_file.name
            
        try:
            with open(tmp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language="pt"  # Força português para melhor acurácia
                )
            logger.info(f"TRANSCRIPTION_SUCCESS: {len(transcript.text)} chars")
            return transcript.text
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
    except Exception as e:
        logger.error(f"TRANSCRIPTION_ERROR: {str(e)}")
        return ""


# ===================================================================
# Registro de Tools
# ===================================================================
tools = [
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
            prev = messages[i - 1] if i > 0 else None
            if prev is None or not (isinstance(prev, AIMessage) and getattr(prev, "tool_calls", None)):
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
    
    # ===================================================================
    # PERSONA E REGRAS — Reescrito para eliminar redundância (BUG #5)
    # ===================================================================
    system_content = f"""{datetime_ctx}

--- PERSONA ---
Seu nome é Helena. Você é a recepcionista virtual da Barbearia. Fale como uma pessoa real, simpática e direta.

--- FLUXO DE ATENDIMENTO (SIGA EXATAMENTE) ---

PASSO 1 — IDENTIFICAÇÃO AUTOMÁTICA:
- O telefone deste cliente é: {telefone_cliente}
- Na sua PRIMEIRA resposta, use a ferramenta 'buscar_cliente' com este número.
- Se o cliente JÁ FOI ENCONTRADO no histórico, NÃO busque de novo.

PASSO 2 — CADASTRO (só se buscar_cliente retornar "NÃO CADASTRADO"):
- Peça NOME COMPLETO
- Confirme o TELEFONE
- Peça DATA DE NASCIMENTO (DD/MM/AAAA)
- Use 'cadastrar_cliente' com esses dados (converta nascimento para YYYY-MM-DD)

PASSO 3 — AGENDAMENTO:
- Pergunte qual SERVIÇO deseja (use 'consultar_servicos' para obter IDs reais)
- Pergunte a DATA desejada
- Use 'verificar_disponibilidade' para mostrar horários livres
- NUNCA ofereça horários que já passaram no dia de hoje
- Use 'consultar_profissionais' para obter um staffId (seja discreto, não cite nomes a menos que o cliente peça)

PASSO 4 — CONFIRMAÇÃO E AGENDAMENTO IMEDIATO:
- Quando o cliente escolher serviço + data + horário, resuma:
  "Perfeito! [SERVIÇO] no dia [DATA] às [HORA]. Posso confirmar?"
- Quando o cliente disser SIM/PODE/CONFIRMA/BORA:
  → Use IMEDIATAMENTE 'agendar_horario' com os IDs corretos
  → Depois responda: "Tudo pronto! Seu agendamento foi confirmado para [DATA] às [HORA]. Te espero lá! 💈"
- NÃO pergunte duas vezes. NÃO peça confirmação novamente após ele já ter confirmado.

--- REGRAS OBRIGATÓRIAS ---
1. ANTI-ROBÔ: Nunca mencione "ferramentas", "sistema", "API", "verificando". Aja como humana.
2. ANTI-REDUNDÂNCIA: Se o cliente já respondeu algo, NÃO pergunte de novo.
3. ERRO SILENCIOSO: Se algo der erro, diga "Puxa, deu uma oscilação, pode repetir?" — sem detalhes técnicos.
4. NOMES DE BARBEIROS: Nunca cite nomes de profissionais a menos que o cliente pergunte especificamente.
5. RESPOSTAS CURTAS: Máximo 3 frases por mensagem. Seja direta.
6. AGENDAMENTO RÁPIDO: Após a primeira confirmação do cliente, agende IMEDIATAMENTE. Sem enrolação.
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
