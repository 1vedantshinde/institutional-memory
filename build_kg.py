import os
import json
import glob
import networkx as nx
from typing import List, Dict, Any


def extract_and_build_kg(json_folder_path: str) -> nx.DiGraph:
    """
    Parses all MyFixit JSON files in a directory and creates a Directed Knowledge Graph.
    """
    kg = nx.DiGraph()

    json_files = glob.glob(os.path.join(json_folder_path, "*.json"))
    if not json_files:
        raise FileNotFoundError(f"No JSON files found in {json_folder_path}")

    print(f"Loading {len(json_files)} guide files...")

    for file_path in json_files:
        with open(file_path, "r", encoding="utf-8") as f:
            try:
                # Handle single object or JSON lines (multiple guides per file)
                content = f.read().strip()
                if content.startswith("["):
                    guides = json.loads(content)
                elif "\n" in content and "{" in content:
                    guides = [json.loads(line) for line in content.splitlines() if line.strip()]
                else:
                    guides = [json.loads(content)]
            except Exception as e:
                print(f"Skipping {file_path} due to parse error: {e}")
                continue

        for guide in guides:
            guide_id = str(guide.get("Guidid", guide.get("Title", "")))
            guide_title = guide.get("Title", "Unknown Title")
            category = guide.get("Category", "Unknown Device")
            subject = guide.get("Subject", "")
            url = guide.get("Url", "")

            # 1. Guide Node
            guide_node = f"guide:{guide_id}"
            kg.add_node(
                guide_node,
                type="Guide",
                guid_id=guide_id,
                title=guide_title,
                category=category,
                subject=subject,
                url=url
            )

            # 2. Category / Device Hierarchy
            cat_node = f"category:{category}"
            kg.add_node(cat_node, type="Category", name=category)
            kg.add_edge(guide_node, cat_node, relation="BELONGS_TO_CATEGORY")

            ancestors = guide.get("Ancestors", [])
            for i in range(len(ancestors) - 1):
                parent_cat = f"category:{ancestors[i+1]}"
                child_cat = f"category:{ancestors[i]}"
                kg.add_node(parent_cat, type="Category", name=ancestors[i+1])
                kg.add_node(child_cat, type="Category", name=ancestors[i])
                kg.add_edge(child_cat, parent_cat, relation="SUB_CATEGORY_OF")

            # 3. Toolbox / Required Tools
            toolbox = guide.get("Toolbox", [])
            for tool in toolbox:
                tool_name = tool.get("Name", "").strip().lower()
                if tool_name:
                    tool_node = f"tool:{tool_name}"
                    kg.add_node(tool_node, type="Tool", name=tool_name, url=tool.get("Url", ""))
                    kg.add_edge(guide_node, tool_node, relation="REQUIRES_TOOL")

            # 4. Steps, Parts, and Actions
            steps = guide.get("Steps", [])
            prev_step_node = None

            for step in steps:
                step_id = str(step.get("StepId", f"{guide_id}_step_{step.get('Order', 0)}"))
                step_order = step.get("Order", 0)
                text_raw = step.get("Text_raw", "")

                step_node = f"step:{step_id}"
                kg.add_node(
                    step_node,
                    type="Step",
                    step_id=step_id,
                    order=step_order,
                    text=text_raw
                )
                kg.add_edge(guide_node, step_node, relation="HAS_STEP", order=step_order)

                # Sequential step ordering
                if prev_step_node is not None:
                    kg.add_edge(prev_step_node, step_node, relation="NEXT_STEP")
                prev_step_node = step_node

                # Extracted tools per step
                step_tools = step.get("Tools_annotated", []) + step.get("Tools_extracted", [])
                for t in set(step_tools):
                    t_clean = t.strip().lower()
                    if t_clean and t_clean != "na":
                        t_node = f"tool:{t_clean}"
                        kg.add_node(t_node, type="Tool", name=t_clean)
                        kg.add_edge(step_node, t_node, relation="USES_TOOL")

                # Extracted Parts
                parts = step.get("Word_level_parts_clean", [])
                for part in parts:
                    # Check if part is not None and is a string
                    if part and isinstance(part, str):
                        part_clean = part.strip().lower()
                        if part_clean:
                            part_node = f"part:{part_clean}"
                            kg.add_node(part_node, type="Part", name=part_clean)
                            kg.add_edge(step_node, part_node, relation="OPERATES_ON_PART")

                # Extraction Actions / Verbs
                verbs = step.get("Removal_verbs", [])
                for v in verbs:
                    verb_name = v.get("name", "").strip().lower()
                    if verb_name:
                        action_node = f"action:{verb_name}"
                        kg.add_node(action_node, type="Action", name=verb_name)
                        kg.add_edge(step_node, action_node, relation="PERFORMS_ACTION")

    print(f"Graph Construction Completed: {kg.number_of_nodes()} nodes, {kg.number_of_edges()} edges.")
    return kg


def save_kg(kg: nx.DiGraph, output_path: str = "myfixit_kg.json"):
    """Serializes the graph to node-link JSON format."""
    data = nx.node_link_data(kg)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
    print(f"Knowledge Graph saved to {output_path}")


if __name__ == "__main__":
    DATA_DIR = "/home/CL502-22/Downloads/IFIXIT/MyFixit-Dataset/jsons"
    os.makedirs(DATA_DIR, exist_ok=True)
    # Build and export
    graph = extract_and_build_kg(DATA_DIR)
    save_kg(graph, "myfixit_kg.json")