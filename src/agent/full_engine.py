"""
BarberOS - Full Engine (Autonomous Agent)
=========================================
Ana agora consegue buscar horários, criar agendamentos e cancelar.
"""
from typing import Annotated, TypedDict, List, Optional, Union
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import ToolNode

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field
from src.config.settings import get_settings
from src.integrations.n8n_webhooks import N8NWebhookClient

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
    messages: Annotated[List[BaseMessage], "Historico"]
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
        "--- PROTOCOLO DE ATENDIMENTO ---\n"
        "1. IDENTIFICAÇÃO: Se é o início da conversa, use 'buscar_cadastro_cliente' para ver se já conhecemos o cliente.\n"
        "2. COLETA: Se o cliente quer agendar, identifique: Serviço, Profissional (opcional) e Data/Hora.\n"
        "3. DISPONIBILIDADE: Assim que tiver a data e serviço, use 'buscar_disponibilidade' imediatamente. Não pergunte 'posso buscar?'.\n"
        "4. CONCLUSÃO: Após mostrar horários e o cliente escolher, use 'realizar_agendamento'.\n"
        "5. REAGENDAMENTO: Se o cliente quer mudar um horário, use 'remarcar_agendamento'.\n\n"
        "--- REGRAS ANTI-LOOP ---\n"
        "- Se você já perguntou algo e a resposta está no histórico, NÃO pergunte de novo.\n"
        "- Se o cliente confirmou ou deu um dado, use-o para chamar a ferramenta correspondente imediatamente.\n"
        "- Seja amigável mas extremamente eficiente. Evite frases como 'Entendo, você gostaria de...', vá direto ao ponto: 'Perfeito, vou verificar os horários para [serviço]...'.\n"
        "- Se o sistema (ferramenta) retornar que não há horários, sugira o próximo dia disponível ou peça para o cliente sugerir um.\n\n"
        "NUNCA invente informações. Se não souber os IDs de serviços/filial, use os que estão nos DADOS TÉCNICOS."
    ))
    
    messages = [system_message] + state["messages"]
    response = llm.invoke(messages)
    
    # Tentamos extrair a intenção da resposta ou das ferramentas chamadas
    intent = state.get("intent", "conversational")
    if response.tool_calls:
        intent = response.tool_calls[0]["name"]
    
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
