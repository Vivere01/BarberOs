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

Correções v2.1 (Abril 2026):
  - contextvars para session context: thread-safe em produção concorrente
  - Prevenção de double tool call: agente instruído a chamar tool 1 vez por turno
"""
from typing import Annotated, TypedDict, List, Optional
from contextvars import ContextVar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from src.config.settings import get_settings
from src.config.logging_config import get_logger
from src.integrations.n8n_webhooks import N8NWebhookClient

logger = get_logger("agent.full_engine")

# Instanciamos o cliente uma vez
n8n = N8NWebhookClient()


# ===================================================================
# Contexto de sessão Chatwoot — async-safe via ContextVar
# Cada coroutine (request) tem seu próprio valor isolado.
# ===================================================================
_session_ctx: ContextVar[dict] = ContextVar("chatwoot_session", default={})


def set_session_context(inbox: Optional[str] = None,
                        contact_id: Optional[str] = None,
                        conversation_id: Optional[str] = None):
    """Chamado pelo endpoint /chat antes de invocar o brain.
    Usa ContextVar — safe para múltiplos usuários concorrentes."""
    _session_ctx.set({
        "inbox": inbox,
        "contact_id": contact_id,
        "conversation_id": conversation_id,
    })


def _ctx() -> dict:
    """Retorna o contexto Chatwoot do request atual (isolado por coroutine)."""
    return _session_ctx.get({}).copy()


# ===================================================================
# Calendário Real — Brasília (UTC-3)
# LLMs não sabem a data de hoje. Injetamos explicitamente para que
# expressões como "essa sexta", "amanhã", "hoje" sejam calculadas certo.
# ===================================================================
_DIAS_PT = ["segunda-feira", "terça-feira", "quarta-feira",
            "quinta-feira", "sexta-feira", "sábado", "domingo"]
_MESES_PT = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
             "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


def _get_datetime_context() -> str:
    """Retorna bloco de data/hora atual (Brasília) para injetar no system prompt.
    Pré-calcula os próximos 7 dias para que o LLM resolva datas relativas sem erro."""
    tz = ZoneInfo("America/Sao_Paulo")
    now = datetime.now(tz)
    dia_semana = _DIAS_PT[now.weekday()]
    mes = _MESES_PT[now.month - 1]

    # Próximos 7 dias com dia da semana
    proximos = []
    for i in range(1, 8):
        d = now + timedelta(days=i)
        proximos.append(
            f"  {_DIAS_PT[d.weekday()]}: {d.strftime('%d/%m/%Y')}"
        )
    proximos_str = "\n".join(proximos)

    return (
        f"--- DATA E HORA ATUAL (Brasília / UTC-3) ---\n"
        f"Hoje é {dia_semana}, {now.day} de {mes} de {now.year}.\n"
        f"Hora atual: {now.strftime('%H:%M')} (BRT).\n"
        f"Data ISO: {now.strftime('%Y-%m-%d')}\n\n"
        f"PRÓXIMOS 7 DIAS (use para resolver 'amanhã', 'essa sexta', etc.):\n"
        f"{proximos_str}\n\n"
        f"REGRA OBRIGATÓRIA DE DATAS:\n"
        f"- SEMPRE use as datas acima como referência. NUNCA invente ou adivinhe datas.\n"
        f"- Ao chamar qualquer ferramenta de agendamento, converta SEMPRE para ISO 8601: "
        f"YYYY-MM-DDTHH:MM:SS (ex: {now.strftime('%Y-%m-%d')}T09:00:00).\n"
        f"- Se o cliente disser 'essa sexta', calcule a partir de hoje ({now.strftime('%d/%m/%Y')}).\n"
    )


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
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno.

    Parâmetros:
    - data_inicio: Data/hora de início da busca (ISO 8601, ex: 2025-06-10T09:00:00)
    - data_fim: Data/hora de fim da busca (ISO 8601, ex: 2025-06-10T18:00:00)
    - id_agenda: ID da agenda do profissional (string)
    - id_filial: ID da filial (string)
    - duracao_total_minutos: Duração do serviço em minutos (ex: 30)
    - amostras: Quantidade de sugestões de horário (padrão: 5)
    """
    ctx = _ctx()
    logger.info(f"TOOL_BUSCAR_HORARIOS: agenda={id_agenda}, filial={id_filial}, inicio={data_inicio}")
    result = await n8n.buscar_horarios(
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
    if result.get("error"):
        logger.error(f"ERRO_BUSCAR_HORARIOS: {result}")
        return {"status": "erro", "mensagem": "N8N retornou erro", "detalhes": result.get("error")}
    return result


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
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno.

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
    logger.info(f"TOOL_CRIAR_AGENDAMENTO: agenda={id_agenda}, inicio={data_inicio}, cliente={id_cliente_cashbarber}")
    result = await n8n.criar_agendamento(
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
    if result.get("error"):
        logger.error(f"ERRO_CRIAR_AGENDAMENTO: {result}")
        return {"status": "erro", "mensagem": "Falha ao criar agendamento", "detalhes": result.get("error")}
    return result


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
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno.

    Parâmetros:
    - data_inicio: Início do período de busca (ISO 8601)
    - data_fim: Fim do período de busca (ISO 8601)
    - id_agenda: ID da agenda
    - id_filial: ID da filial
    - id_cliente: ID do cliente no sistema
    - duracao_minutos: Tamanho da janela em minutos (padrão: 30)
    """
    ctx = _ctx()
    logger.info(f"TOOL_CONSULTAR_AGENDAMENTO: agenda={id_agenda}, cliente={id_cliente}")
    result = await n8n.buscar_agendamento_contato(
        start=data_inicio,
        end=data_fim,
        id_agenda=id_agenda,
        id_filial=id_filial,
        id_cliente=id_cliente,
        inbox=ctx.get("inbox"),
        duration=duracao_minutos,
    )
    if result.get("error"):
        logger.error(f"ERRO_CONSULTAR_AGENDAMENTO: {result}")
        return {"status": "erro", "mensagem": "Falha ao consultar agendamentos", "detalhes": result.get("error")}
    return result


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
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno.

    Parâmetros:
    - telefone: Telefone do cliente (ex: 5511999999999)
    - motivo: Mensagem de cancelamento
    - id_agenda: ID da agenda
    - id_evento: ID do evento a ser cancelado
    """
    ctx = _ctx()
    logger.info(f"TOOL_CANCELAR_AGENDAMENTO: agenda={id_agenda}, evento={id_evento}")
    result = await n8n.desmarcar_agendamento(
        phone=telefone,
        message=motivo,
        id_agenda=id_agenda,
        id_evento=id_evento,
        inbox=ctx.get("inbox"),
        contact_id=ctx.get("contact_id"),
        conversation_id=ctx.get("conversation_id"),
    )
    if result.get("error"):
        logger.error(f"ERRO_CANCELAR_AGENDAMENTO: {result}")
        return {"status": "erro", "mensagem": "Falha ao cancelar agendamento", "detalhes": result.get("error")}
    return result


@tool
async def buscar_cadastro_cliente(telefone: str):
    """Busca se o cliente já existe na base de dados pelo telefone.
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno."""
    logger.info(f"TOOL_BUSCAR_CLIENTE: telefone={telefone}")
    return await n8n.buscar_cliente(telefone)


@tool
async def criar_cadastro_cliente(telefone: str, nome: str, email: Optional[str] = None):
    """Cria um novo cadastro de cliente. Use quando buscar_cadastro_cliente retornar que não existe.
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno."""
    logger.info(f"TOOL_CRIAR_CLIENTE: telefone={telefone}, nome={nome}")
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
    IMPORTANTE: Chame esta ferramenta APENAS UMA VEZ por turno.
    """
    ctx = _ctx()
    logger.info(f"TOOL_REMARCAR_AGENDAMENTO: evento_antigo={id_evento_antigo}, nova_data={nova_data_inicio}")

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

    if cancel_res.get("error"):
        return {"status": "erro", "mensagem": "Falha ao cancelar agendamento anterior", "detalhes": cancel_res}

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
        max_retries=1  # Reduzido: evita loops de retry
    ).bind_tools(tools)

    # --- Gestão de Memória: últimas 15 mensagens ---
    all_messages = state["messages"]
    messages_to_send = all_messages[-15:] if len(all_messages) > 15 else all_messages

    persona = state.get("context_data", {}).get("persona", "Você é a Ana, assistente virtual da barbearia.")
    system_info = state.get("context_data", {}).get("system_info", {})

    datetime_ctx = _get_datetime_context()

    system_message = SystemMessage(content=(
        f"{datetime_ctx}\n"
        f"--- PERSONA ---\n{persona}\n\n"
        f"--- DADOS TÉCNICOS DA FILIAL ---\n{system_info}\n\n"
        "--- REGRAS DE OURO (MEMÓRIA E FLUXO) ---\n"
        "1. MEMÓRIA ABSOLUTA: Antes de fazer qualquer pergunta, leia TODO o histórico. "
        "Se o usuário já disse a unidade, o serviço ou o horário, NUNCA pergunte novamente.\n\n"
        "REGRAS CRÍTICAS — SIGA À RISCA:\n"
        "1. USE NO MÁXIMO 1 (UMA) ferramenta por resposta. NUNCA chame 2 ferramentas ao mesmo tempo.\n"
        "2. NUNCA chame a mesma ferramenta duas vezes com os mesmos parâmetros.\n"
        "3. Se uma ferramenta retornar {\"status\": \"erro\"}, informe ao cliente: "
        "'Estou com uma instabilidade técnica momentânea. Pode me dizer seu [DADO FALTANTE] enquanto eu verifico?'\n"
        "4. Se o cliente quer agendar, siga ESTRITAMENTE: "
        "Cadastro → Disponibilidade → Confirmação → Agendamento.\n"
        "5. Não peça desculpas excessivas. Seja prática e direta.\n"
        "6. Todos os IDs (id_agenda, id_filial, id_cliente, id_servico) são STRINGS.\n"
    ))

    logger.debug("DECISAO_AGENTE: Chamando LLM", thread_id=config.get("configurable", {}).get("thread_id"))

    messages = [system_message] + messages_to_send

    try:
        response = llm.invoke(messages, timeout=30)
    except Exception as e:
        logger.error(f"FALHA_OPENAI: {str(e)}")
        raise e

    # Detecta intenção
    intent = state.get("intent", "conversational")
    content_lower = response.content.lower() if response.content else ""

    if response.tool_calls:
        # Garante que apenas 1 tool call seja executada por turno
        if len(response.tool_calls) > 1:
            logger.warning(f"LLM_DOUBLE_TOOL_CALL: {[tc['name'] for tc in response.tool_calls]} — truncando para 1")
            # Mantém apenas o primeiro tool call
            response.tool_calls = response.tool_calls[:1]
            response.additional_kwargs["tool_calls"] = response.additional_kwargs.get("tool_calls", [])[:1]
        intent = response.tool_calls[0]["name"]
        logger.info(f"AGENTE_ACAO: {intent}")
    elif "horário" in content_lower or "agenda" in content_lower or "disponível" in content_lower:
        intent = "perguntando_horario"
    elif "serviço" in content_lower or "corte" in content_lower or "barba" in content_lower:
        intent = "perguntando_servico"
    elif "unidade" in content_lower or "filial" in content_lower:
        intent = "perguntando_unidade"
    elif any(g in content_lower for g in ["olá", "oi", "bom dia", "boa tarde", "boa noite"]):
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
    last_message = state["messages"][-1]
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
    workflow.add_edge("tools", "agent")
    return workflow.compile(checkpointer=MemorySaver())
