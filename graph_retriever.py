import networkx as nx
from typing import List, Dict, Any


class FixitGraphRetriever:
    def __init__(self, kg: nx.DiGraph):
        self.kg = kg

    def retrieve_guide_subgraph_context(self, guide_title_or_id: str) -> str:
        """Retrieves structured context about a repair guide from the Knowledge Graph."""
        target_node = None
        for n, data in self.kg.nodes(data=True):
            if data.get("type") == "Guide":
                if guide_title_or_id.lower() in data.get("title", "").lower() or guide_title_or_id == data.get("guid_id", ""):
                    target_node = n
                    break

        if not target_node:
            return "No matching repair guide found in the Knowledge Graph."

        g_data = self.kg.nodes[target_node]
        context = [
            f"Repair Guide: {g_data.get('title')}",
            f"Device/Category: {g_data.get('category')}",
            f"Subject: {g_data.get('subject')}"
        ]

        # Extract required tools
        tools = [
            self.kg.nodes[nbr].get("name")
            for _, nbr, edge_data in self.kg.out_edges(target_node, data=True)
            if edge_data.get("relation") == "REQUIRES_TOOL"
        ]
        if tools:
            context.append(f"Required Tools: {', '.join(tools)}")

        # Extract step sequences
        step_edges = [
            (nbr, edge_data.get("order", 0))
            for _, nbr, edge_data in self.kg.out_edges(target_node, data=True)
            if edge_data.get("relation") == "HAS_STEP"
        ]
        step_edges.sort(key=lambda x: x[1])

        context.append("Procedure Steps:")
        for step_node, order in step_edges:
            step_text = self.kg.nodes[step_node].get("text", "")
            # Find tools and parts for this step
            step_tools = [
                self.kg.nodes[target].get("name")
                for _, target, edata in self.kg.out_edges(step_node, data=True)
                if edata.get("relation") == "USES_TOOL"
            ]
            tools_str = f" [Tools: {', '.join(step_tools)}]" if step_tools else ""
            context.append(f"  Step {order + 1}: {step_text}{tools_str}")

        return "\n".join(context)