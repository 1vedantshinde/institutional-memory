import os
import json
import time
import networkx as nx
import matplotlib.pyplot as plt
import numpy as np
from rouge_score import rouge_scorer
from transformers import Qwen2_5_VLForConditionalGeneration, AutoProcessor
from qwen_vl_utils import process_vision_info
import torch

# 1. KNOWLEDGE GRAPH CONSTRUCTION
def build_knowledge_graph(json_directory):
    """
    Parses files like "Mac.json" from the directory into a NetworkX Graph.
    """
    kg = nx.DiGraph()
    for filename in os.listdir(json_directory):
        if not filename.endswith('.json'):
            continue
        filepath = os.path.join(json_directory, filename)
        
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f.readlines():
                if not line.strip(): continue
                guide = json.loads(line)
                
                guide_id = f"guide:{guide['Guidid']}"
                kg.add_node(guide_id, type="Guide", title=guide['Title'])
                
                for tool in guide.get('Toolbox', []):
                    tool_id = f"tool:{tool['Name'].lower()}"
                    kg.add_node(tool_id, type="Tool", name=tool['Name'])
                    kg.add_edge(guide_id, tool_id, relation="REQUIRES_TOOL")
                
                for step in guide.get('Steps', []):
                    step_id = f"step:{guide['Guidid']}_{step['Order']}"
                    kg.add_node(step_id, type="Step", text=step['Text_raw'], order=step['Order'])
                    kg.add_edge(guide_id, step_id, relation="HAS_STEP")
                    
                    for img_url in step.get('Images', []):
                        img_id = f"image:{img_url}"
                        kg.add_node(img_id, type="Image", url=img_url)
                        kg.add_edge(step_id, img_id, relation="HAS_IMAGE")
    return kg

# 2. XAI SUBGRAPH RETRIEVER
def retrieve_context_and_xai(kg, guide_title):
    """
    Fetches the subgraph context and outputs XAI node traces.
    """
    guide_node = next((n for n, d in kg.nodes(data=True) if d.get('type') == 'Guide' and guide_title in d.get('title', '')), None)
    
    if not guide_node:
        return "", [], "XAI Trace: No matching guide found."

    subgraph_nodes = {guide_node}
    context_str = f"Repair Guide: {kg.nodes[guide_node]['title']}\n"
    
    tools = [v for u, v, d in kg.edges(guide_node, data=True) if d['relation'] == 'REQUIRES_TOOL']
    subgraph_nodes.update(tools)
    context_str += "Required Tools: " + ", ".join([f'"{kg.nodes[t]["name"]}"' for t in tools]) + "\n\n"
    
    steps = [(v, kg.nodes[v]['order']) for u, v, d in kg.edges(guide_node, data=True) if d['relation'] == 'HAS_STEP']
    steps.sort(key=lambda x: x[1])
    
    images_to_process = []
    for step_node, order in steps:
        subgraph_nodes.add(step_node)
        step_text = kg.nodes[step_node]['text']
        
        imgs = [v for u, v, d in kg.edges(step_node, data=True) if d['relation'] == 'HAS_IMAGE']
        subgraph_nodes.update(imgs)
        
        img_str = ""
        if imgs:
            img_url = kg.nodes[imgs[0]]['url']
            img_str = f" [Image URL: {img_url}]"
            images_to_process.append({"type": "image", "image": img_url})
            
        context_str += f"Step {order + 1}: {step_text}{img_str}\n"
        
    xai_trace = f"XAI Trace: Activated {len(subgraph_nodes)} nodes (1 Guide, {len(steps)} Steps, {len(tools)} Tools, {len(images_to_process)} Images)."
    return context_str, images_to_process, xai_trace

# 3. QWEN 2.5 INFERENCE & EVALUATION
def run_evaluation(kg, test_cases):
    model_name = "Qwen/Qwen2.5-VL-7B-Instruct"
    processor = AutoProcessor.from_pretrained(model_name)
    model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
        model_name, torch_dtype="auto", device_map="auto"
    )
    
    scorer = rouge_scorer.RougeScorer(['rougeL'], use_stemmer=True)
    results = []
    latencies = []
    
    for case in test_cases:
        context, images, xai_trace = retrieve_context_and_xai(kg, case["guide"])
        print(f"\n{xai_trace}")
        
        prompt = (
            "You are a technical repair assistant. Answer the user's question based on the provided guide context and images.\n"
            "CRITICAL INSTRUCTIONS:\n"
            "1. You must use the EXACT words for the repair steps from the context.\n"
            "2. You must quote all tools exactly as written.\n"
            "3. If a relevant image URL is present in the context, supply it in your answer.\n\n"
            f"Context:\n{context}\n\nQuestion: {case['query']}"
        )
        
        messages = [{"role": "user", "content": images + [{"type": "text", "text": prompt}]}]
        text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        
        inputs = processor(text=[text], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt").to(model.device)
        
        start_time = time.time()
        with torch.no_grad():
            generated_ids = model.generate(**inputs, max_new_tokens=200)
        latency = time.time() - start_time
        latencies.append(latency)
        
        output_text = processor.batch_decode(
            [out[len(inp):] for input_ids, out in zip(inputs.input_ids, generated_ids)],
            skip_special_tokens=True
        )[0].strip()
        
        rouge_score = scorer.score(case["expected"], output_text)['rougeL'].fmeasure
        
        results.append({
            "query": case['query'],
            "latency": latency,
            "rouge_L": rouge_score,
            "prediction": output_text,
            "xai_provenance": xai_trace
        })

    # Save metrics
    with open("evaluation_metrics.json", "w") as f:
        json.dump(results, f, indent=4)
        
    # Plotting Latency
    plt.figure(figsize=(8, 5))
    plt.bar(range(len(latencies)), latencies, color='skyblue')
    plt.xlabel("Test Case ID")
    plt.ylabel("Latency (seconds)")
    plt.title("Qwen 2.5 VL Inference Latency per Query")
    plt.savefig("latency_graph.png")
    plt.close()
    print("\nMetrics saved to evaluation_metrics.json and latency_graph.png")

if __name__ == "__main__":
    test_cases = [
        {
            "guide": "PowerBook G3 Wallstreet Hard Drive Replacement",
            "query": "What are the exact steps and tools to remove the heat shield, and what is the image URL?",
            "expected": "remove the two phillips screws from the heat shield . one screw is shorter than the other . when putting the wallstreet back together , this screw goes in the middle of the heat shield . Tools: \"ph0 phillips screwdriver\". Image URL: https://d3nevzfk7ii3be.cloudfront.net/igi/mBiGMsChBxQsE3XN.standard"
        }
    ]
    kg = build_knowledge_graph("./MyFixit-Dataset/jsons")
    run_evaluation(kg, test_cases)