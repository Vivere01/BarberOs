"""
BarberOS - ChatBarber PRO Engine
================================
Engine dedicada para o sistema ChatBarber PRO.
"""
from typing import Annotated, TypedDict, List, Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

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

@tool
async def consultar_servicos():
    """Lista todos os serviços, preços e durações disponíveis na barbearia."""
    try:
        client = get_pro_client()
        services = await client.list_services()
        return {"status": "sucesso", "servicos": services}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}

@tool
async def consultar_profissionais():
    """Lista os barbeiros/profissionais da equipe."""
    try:
        client = get_pro_client()
        staff = await client.list_staff()
        return {"status": "sucesso", "equipe": staff}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}

@tool
async def verificar_disponibilidade(data_desejada: str):
    """
    Busca horários disponíveis para agendamento.
    Parâmetro: data_desejada (ISO 8601, ex: 2024-04-16)
    """
    try:
        client = get_pro_client()
        appointments = await client.list_appointments()
        return {"status": "sucesso", "agendamentos_existentes": appointments, "aviso": "O agente deve sugerir horários livres com base na agenda do dia."}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}

@tool
async def cadastrar_cliente(nome: str, telefone: str, email: Optional[str] = None):
    """Cria um novo cadastro de cliente no sistema."""
    try:
        client = get_pro_client()
        res = await client.create_client(name=nome, phone=telefone, email=email)
        return {"status": "sucesso", "cliente": res}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}

@tool
async def agendar_horario(client_id: str, service_id: str, staff_id: str, store_id: str, data_hora: str, notas: str = "Agendamento via IA"):
    """
    Realiza o agendamento final no sistema.
    Parâmetros: client_id, service_id, staff_id, store_id, data_hora (ISO 8601)
    """
    try:
        client = get_pro_client()
        res = await client.create_appointment(
            client_id=client_id,
            service_id=service_id,
            staff_id=staff_id,
            store_id=store_id,
            scheduled_at=data_hora,
            notes=notas
        )
        return {"status": "sucesso", "agendamento": res}
    except Exception as e:
        return {"status": "erro", "mensagem": str(e)}

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
        
        # Converte base64 para arquivo temporário
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
            logger.info("TRANSCRIPTION_SUCCESS: Transcrição via OpenAI Whisper concluída.")
            return transcript.text
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
                
    except Exception as e:
        logger.error(f"TRANSCRIPTION_ERROR: Falha ao transcrever com OpenAI: {str(e)}")
        return ""

tools = [consultar_servicos, consultar_profissionais, verificar_disponibilidade, cadastrar_cliente, agendar_horario]
tool_node = ToolNode(tools)

# ===================================================================
# Lógica do Grafo
# ===================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict

def call_model(state: AgentState):
    settings = get_settings()
    
    # Agora forçamos OpenAI para estabilidade máxima
    if settings.OPENAI_API_KEY:
        from langchain_openai import ChatOpenAI
        llm = ChatOpenAI(
            model="gpt-4o-mini",
            temperature=0,
            openai_api_key=settings.OPENAI_API_KEY
        )
        logger.info("PRO_BRAIN: Usando motor premium OpenAI (GPT-4o-mini)")
    else:
        # Fallback apenas se OpenAI não existir nada
        from langchain_groq import ChatGroq
        llm = ChatGroq(
            model="llama-3.3-70b-versatile",
            temperature=0,
            groq_api_key=settings.GROQ_API_KEY
        )
        logger.warning("PRO_BRAIN: Alerta: Usando Groq como fallback (Cuidado com limites)")
    
    llm = llm.bind_tools(tools)
    
    # Carrega persona do arquivo para facilitar manutenção
    persona = (
        "Você é o AgenteIA da BarberOS, um recepcionista de barbearia de elite, humano e eficiente.\n"
        "Seu tom é amigável, educado e profissional, equilibrando empatia com agilidade.\n\n"
        "--- REGRAS DE OURO ---\n"
        "1. NÃO SEJA REPETITIVO: Antes de perguntar algo, veja se o cliente já respondeu no histórico.\n"
        "2. FOCO NA INTENÇÃO: Se o cliente quer apenas saber o preço, informe o preço e convide-o suavemente para agendar. Se ele estiver com pressa ou bravo, seja ultra-eficiente e resolva logo.\n"
        "3. EMPATIA NATURAL: Use expressões curtas de entendimento como 'Perfeito', 'Entendi perfeitamente', 'Claro, com certeza'.\n"
        "4. FLUXO LOGÍCO: Só peça informações que realmente faltam. Se já sabe o serviço, pergunte apenas a unidade e o horário.\n"
        "5. TRATAMENTO: Trate o cliente bem, mas sem bajulação excessiva. Seja o parceiro que resolve o agendamento dele.\n"
        "6. ERROS: Se não entender algo, peça desculpas de forma humana (ex: 'Puts, não consegui entender essa parte, pode repetir por favor?') em vez de frases robóticas.\n"
    )

    system_msg = SystemMessage(content=(
        f"{_get_datetime_context()}\n"
        f"--- PERSONA E REGRAS ---\n{persona}\n\n"
        "--- INSTRUÇÕES ADICIONAIS ---\n"
        "- Identifique a intenção do cliente no histórico antes de agir.\n"
        "- Use as ferramentas para consultar dados reais (preços, vagas, profissionais).\n"
        "- Responda sempre de forma concisa e natural no WhatsApp.\n"
    ))

    # Trima o histórico para as últimas 10 mensagens para evitar context_length_exceeded
    history = state["messages"][-10:]
    messages = [system_msg] + history
    
    logger.info(f"GROQ_CALL: Thread={state.get('context_data', {}).get('telefone_cliente')}, MsgCount={len(messages)}")
    
    try:
        response = llm.invoke(messages)
        return {"messages": [response]}
    except Exception as e:
        logger.error(f"GROQ_INVOKE_ERROR: {str(e)}")
        # Retorna uma mensagem de erro amigável se o Groq falhar
        return {"messages": [AIMessage(content="Desculpe, tive um problema técnico momentâneo. Pode repetir?")]}

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
