"""
BarberOS - Full Engine (Autonomous Agent)
=========================================
Ana agora consegue buscar horários, criar agendamentos e cancelar.

Endpoints atualizados (Abril 2026):
  - POST /webhook/buscar_horarios
  - POST /webhook/criar_agendamento
  - POST /webhook/buscar_agendamento_contato
  - POST /webhook/desmarcar_agendamento

Todos os endpoints agora recebem:
  inbox_do_cliente, contact_id, conversation_id (contexto Chatwoot)
  IDs como strings ("ID_DA_AGENDA", "ID_DA_FILIAL")
"""
from typing import Annotated, TypedDict, List, Optional, Union
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.config.settings import get_settings
from src.config.logging_config import get_logger
from src.integrations.n8n_webhooks import N8NWebhookClient

logger = get_logger("agent.full_engine")

# Instanciamos o cliente uma vez
n8n = N8NWebhookClient()


# ===================================================================
# Contexto de sessão Chatwoot (injetado por request no /chat endpoint)
# Usado pelas tools para enviar inbox/contact/conversation ao N8N
# ===================================================================
_session_context: dict = {}


def set_session_context(inbox: Optional[str] = None,
                        contact_id: Optional[str] = None,
                        conversation_id: Optional[str] = None):
    """Chamado pelo endpoint /chat antes de invocar o brain."""
    global _session_context
    _session_context = {
        "inbox": inbox,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
    }


def _ctx():
    """Retorna o contexto Chatwoot da sessão atual."""
    return _session_context.copy()


# ===================================================================
# Definição das Ferramentas (Tools) — alinhadas com endpoints v2
# ===================================================================

@tool
async def buscar_disponibilidade(
    data_inicio: str,
    data_fim: str,
    id_agenda: str,
    id_filial: str,
    duracao_total_minutos: int,
    amostras: int = 5
):
    """
    Busca horários livres no sistema de agendamento.
    Use quando o cliente perguntar 'tem horário para amanhã?'
    ou 'quais horários você tem?'.

    Parâmetros:
    - data_inicio: Data/hora de início da busca (ISO 8601, ex: 2025-06-10T09:00:00)
    - data_fim: Data/hora de fim da busca (ISO 8601, ex: 2025-06-10T18:00:00)
    - id_agenda: ID da agenda do profissional (string)
    - id_filial: ID da filial (string)
    - duracao_total_minutos: Duração do serviço em minutos (ex: 30)
    - amostras: Quantidade de sugestões de horário (padrão: 5)
    """
    ctx = _ctx()
    return await n8n.buscar_horarios(
        start=data_inicio,
        end=data_fim,
        id_agenda=id_agenda,
        id_filial=id_filial,
        duration=duracao_total_minutos,
        inbox=ctx.get("inbox"),
        contact_id=ctx.get("contact_id"),
        conversation_id=ctx.get("conversation_id"),
        amostras=amostras,
    )


@tool
async def realizar_agendamento(
    data_inicio: str,
    duracao_minutos: int,
    servicos_ids: List[str],
    id_agenda: str,
    id_filial: str,
    id_cliente_cashbarber: str,
    titulo: str,
    cliente_fone: str = ""
):
    """
    Cria um agendamento real no sistema. Use APENAS quando o cliente
    confirmar o interesse e você já tiver todos os dados necessários.

    Parâmetros:
    - data_inicio: Data/hora de início do agendamento (ISO 8601)
    - duracao_minutos: Duração total em minutos
    - servicos_ids: Lista de IDs de serviços (strings)
    - id_agenda: ID da agenda do profissional
    - id_filial: ID da filial
    - id_cliente_cashbarber: ID do cliente no CashBarber
    - titulo: Título do agendamento (ex: "Corte de cabelo")
    - cliente_fone: Telefone do cliente (para registro)
    """
    ctx = _ctx()
    desc = f"Agendamento via Ana AI. Tel: {cliente_fone}"
    return await n8n.criar_agendamento(
        start=data_inicio,
        duration=duracao_minutos,
        title=titulo,
        desc=desc,
        id_agenda=id_agenda,
        services=servicos_ids,
        id_filial=id_filial,
        id_cliente=id_cliente_cashbarber,
        inbox=ctx.get("inbox"),
        contact_id=ctx.get("contact_id"),
        conversation_id=ctx.get("conversation_id"),
    )


