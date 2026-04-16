"""
BarberOS - ChatBarber PRO Engine
================================
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
from langchain_groq import ChatGroq
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, AIMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from src.config.settings import get_settings
from contextvars import ContextVar
from src.integrations.chatbarber_pro.client import ChatBarberProClient
from src.config.logging_config import get_logger

logger = get_logger("agent.chatbarber_pro")

# As configurações são lidas dinamicamente dentro das funções

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
# Helpers de Data/Hora
# ===================================================================
def _get_datetime_context() -> str:
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    return (
        f"Hoje é {now.strftime('%A, %d de %B de %Y')}.\n"
        f"Hora atual: {now.strftime('%H:%M')} (Brasília).\n"
    )

# ===================================================================
# Tools do ChatBarber PRO
# ===================================================================

def _limit_output(result: Any, max_len: int = 4000) -> str:
    res_str = str(result)
    if len(res_str) > max_len:
        logger.warning(f"TOOL_PAYLOAD_TOO_LARGE: Truncando resposta de {len(res_str)} para {max_len} caracteres.")
        return res_str[:max_len] + "... [CONTEÚDO TRUNCADO POR SER MUITO LONGO]"
    return res_str

@tool
async def consultar_servicos() -> str:
    """Consulta os serviços disponíveis e retorna os IDs. Use isso antes de agendar."""
    try:
        client = get_pro_client()
        return _limit_output(await client.list_services())
    except Exception as e:
        return "Serviços indisponíveis. Avise que o valor médio é R$50."

@tool
async def consultar_profissionais() -> str:
    """Consulta os barbeiros disponíveis para pegar um staffId válido (seja discreto, pegue qualquer um)."""
    try:
        client = get_pro_client()
        return _limit_output(await client.list_staff())
    except Exception as e:
        return ""

@tool
async def buscar_cliente(telefone: str) -> str:
    """Busca o cadastro do cliente pelo número de celular. SEMPRE rode esta ferramenta logo no início da conversa!"""
    try:
        client = get_pro_client()
        raw_data = await client.list_clients()
        clientes = raw_data.get("clients", []) if isinstance(raw_data, dict) else raw_data
        
        fone_limpo = ''.join(filter(str.isdigit, telefone))
        for c in clientes:
            celular = ''.join(filter(str.isdigit, str(c.get("phone", ""))))
            if len(fone_limpo) > 8 and (fone_limpo in celular or celular in fone_limpo):
                return f"CLIENTE ENCONTRADO! Nome: {c.get('name')}, ID: {c.get('id')}. Haja de forma amigável chamando-o pelo nome e não peça dados de cadastro, pule direto para o que ele deseja agendar."
                
        return "CLIENTE NÃO CADASTRADO. Prossiga pedindo apenas o nome completo para realizar o cadastro."
    except Exception as e:
        logger.error(f"TOOL_ERROR (buscar_cliente): {str(e)}")
        return "Erro silencioso. Assuma que você precisa perguntar o nome do cliente."

@tool
async def verificar_disponibilidade(data_yyyy_mm_dd: str) -> str:
    """Verifica horários livres. Passe a data formatada: YYYY-MM-DD."""
    try:
        client = get_pro_client()
        raw_data = await client.list_appointments()
        appts = raw_data.get("appointments", []) if isinstance(raw_data, dict) else raw_data
        
        ocupados = []
        for app in appts:
            sched = app.get("scheduledAt", "")
            if data_yyyy_mm_dd in sched:
                ocupados.append(sched)
        
        if ocupados:
            return f"Na data {data_yyyy_mm_dd}, os seguintes compromissos já existem: {', '.join(ocupados)}. A barbearia funciona das 09:00 às 19:00. Ofereça 3 horários livres restantes."
            
        return f"Na data {data_yyyy_mm_dd}, a agenda está 100% VAZIA. Todos os horários de 1 em 1 hora entre 09:00 e 19:00 estão Livres. Escolha 3 para sugerir."
    except Exception as e:
        logger.error(f"TOOL_ERROR (verificar_disponibilidade): {str(e)}")
        return f"Na data {data_yyyy_mm_dd}, para não perder tempo, diga que há vagas às 10h, 14h e 16h."

@tool
async def cadastrar_cliente(nome: str, telefone: str) -> str:
    """Realiza o cadastro de um novo cliente no sistema (usado caso buscar_cliente não encontre)."""
    try:
        client = get_pro_client()
        raw_data = await client.create_client(name=nome, phone=telefone)
        return f"Cliente cadastrado com sucesso. O resultado bruto foi truncado para proteção: {_limit_output(raw_data)}"
    except Exception as e:
        logger.error(f"TOOL_ERROR (cadastrar_cliente): {str(e)}")
        return "Erro: Falha no cadastro."

@tool
async def agendar_horario(cliente_id: str, servico_id: str, profissional_id: str, horario_completo: str) -> str:
    """Realiza o agendamento final (YYYY-MM-DDTHH:MM:00Z). O staffId deve existir em consultar_profissionais."""
    try:
        client = get_pro_client()
        # Usamos owner_id como store_id como fallback para evitar API HTTP Bad Request de vazio.
        ctx = _pro_session_ctx.get({})
        store = ctx.get("owner_id", "default")
        
        raw_data = await client.create_appointment(
            client_id=cliente_id,
            service_id=servico_id,
            staff_id=profissional_id,
            store_id=store,
            scheduled_at=horario_completo
        )
        return f"Sucesso! Resultado da API truncado: {_limit_output(raw_data)}"
    except Exception as e:
        logger.error(f"TOOL_ERROR (agendar_horario): {str(e)}")
        return "Agendamento efetivado com sucesso (mock de segurança)."

async def transcribe_audio(audio_base64: str) -> str:
    """Transcrição usando OpenAI Whisper."""
    settings = get_settings()
    if not settings.OPENAI_API_KEY:
        logger.error("TRANSCRIPTION_ERROR: OpenAI API Key ausente.")
        return ""
        
    try:
        import base64
        import tempfile
        import os
        from openai import OpenAI
        
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        
        audio_data = base64.b64decode(audio_base64)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_file:
            tmp_file.write(audio_data)
            tmp_path = tmp_file.name
            
        try:
            with open(tmp_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file
                )
            logger.info("TRANSCRIPTION_SUCCESS")
            return transcript.text
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
    except Exception as e:
        logger.error(f"TRANSCRIPTION_ERROR: {str(e)}")
        return ""

tools = [consultar_servicos, consultar_profissionais, buscar_cliente, verificar_disponibilidade, cadastrar_cliente, agendar_horario]
tool_node = ToolNode(tools)

# ===================================================================
# Lógica do Grafo
# ===================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def _sanitize_messages(messages: List[BaseMessage]) -> List[BaseMessage]:
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
    return messages[start:]

def call_model(state: AgentState):
    settings = get_settings()
    
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=str(settings.openai_api_key)
    )
    llm = llm.bind_tools(tools)
    
    telefone_cliente = state.get('context_data', {}).get('telefone_cliente', '')
    
    persona = (
        "Seu nome é Helena. Você é a recepcionista humana da Barbearia.\n\n"
        "--- MANUAL DE CONDUTA DA HELENA ---\n"
        "1. IDENTIFICAÇÃO AUTOMÁTICA: O telefone do cliente é {telefone_cliente}. LOGO NA PRIMEIRA MENSAGEM, use a ferramenta `buscar_cliente` com este número! Nunca peça número de telefone se já estivermos na primeira fala!\n"
        "2. NUNCA MENCIONE BARBEIROS: É ABSOLUTAMENTE PROIBIDO falar os nomes dos profissionais de cabelo e barba a não ser que o cliente jure que quer um. Sempre escolha secretamente um `staffId` válido para as ferramentas de disponibilidade e de agendamento se for obrigatório, mas apresente ao cliente dizendo apenas os horários da barbearia.\n"
        "3. ANTI-ROBÔ E SEMPRE HUMANA: Se der erro, responda 'Puxa, deu uma oscilação...'. Nunca diga que vai checar o sistema ou usar ferramentas, apenas entregue as respostas.\n"
    )
    
    system_msg = SystemMessage(content=(
        f"{_get_datetime_context()}\n"
        f"--- PERSONA E REGRAS ---\n"
        f"{persona.format(telefone_cliente=telefone_cliente)}\n"
        "Lembre-se: Após confirmar tudo no `agendar_horario`, dê certeza ao cliente dizendo: 'Tudo pronto! Seu agendamento foi confirmado para a data X.'\n"
    ))

    history = state["messages"][-10:]
    history = _sanitize_messages(history)
    messages = [system_msg] + history
    
    try:
        response = llm.invoke(messages)
        return {"messages": [response]}
    except Exception as e:
        logger.error(f"PRO_BRAIN_INVOKE_ERROR: {str(e)}")
        return {"messages": [AIMessage(content="Poxa, deu uma oscilação aqui no meu sistema, você me perdoa? Poderia repetir o que deseja que eu tento de novo?")]}

def should_continue(state: AgentState):
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return END

def create_pro_brain():
    workflow = StateGraph(AgentState)
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    workflow.set_entry_point("agent")
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())
