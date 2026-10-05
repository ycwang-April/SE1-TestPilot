from langgraph.graph import END, START, StateGraph

from testpilot.agent.nodes import AgentNodes
from testpilot.agent.state import Action, AgentState


def build_graph(nodes: AgentNodes):
    """Controller selects a tool/LLM node after EVERY new observation."""
    graph = StateGraph(AgentState)
    graph.add_node("controller", nodes.controller)
    graph.add_edge(START, "controller")
    for action in Action:
        graph.add_node(action.value, nodes.perform(action))
        graph.add_edge(
            action.value, END if action in (Action.FINISH, Action.FAIL) else "controller"
        )
    graph.add_conditional_edges(
        "controller",
        lambda state: state.current_action.value,
        {action.value: action.value for action in Action},
    )
    return graph.compile()