@tool
async def consultar_meu_agendamento(
    data_inicio: str,
    data_fim: str,
    id_agenda: str,
    id_filial: str,
    id_cliente: str,
    duracao_minutos: int = 30
):
    """
    Consulta se o cliente já tem algo marcado em um período.
    Use para verificar agendamentos existentes antes de remarcar ou cancelar.

    Parâmetros:
    - data_inicio: Início do período de busca (ISO 8601)
    - data_fim: Fim do período de busca (ISO 8601)
    - id_agenda: ID da agenda
    - id_filial: ID da filial
    - id_cliente: ID do cliente no sistema
    - duracao_minutos: Tamanho da janela em minutos (padrão: 30)
    """
    ctx = _ctx()
    return await n8n.buscar_agendamento_contato(
        start=data_inicio,
        end=data_fim,
        id_agenda=id_agenda,
        id_filial=id_filial,
        id_cliente=id_cliente,
        inbox=ctx.get("inbox"),
        duration=duracao_minutos,
    )


@tool
async def cancelar_meu_agendamento(
    telefone: str,
    motivo: str,
    id_agenda: str,
    id_evento: str
):
    """
    Cancela (desmarca) um agendamento existente e envia alerta ao cliente.
    Sempre confirme com o cliente antes de executar esta ação.

    Parâmetros:
    - telefone: Telefone do cliente (ex: 5511999999999)
    - motivo: Mensagem de cancelamento (ex: "Agendamento cancelado a pedido do cliente")
    - id_agenda: ID da agenda
    - id_evento: ID do evento a ser cancelado
    """
    ctx = _ctx()
    return await n8n.desmarcar_agendamento(
        phone=telefone,
        message=motivo,
        id_agenda=id_agenda,
        id_evento=id_evento,
        inbox=ctx.get("inbox"),
        contact_id=ctx.get("contact_id"),
        conversation_id=ctx.get("conversation_id"),
    )


@tool
async def buscar_cadastro_cliente(telefone: str):
    """Busca se o cliente já existe na base de dados pelo telefone."""
    return await n8n.buscar_cliente(telefone)


@tool
async def criar_cadastro_cliente(telefone: str, nome: str, email: Optional[str] = None):
    """Cria um novo cadastro de cliente. Use quando buscar_cadastro_cliente retornar que não existe."""
    return await n8n.criar_cliente(telefone, nome, email)


@tool
async def remarcar_agendamento(
    id_evento_antigo: str,
    nova_data_inicio: str,
    duracao_minutos: int,
    servicos_ids: List[str],
    id_agenda: str,
    id_filial: str,
    id_cliente_cashbarber: str,
    cliente_fone: str,
    titulo: str
):
    """
    Remarca um agendamento existente. Cancela o antigo e cria um novo.
    Use quando o cliente quiser trocar dia ou horário.

    Parâmetros:
    - id_evento_antigo: ID do evento que será cancelado
    - nova_data_inicio: Nova data/hora (ISO 8601)
    - duracao_minutos: Duração do novo agendamento
    - servicos_ids: Lista de IDs dos serviços
    - id_agenda: ID da agenda do profissional
    - id_filial: ID da filial
    - id_cliente_cashbarber: ID do cliente no CashBarber
    - cliente_fone: Telefone do cliente
    - titulo: Título do agendamento
    """
    ctx = _ctx()

    # Passo 1: Cancelar o agendamento antigo
    cancel_res = await n8n.desmarcar_agendamento(
        phone=cliente_fone,
        message="Reagendamento solicitado pelo cliente",
        id_agenda=id_agenda,
        id_evento=id_evento_antigo,
        inbox=ctx.get("inbox"),
        contact_id=ctx.get("contact_id"),
        conversation_id=ctx.get("conversation_id"),
    )

    if cancel_res.get("success") or not cancel_res.get("error"):
        # Passo 2: Criar o novo agendamento
        desc = f"Reagendamento via Ana AI (Antigo: {id_evento_antigo}). Tel: {cliente_fone}"
        return await n8n.criar_agendamento(
            start=nova_data_inicio,
            duration=duracao_minutos,
            title=titulo,
            desc=desc,
            id_agenda=id_agenda,
            services=servicos_ids,
            id_filial=id_filial,
            id_cliente=id_cliente_cashbarber,
            inbox=ctx.get("inbox"),
            contact_id=ctx.get("contact_id"),
            conversation_id=ctx.get("conversation_id"),
        )

    return {"error": "Falha ao cancelar agendamento anterior para reagendar.", "details": cancel_res}


