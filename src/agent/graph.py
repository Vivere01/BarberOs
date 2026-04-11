"""
BarberOS - Graph Definition
============================
Define a máquina de estados (LangGraph) do agente.
O motor orquestra a classificação, a geração da resposta e a validação.
"""
from typing import Literal
from langgraph.graph import StateGraph, END

from src.agent.state import AgentState
from src.agent.nodes.router import route_intent
from src.agent.nodes.query import query_info
from src.agent.nodes.validator import validate_response
# Nota: Vamos usar query_info para greetings simplificados por enquanto
# para manter o foco no motor lógico

def intent_router(state: AgentState) -> Literal["query", "handoff", "end"]:
    """
    Decide para qual nó o fluxo deve ir após a classificação.
    """
    intent = state.get("current_intent", "unknown")
    
    if intent in ["query_services", "query_prices", "query_hours", "greeting"]:
        return "query"
    if intent == "human_handoff":
        return "handoff"
    
    # Se ainda não implementamos agendamento no graf, roteamos para handoff ou query
    return "query"

async def handoff_node(state: AgentState) -> dict:
    return {
        "agent_response": "Entendi. Vou te passar para um dos nossos barbeiros resolver isso com você agora mesmo! Só um minuto... 🏁",
        "metadata": {"needs_human": True}
    }

def create_agent_graph():
    """Cria e compila o grafo de estados."""
    workflow = StateGraph(AgentState)

    # Adiciona nós
    workflow.add_node("router", route_intent)
    workflow.add_node("query", query_info)
    workflow.add_node("handoff", handoff_node)
    workflow.add_node("validator", validate_response)

    # Define as bordas (Edges)
    workflow.set_entry_point("router")
    
    workflow.add_conditional_edges(
        "router",
        intent_router,
        {
            "query": "query",
            "handoff": "handoff",
            "end": END
        }
    )

    # Todos os fluxos de resposta passam pelo validador antes de sair
    workflow.add_edge("query", "validator")
    workflow.add_edge("handoff", "validator")
    
    workflow.add_edge("validator", END)

    # Compila o grafo
    return workflow.compile()
