"""
BarberOS - LangGraph Agent Graph
===================================
O grafo principal que orquestra todo o fluxo da conversa.

ARQUITETURA:
                    ┌─────────────┐
                    │  user_input  │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   router    │ ← Classifica intenção (temp=0)
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┬───────────┐
              │            │            │           │
        ┌─────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌───▼──────┐
        │ greeting  │ │scheduling│ │ query  │ │ fallback │
        └─────┬────┘ └────┬─────┘ └───┬────┘ └───┬──────┘
              │            │            │           │
              └────────────┼────────────┘           │
                           │                        │
                    ┌──────▼──────┐                  │
                    │  validator  │ ← Anti-alucinação│
                    └──────┬──────┘                  │
                           │                        │
                    ┌──────▼──────┐                  │
                    │   output    │◄─────────────────┘
                    └─────────────┘
"""
from langgraph.graph import StateGraph, END

from src.agent.state import AgentState, IntentType
from src.agent.nodes.router import route_intent
from src.agent.nodes.greeting import handle_greeting
from src.agent.nodes.scheduling import handle_scheduling
from src.agent.nodes.query import handle_query
from src.agent.nodes.cancellation import handle_cancellation
from src.agent.nodes.validator import validate_response
from src.agent.nodes.fallback import handle_fallback
from src.config.logging_config import get_logger

logger = get_logger("agent.graph")


def _route_by_intent(state: AgentState) -> str:
    """
    Roteamento condicional baseado na intenção classificada.
    Retorna o nome do próximo nó a executar.

    NOTA: Esta é uma função DETERMINÍSTICA — não usa LLM.
    O routing é feito por uma lookup table, impossível alucinar.
    """
    intent = state.get("current_intent", IntentType.UNKNOWN.value)

    # Routing table — determinístico
    routing_table = {
        IntentType.GREETING.value: "greeting",
        IntentType.SCHEDULE_APPOINTMENT.value: "scheduling",
        IntentType.RESCHEDULE_APPOINTMENT.value: "scheduling",
        IntentType.CHECK_AVAILABILITY.value: "scheduling",
        IntentType.CANCEL_APPOINTMENT.value: "cancellation",
        IntentType.QUERY_SERVICES.value: "query",
        IntentType.QUERY_PRICES.value: "query",
        IntentType.QUERY_HOURS.value: "query",
        IntentType.QUERY_LOCATION.value: "query",
        IntentType.CHECK_APPOINTMENT.value: "query",
        IntentType.FAQ.value: "query",
        IntentType.COMPLAINT.value: "fallback",
        IntentType.HUMAN_HANDOFF.value: "fallback",
        IntentType.UNKNOWN.value: "fallback",
    }

    next_node = routing_table.get(intent, "fallback")

    logger.info(
        "Routing decision",
        intent=intent,
        next_node=next_node,
        conversation_id=state.get("conversation_id", ""),
    )

    return next_node


def _should_validate(state: AgentState) -> str:
    """
    Decide se a resposta precisa de validação.
    Respostas de template puro (greeting, fallback) não precisam.
    """
    intent = state.get("current_intent", "")

    # Templates puros não precisam validação
    skip_validation = {
        IntentType.GREETING.value,
        IntentType.HUMAN_HANDOFF.value,
        IntentType.COMPLAINT.value,
    }

    if intent in skip_validation:
        return "output"

    return "validator"


def create_agent_graph() -> StateGraph:
    """
    Cria o grafo principal do agente.

    O grafo garante que:
    1. Toda mensagem é classificada antes de processada
    2. Toda resposta com dados é validada contra dados reais
    3. Erros sempre resultam em handoff para humano
    4. O fluxo é determinístico (sem loops infinitos)
    """
    # Cria o grafo com o estado tipado
    graph = StateGraph(AgentState)

    # ─── Adiciona nós ───
    graph.add_node("router", route_intent)
    graph.add_node("greeting", handle_greeting)
    graph.add_node("scheduling", handle_scheduling)
    graph.add_node("query", handle_query)
    graph.add_node("cancellation", handle_cancellation)
    graph.add_node("validator", validate_response)
    graph.add_node("fallback", handle_fallback)

    # ─── Define ponto de entrada ───
    graph.set_entry_point("router")

    # ─── Roteamento condicional do router ───
    graph.add_conditional_edges(
        "router",
        _route_by_intent,
        {
            "greeting": "greeting",
            "scheduling": "scheduling",
            "query": "query",
            "cancellation": "cancellation",
            "fallback": "fallback",
        },
    )

    # ─── Após handler → decide se valida ───
    for handler in ["greeting", "scheduling", "query", "cancellation"]:
        graph.add_conditional_edges(
            handler,
            _should_validate,
            {
                "validator": "validator",
                "output": END,
            },
        )

    # ─── Validator → sempre finaliza ───
    graph.add_edge("validator", END)

    # ─── Fallback → sempre finaliza ───
    graph.add_edge("fallback", END)

    logger.info("Agent graph created successfully")

    return graph.compile()
