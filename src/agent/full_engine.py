"""
BarberOS - Full Engine com Execução de Ferramentas
===================================================
O Grafo agora executa ferramentas e volta para o modelo para validar.
"""
from typing import Annotated, TypedDict, List
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode # Nó que executa as ferramentas
from langgraph.checkpoint.memory import MemorySaver

from langchain_openai import ChatOpenAI
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.tools import tool

# --- Importamos seus Scrapers reais ---
from src.integrations.cashbarber.client import CashBarberScraper

@tool
async def search_slots(date: str):
    """Buscador de horários reais no sistema. Use para agendamentos."""
    scraper = CashBarberScraper()
    # No seu caso, o login é feito aqui com os dados do cliente
    return await scraper.get_available_slots(date)

tools = [search_slots]
tool_node = ToolNode(tools)

# --- Estado ---
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Historico"]
    needs_human: bool

# --- Lógica do Modelo ---
def call_model(state: AgentState):
    llm = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    llm_with_tools = llm.bind_tools(tools)
    response = llm_with_tools.invoke(state["messages"])
    return {"messages": [response]}

# --- Decisor: Continuar ou Parar ---
def should_continue(state: AgentState):
    messages = state["messages"]
    last_message = messages[-1]
    if last_message.tool_calls:
        return "tools" # Se o modelo pediu ferramenta, vai para o nó de tools
    return END # Se não, termina e responde ao N8N

# --- Construindo o Grafo ---
def create_full_brain():
    workflow = StateGraph(AgentState)
    
    workflow.add_node("agent", call_model)
    workflow.add_node("tools", tool_node)
    
    workflow.set_entry_point("agent")
    
    # Condição: Se precisar de ferramenta, vai para /tools, se não, END.
    workflow.add_conditional_edges(
        "agent",
        should_continue,
    )
    
    # Após usar a ferramenta, ele OBRIGATORIAMENTE volta para o agente
    # Isso permite que ele analise os dados do scraping e valide antes de responder.
    workflow.add_edge("tools", "agent")
    
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)