# ===================================================================
# Registro de ferramentas
# ===================================================================
tools = [
    buscar_disponibilidade,
    realizar_agendamento,
    consultar_meu_agendamento,
    cancelar_meu_agendamento,
    buscar_cadastro_cliente,
    criar_cadastro_cliente,
    remarcar_agendamento,
]
tool_node = ToolNode(tools)


# ===================================================================
# Estado do Agente
# ===================================================================
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict
    needs_human: bool
    intent: Optional[str]
    current_action: Optional[str]


# ===================================================================
# Lógica do Modelo
# ===================================================================
def call_model(state: AgentState, config: RunnableConfig):
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model,
        temperature=0,
        openai_api_key=str(settings.openai_api_key),
        max_retries=2
    ).bind_tools(tools)

    # --- Gestão de Memória: últimas 15 mensagens ---
    all_messages = state["messages"]
    if len(all_messages) > 15:
        messages_to_send = all_messages[-15:]
    else:
        messages_to_send = all_messages

    persona = state.get("context_data", {}).get("persona", "Você é a Ana, assistente virtual da barbearia.")
    system_info = state.get("context_data", {}).get("system_info", {})

    system_message = SystemMessage(content=(
        f"--- PERSONA ---\n{persona}\n\n"
        f"--- DADOS TÉCNICOS DA FILIAL ---\n{system_info}\n\n"
        "--- REGRAS DE OURO (MEMÓRIA E FLUXO) ---\n"
        "1. MEMÓRIA ABSOLUTA: Antes de fazer qualquer pergunta, leia TODO o histórico de mensagens acima. Se o usuário já disse a unidade, o serviço ou o horário, NUNCA pergunte novamente.\n"
        "Você é a Ana, recepcionista virtual da BarberOS. Sua prioridade é a fluidez.\n\n"
        "REGRAS CRÍTICAS DE SOBREVIVÊNCIA:\n"
        "1. Nunca chame a mesma ferramenta duas vezes com os mesmos parâmetros se ela retornou erro.\n"
        "2. Se o N8N retornar erro, diga: 'Estou com uma instabilidade técnica momentânea. Pode me dizer seu [DADO FALTANTE] enquanto eu verifico?'\n"
        "3. Não peça desculpas excessivas. Seja prática.\n"
        "4. Se o cliente quer agendar, siga: Cadastro -> Disponibilidade -> Agendamento.\n"
        "5. Máximo de 2 chamadas de ferramenta por resposta do usuário.\n"
        "6. IMPORTANTE: Todos os IDs (id_agenda, id_filial, id_cliente, id_servico) são STRINGS.\n"
    ))

    # Log para auditoria de decisão
    logger.debug("DECISAO_AGENTE: Chamando LLM", thread_id=config.get("configurable", {}).get("thread_id"))

    messages = [system_message] + messages_to_send

    # Timeout de 30s à chamada do LLM para evitar travamentos infinitos
    try:
        response = llm.invoke(messages, timeout=30)
    except Exception as e:
        logger.error(f"FALHA_OPENAI: {str(e)}")
        raise e

    # Tentamos extrair a intenção da resposta ou das ferramentas chamadas
    intent = state.get("intent", "conversational")
    content_lower = response.content.lower()

    if response.tool_calls:
        intent = response.tool_calls[0]["name"]
        logger.info(f"AGENTE_ACAO: {intent}")
    elif "horário" in content_lower or "agenda" in content_lower or "disponível" in content_lower:
        intent = "perguntando_horario"
    elif "serviço" in content_lower or "corte" in content_lower or "barba" in content_lower:
        intent = "perguntando_servico"
    elif "unidade" in content_lower or "filial" in content_lower or "unidades" in content_lower:
        intent = "perguntando_unidade"
    elif any(greeting in content_lower for greeting in ["olá", "oi", "bom dia", "boa tarde", "boa noite"]):
        intent = "greeting"

    return {
        "messages": [response],
        "intent": intent,
        "needs_human": "falar com humano" in content_lower or "atendente" in content_lower
    }


# ===================================================================
# Verificador de Fluxo
# ===================================================================
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END


# ===================================================================
# Construindo o Grafo
# ===================================================================
def create_full_brain():
    workflow = StateGraph(AgentState)

    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("agent")

    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent")  # Volta para o agente para ele falar o resultado

    return workflow.compile(checkpointer=MemorySaver())
