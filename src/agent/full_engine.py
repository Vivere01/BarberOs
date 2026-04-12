"""
BarberOS - Full Engine (Autonomous Agent)
=========================================
Ana agora consegue buscar horários, criar agendamentos e cancelar.
"""
from typing import Annotated, TypedDict, List, Optional, Union
from langgraph.graph import StateGraph, END
from operator import add
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.config.settings import get_settings
from src.config.logging_config import get_logger
from src.integrations.n8n_webhooks import N8NWebhookClient

logger = get_logger("agent.full_engine")

# Instanciamos o cliente uma vez
n8n = N8NWebhookClient()

# --- Definição das Ferramentas (Tools) ---

@tool
async def buscar_disponibilidade(data_inicio: str, data_fim: str, id_agenda: int, id_filial: int, duracao_total_minutos: int):
    """
    Busca horários livres no sistema. Use quando o cliente perguntar 'tem horário para amanhã?' 
    ou 'quais horários você tem?'.
    As datas devem estar no formato ISO 8601 (Ex: 2025-06-10T09:00:00-03:00).
    """
    return await n8n.buscar_horarios(data_inicio, data_fim, id_agenda, id_filial, duracao_total_minutos)

@tool
async def realizar_agendamento(data_inicio: str, duracao_minutos: int, servicos_ids: List[int], id_agenda: int, id_filial: int, cliente_fone: str, titulo: str):
    """
    Cria um agendamento real no sistema. Use APENAS quando o cliente confirmar o interesse.
    """
    desc = f"Agendamento via Ana AI. Tel: {cliente_fone}"
    return await n8n.criar_agendamento(data_inicio, duracao_minutos, titulo, desc, id_agenda, servicos_ids, id_filial)

@tool
async def consultar_meu_agendamento(data_inicio: str, data_fim: str, id_agenda: int, id_filial: int, duracao_minutos: int):
    """Consulta se o cliente já tem algo marcado em um período."""
    return await n8n.buscar_agendamento_contato(data_inicio, data_fim, id_agenda, duracao_minutos, id_filial)

@tool
async def cancelar_meu_agendamento(telefone: str, motivo: str, id_agenda: int, id_evento: str):
    """Cancela um agendamento existente."""
    return await n8n.cancelar_agendamento(telefone, motivo, id_agenda, id_evento)

@tool
async def buscar_cadastro_cliente(telefone: str):
    """Busca se o cliente já existe na base de dados pelo telefone."""
    return await n8n.buscar_cliente(telefone)

@tool
async def criar_cadastro_cliente(telefone: str, nome: str, email: Optional[str] = None):
    """Cria um novo cadastro de cliente. Use quando buscar_cadastro_cliente retornar que não existe."""
    return await n8n.criar_cliente(telefone, nome, email)

@tool
async def remarcar_agendamento(id_evento_antigo: str, nova_data_inicio: str, duracao_minutos: int, servicos_ids: List[int], id_agenda: int, id_filial: int, cliente_fone: str, titulo: str):
    """
    Remarca um agendamento. Internamente, você deve cancelar o antigo primeiro se ainda não o fez, 
    ou simplesmente usar esta ferramenta que sinaliza o desejo de troca.
    """
    # Na prática, o N8N pode lidar com o 'reagendamento' como um cancel + create
    cancel_res = await n8n.cancelar_agendamento(cliente_fone, "Reagendamento solicitado pelo cliente", id_agenda, id_evento_antigo)
    if cancel_res.get("success") or not cancel_res.get("error"):
        desc = f"Reagendamento via Ana AI (Antigo: {id_evento_antigo}). Tel: {cliente_fone}"
        return await n8n.criar_agendamento(nova_data_inicio, duracao_minutos, titulo, desc, id_agenda, servicos_ids, id_filial)
    return {"error": "Falha ao cancelar agendamento anterior para reagendar.", "details": cancel_res}

tools = [
    buscar_disponibilidade, 
    realizar_agendamento, 
    consultar_meu_agendamento, 
    cancelar_meu_agendamento,
    buscar_cadastro_cliente,
    criar_cadastro_cliente,
    remarcar_agendamento
]
tool_node = ToolNode(tools)

# --- Estado do Agente ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], add]
    context_data: dict
    needs_human: bool
    intent: Optional[str]
    current_action: Optional[str]

# --- Lógica do Modelo ---
def call_model(state: AgentState):
    settings = get_settings()
    llm = ChatOpenAI(
        model=settings.openai_model, 
        temperature=0, # Temperatura 0 para ferramentas ser mais preciso
        openai_api_key=str(settings.openai_api_key)
    ).bind_tools(tools)
    
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
    ))
    
    # Log para auditoria de decisão
    logger.debug(f"DECISAO_AGENTE: Chamando LLM para thread {state.get('thread_id')}")
    
    messages = [system_message] + state["messages"]
    response = llm.invoke(messages)
    
    # Tentamos extrair a intenção da resposta ou das ferramentas chamadas
    intent = state.get("intent", "conversational")
    content_lower = response.content.lower()
    
    if response.tool_calls:
        intent = response.tool_calls[0]["name"]
        logger.info(f"AGENTE_ACAO: {intent}")
    # Invertemos a ordem: se ela perguntou horário ou serviço, isso tem prioridade sobre "unidade"
    elif "horário" in content_lower or "agenda" in content_lower or "disponível" in content_lower:
        intent = "perguntando_horario"
    elif "serviço" in content_lower or "corte" in content_lower or "barba" in content_lower:
        intent = "perguntando_servico"
    elif "unidade" in content_lower or "filial" in content_lower or "unidades" in content_lower:
        intent = "perguntando_unidade"
    
    return {
        "messages": [response],
        "intent": intent,
        "needs_human": "falar com humano" in response.content.lower() or "atendente" in response.content.lower()
    }

# --- Verificador de Fluxo ---
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools"
    return END

# --- Construindo o Grafo ---
def create_full_brain():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    workflow.set_entry_point("agent")
    
    workflow.add_conditional_edges("agent", should_continue)
    workflow.add_edge("tools", "agent") # Volta para o agente para ele falar o resultado
    
    return workflow.compile(checkpointer=MemorySaver())
