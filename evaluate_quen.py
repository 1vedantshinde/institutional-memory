import json
import time
import torch
import numpy as np
import networkx as nx
from typing import List, Dict, Any
from transformers import AutoModelForCausalLM, AutoTokenizer
from rouge_score import rouge_scorer
import nltk
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from networkx.readwrite import json_graph
import json

from build_kg import extract_and_build_kg
from graph_retriever import FixitGraphRetriever

nltk.download("punkt", quiet=True)


# ----------------------------------------------------
# Evaluation Metric Functions
# ----------------------------------------------------
def compute_f1(pred_tokens: List[str], ref_tokens: List[str]) -> float:
    common = set(pred_tokens) & set(ref_tokens)
    if not common:
        return 0.0
    precision = len(common) / len(pred_tokens)
    recall = len(common) / len(ref_tokens)
    return (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0


def compute_metrics(predictions: List[str], ground_truths: List[str], latencies: List[float]) -> Dict[str, Any]:
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    smooth = SmoothingFunction().method1

    rouge1_scores, rouge2_scores, rougeL_scores = [], [], []
    bleu_scores = []
    f1_scores = []
    exact_matches = []

    for pred, ref in zip(predictions, ground_truths):
        pred_clean = pred.strip().lower()
        ref_clean = ref.strip().lower()

        # Exact Match
        exact_matches.append(1.0 if pred_clean == ref_clean else 0.0)

        # ROUGE
        r_scores = scorer.score(ref_clean, pred_clean)
        rouge1_scores.append(r_scores["rouge1"].fmeasure)
        rouge2_scores.append(r_scores["rouge2"].fmeasure)
        rougeL_scores.append(r_scores["rougeL"].fmeasure)

        # BLEU
        ref_tokens = ref_clean.split()
        pred_tokens = pred_clean.split()
        bleu = sentence_bleu([ref_tokens], pred_tokens, smoothing_function=smooth)
        bleu_scores.append(bleu)

        # F1
        f1 = compute_f1(pred_tokens, ref_tokens)
        f1_scores.append(f1)

    return {
        "rouge1": float(np.mean(rouge1_scores)),
        "rouge2": float(np.mean(rouge2_scores)),
        "rougeL": float(np.mean(rougeL_scores)),
        "bleu": float(np.mean(bleu_scores)),
        "token_f1": float(np.mean(f1_scores)),
        "exact_match": float(np.mean(exact_matches)),
        "avg_latency_seconds": float(np.mean(latencies)),
        "total_evaluated": len(predictions)
    }


# ----------------------------------------------------
# Main Evaluation Pipeline
# ----------------------------------------------------
def main():
    model_name = "Qwen/Qwen2.5-7B-Instruct"  # or "Qwen/Qwen2.5-3B-Instruct"
    data_dir = "./MyFixit-Dataset/jsons"
    output_metrics_file = "qwen2.5_test_metrics.json"

    print("Step 1: Building Knowledge Graph from MyFixit JSON files...")
    kg = extract_and_build_kg(data_dir)
    retriever = FixitGraphRetriever(kg)

    print(f"Step 2: Loading model {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        trust_remote_code=True
    )
    model.eval()

    # Step 3: Define evaluation benchmark dataset
    test_suite = [
    # ---------------- Skills ----------------
    {
        "guide_target": "How to Apply Thermal Paste",
        "question": "What happens if a computer is reassembled without applying thermal paste?",
        "ground_truth": "The processor will overheat and suffer permanent damage, because thermal paste conducts heat from the processor to the heat sink."
    },
    {
        "guide_target": "How to Use Heat Shrink Tubing",
        "question": "What does a 2:1 shrink ratio mean for a 2 mm diameter piece of heat shrink tubing?",
        "ground_truth": "It will shrink down to a diameter of 1 mm once heated."
    },
    {
        "guide_target": "How to Fix a Cross Threaded or Stripped Hole in Aluminum",
        "question": "What rotation pattern should be used when running the tap into a stripped hole?",
        "ground_truth": "Rotate the tap handle clockwise two full rotations, then counterclockwise a quarter turn, and repeat until it no longer turns easily."
    },
    {
        "guide_target": "How to Sew a Whip Stitch",
        "question": "How does stitch length affect the strength of a whip stitch seam?",
        "ground_truth": "A smaller stitch length requires more stitches and produces a stronger seam."
    },
 
    # ---------------- Mac ----------------
    {
        "guide_target": "PowerBook G3 Wallstreet Hard Drive Replacement",
        "question": "How many T8 Torx screws hold the hard drive to its bracket in the PowerBook G3 Wallstreet?",
        "ground_truth": "Four T8 Torx screws secure the hard drive to the bracket."
    },
    {
        "guide_target": "PowerBook G3 Wallstreet RAM Replacement",
        "question": "Where should higher capacity RAM chips be installed in the PowerBook G3 Wallstreet, and why?",
        "ground_truth": "Install higher capacity chips in the bottom slot, so that a later upgrade only requires removing the heat shield instead of the processor."
    },
    {
        "guide_target": "PowerBook G3 Pismo Heat Sink Replacement",
        "question": "Which screws attach the heat sink in the PowerBook G3 Pismo?",
        "ground_truth": "One long silver Phillips #1 screw, plus two T8 Torx screws that attach the heat sink to the processor."
    },
    {
        "guide_target": "MacBook Core 2 Duo Upper Case Replacement",
        "question": "How is the battery released on a MacBook Core 2 Duo before removing the upper case?",
        "ground_truth": "Use a coin or spudger to rotate the battery-locking screw 90 degrees clockwise, then lift the battery out of the computer."
    },
    {
        "guide_target": "MacBook Pro 13\" Retina Display Early 2013 Left Fan Replacement",
        "question": "How many screws secure the lower case on a 13-inch MacBook Pro with Retina Display from Early 2013?",
        "ground_truth": "Ten P5 Pentalobe screws: two 2.3 mm screws and eight 3.0 mm screws."
    },
 
    # ---------------- PC ----------------
    {
        "guide_target": "Removing the HP Elitebook 6930p Top Cover",
        "question": "What is the first step when removing the top cover of an HP EliteBook 6930p?",
        "ground_truth": "Flip the laptop over, push the battery release button to the left, and gently pull the battery out of the laptop."
    },
    {
        "guide_target": "Toshiba Satellite A105-S4074 Fan Replacement",
        "question": "How many screws must be removed from the bottom of the Toshiba Satellite A105-S4074 before separating the case?",
        "ground_truth": "Fifteen 6.0 mm screws and two 5.0 mm screws, using a Phillips #1 screwdriver."
    },
    {
        "guide_target": "Lenovo ThinkPad Edge E520 CD Disk Drive Replacement",
        "question": "How is the battery removed from a Lenovo ThinkPad Edge E520?",
        "ground_truth": "Slide the switch toward the unlocked lock icon and, while holding it there, slide the battery toward the hinge to separate it from the laptop."
    },
    {
        "guide_target": "HP Pavilion x2 10-n113dx Screen Replacement",
        "question": "How many screws hold the screen to the display panel on the HP Pavilion x2 10-n113dx?",
        "ground_truth": "21 Phillips #0 screws in three different head and length sizes."
    },
 
    # ---------------- Phone ----------------
    {
        "guide_target": "iPhone 4 Wi-Fi Antenna Replacement",
        "question": "Which screw acts as the ground for the iPhone 4 Wi-Fi antenna?",
        "ground_truth": "The long 4.8 mm Phillips screw, which is often the culprit behind poor Wi-Fi reception if it is not reinstalled correctly."
    },
    {
        "guide_target": "iPhone 4 Rear Camera Replacement",
        "question": "To what level should the iPhone 4 battery be discharged before disassembly, and why?",
        "ground_truth": "Below 25 percent, because a charged lithium-ion battery can catch fire or explode if it is accidentally punctured."
    },
    {
        "guide_target": "iPhone 4 Vibrator Replacement",
        "question": "Which screws secure the vibrator to the inner frame of the iPhone 4?",
        "ground_truth": "One 6 mm Phillips screw and one 1.4 mm Phillips screw."
    },
    {
        "guide_target": "iPhone 7 Logic Board  Disconnection",
        "question": "How should the 2.2 mm standoff screw on the grounding bracket be removed on an iPhone 7?",
        "ground_truth": "With a standoff screwdriver or standoff driver bit; a small flathead can work but risks slipping and damaging surrounding components."
    },
 
    # ---------------- Tablet ----------------
    {
        "guide_target": "Insignia Flex 10.1 Battery Replacement",
        "question": "How is the battery attached to the motherboard in the Insignia Flex 10.1?",
        "ground_truth": "By five wires soldered to the motherboard, which must be desoldered one joint at a time."
    },
    {
        "guide_target": "Kindle Touch Motherboard Replacement",
        "question": "How long should the iOpener be applied to loosen the glue holding the WiFi unit to the Kindle Touch screen?",
        "ground_truth": "About 30 seconds, after which the heating element is removed and a thin tool is used to separate the WiFi unit from the screen."
    },
    {
        "guide_target": "LeapFrog LeapPad2 Explorer Speaker Replacement",
        "question": "What batteries does the LeapFrog LeapPad2 Explorer use and how are they removed?",
        "ground_truth": "Four AA alkaline batteries, pried up by pushing down from the positive end toward the negative end."
    },
 
    # ---------------- Camera ----------------
    {
        "guide_target": "Nikon D3000 On/Off Switch and Shutter Button Replacement",
        "question": "How many screws are removed from the bottom of the Nikon D3000 in the first step?",
        "ground_truth": "Eleven screws: six 3 x 2.5 mm Phillips screws, three 3 x 5.5 mm screws near the battery cover, and two more 3 x 5.5 mm screws under the battery cover."
    },
    {
        "guide_target": "FujiFilm FinePix XP50 LCD Screen Replacement",
        "question": "How many clasps must be unlatched on the FujiFilm FinePix XP50, and what conceals one of them?",
        "ground_truth": "Four clasps, one on each side of the camera, and the fourth is concealed by the battery door."
    },
    {
        "guide_target": "Nikon Coolpix P90 LCD Screen Replacement",
        "question": "Why must the back cover of the Nikon Coolpix P90 not be fully removed right away?",
        "ground_truth": "A data transfer ribbon still connects the LCD screen to the motherboard and must be released from its socket first."
    },
    {
        "guide_target": "Panasonic Lumix DMC-ZS6 Lens Assembly Replacement",
        "question": "How is the tripod mount removed from the Panasonic Lumix DMC-ZS6?",
        "ground_truth": "Insert the tip of the 2.0 mm flathead into the center hole of the tripod mount, apply force away from the button, then lift the mount out of the camera body."
    },
 
    # ---------------- Game Console ----------------
    {
        "guide_target": "Nintendo GameCube Lens Recalibration",
        "question": "How far should the potentiometer be turned during GameCube lens recalibration, and in which direction?",
        "ground_truth": "No more than three degrees counter-clockwise, because turning it too far can make the laser strong enough to burn discs."
    },
    {
        "guide_target": "Nintendo Entertainment System 72-PIN Connector Replacement",
        "question": "Which screws hold the cartridge tray in the Nintendo Entertainment System?",
        "ground_truth": "Two silver 17.45 mm Phillips screws and two bronze 13.25 mm Phillips screws."
    },
    {
        "guide_target": "Xbox One Kinect Colour Camera Replacement",
        "question": "Which screwdriver and screws free the colour camera itself on the Xbox One Kinect?",
        "ground_truth": "A T5 screwdriver, used to remove four 1.9 x 10.2 mm screws from the four corners of the camera."
    },
 
    # ---------------- Car and Truck ----------------
    {
        "guide_target": "2005 Honda Accord Engine Oil Replacement",
        "question": "What torque should the drain bolt be tightened to during a 2005 Honda Accord oil change?",
        "ground_truth": "29 ft-lb, after replacing the crush washer on the drain bolt with a new one."
    },
    {
        "guide_target": "2003-2011 Honda Element Spark Plug Replacement",
        "question": "How tight should new spark plugs be on a 2003-2011 Honda Element?",
        "ground_truth": "Thread each plug in hand tight, then tighten all four plugs a half turn past hand tight."
    },
    {
        "guide_target": "2008-2012 Honda Accord  ATF Flush - Every 80k Miles",
        "question": "How often should a full ATF flush be done on a 2008-2012 Honda Accord compared with a drain and fill?",
        "ground_truth": "A full flush every 80,000 miles and a plain drain and fill every 30,000 miles."
    },
    {
        "guide_target": "2000-2005 Audi A4 Headlight Replacement (via Headlight Assembly Removal)",
        "question": "What type of bulb does a 2000-2005 Audi A4 headlight take?",
        "ground_truth": "A 12 volt, 55 watt, H7-style bulb."
    },
 
    # ---------------- Vehicle ----------------
    {
        "guide_target": "Harley-Davidson Sportster Evolution Transmission/Primary Oil Change",
        "question": "What is the correct torque specification for the transmission drain plug on a Harley-Davidson Sportster Evolution?",
        "ground_truth": "14 to 21 ft-lbs (168 to 252 in-lbs); over-tightening can strip the threads in the aluminum housing."
    },
    {
        "guide_target": "How to Replace the Front Brake Pads on a 1994 Honda VFR 750",
        "question": "To what torque should the brake pad retainer pin be tightened on a 1994 Honda VFR 750?",
        "ground_truth": "11 to 14 ft-lbs, which is 15 to 20 N*m, using a torque wrench."
    },
    {
        "guide_target": "DJI Phantom 3 Advanced Motor Replacement",
        "question": "How are the motor wires disconnected from the flight controller on a DJI Phantom 3 Advanced?",
        "ground_truth": "Remove the glue covering the three wires, then desolder the black, yellow, and red wires where they connect to the flight controller."
    },
 
    # ---------------- Household ----------------
    {
        "guide_target": "Nerf Recon CS-6 O-Ring Replacement",
        "question": "Why should the trigger be pulled before separating the two halves of the Nerf Recon CS-6?",
        "ground_truth": "Pulling the trigger releases the compression of the main spring so it does not launch out of the gun when the two halves are separated."
    },
    {
        "guide_target": "Porter-Cable PC60TAG Pinion Gear Replacement",
        "question": "What tool is used to remove the pinion gear from the Porter-Cable PC60TAG head?",
        "ground_truth": "A pair of needle nose pliers."
    },
 
    # ---------------- Appliance ----------------
    {
        "guide_target": "Tune-up A Rancilio Silvia Espresso Machine",
        "question": "How is a Version 3 Rancilio Silvia identified?",
        "ground_truth": "By its ergonomic handle, the larger steam handle with a silver cap on it, and a steam wand mounted on a ball joint."
    },
    {
        "guide_target": "Dyson Ball Multi Floor Upright Wheels Replacement",
        "question": "How is the side hemisphere removed on a Dyson Ball Multi Floor upright?",
        "ground_truth": "Twist the small gray center piece counterclockwise with needle-nose pliers and pull it out, then repeat on the exposed center piece to pull the whole hemisphere off."
    },
    {
        "guide_target": "Honeywell HY-254-TGT Fan Blade Replacement",
        "question": "Why can't the front panel of the Honeywell HY-254-TGT be completely removed?",
        "ground_truth": "It is not detached from the body and can only be leaned forward; forcing it off may damage the electronics."
    },
    {
        "guide_target": "iRobot Roomba 655 Pet Series Motherboard Replacement",
        "question": "How is the battery removed from an iRobot Roomba 655?",
        "ground_truth": "Grab the two pieces of green tape with your thumb and index finger and pull the battery straight up."
    },
 
    # ---------------- Electronics ----------------
    {
        "guide_target": "Bose SoundLink III Charging Port Replacement",
        "question": "How many screws hold the four speakers in the Bose SoundLink III, and what sizes are they?",
        "ground_truth": "Sixteen Torx T10 screws in total, all 12.5 mm except the two middle screws on the right side, which are 21 mm."
    },
    {
        "guide_target": "Behringer Eurolive B212D Power PCB Replacement",
        "question": "Why must the two screws with washers be removed first from the Behringer Eurolive B212D electronics box?",
        "ground_truth": "Their holes are slots designed to accommodate slop in the assembly, so unscrewing them out of order can make the other five screws difficult to remove or damage them."
    },
    {
        "guide_target": "BenQ HT1075 Projector Circuit Board Replacement",
        "question": "How many screws hold the back cover of the BenQ HT1075 projector?",
        "ground_truth": "Five 9.5 mm Phillips #1 screws."
    },
    {
        "guide_target": "iHome iH5 Display Screen Replacement",
        "question": "What hazard is present on the back of the iHome iH5 circuit board?",
        "ground_truth": "Capacitors, the blue cylinders, which can discharge and give you a shock if touched."
    },
 
    # ---------------- Computer Hardware ----------------
    {
        "guide_target": "Temporarily repair a lost-cause graphics card by heating it up in an oven",
        "question": "What oven temperature and bake time are recommended for reflowing a graphics card?",
        "ground_truth": "Preheat to 385F (195C) and bake for 8 to 12 minutes, raising the temperature slightly on a repeat attempt."
    },
    {
        "guide_target": "Dell E193FPc Inverter Board Replacement",
        "question": "How many screws secure the stand to the back of the Dell E193FPc monitor?",
        "ground_truth": "Four 11.9 mm Phillips #2 screws."
    },
 
    # ---------------- Media Player ----------------
    {
        "guide_target": "iHome iH8BR Speakers Replacement",
        "question": "What is the only thing connecting the bottom case to the rest of the iHome iH8BR once the eight screws are out?",
        "ground_truth": "A white ribbon wire, so the bottom case should be tilted rather than yanked away."
    },
    {
        "guide_target": "Philips DC320 37 LCD Screen Replacement",
        "question": "How many screws hold the bottom panel to the Philips DC320 dock?",
        "ground_truth": "Four 15.5 mm Phillips #2 screws."
    },
 
    # ---------------- Apparel ----------------
    {
        "guide_target": "Samsung Gear S2 Battery Replacement",
        "question": "How far may a plastic opening tool be inserted when prying open a Samsung Gear S2?",
        "ground_truth": "No more than 3 millimeters, because inserting it further may damage the seal and the electric components."
    },
    {
        "guide_target": "LG G Watch Display Assembly Replacement",
        "question": "How is the wristband detached from the LG G Watch?",
        "ground_truth": "Slide the wristband down the spring bar to expose its shoulder, then use tweezers to depress the spring bar until it collapses and pops out of its hole."
    },
]


    predictions = []
    ground_truths = []
    latencies = []
    detailed_records = []

    print("Step 4: Running Inference...")
    for item in test_suite:
        guide_name = item["guide_target"]
        query = item["question"]
        ref_ans = item["ground_truth"]

        # Retrieve Knowledge Graph context
        kg_context = retriever.retrieve_guide_subgraph_context(guide_name)

        # Build Prompt for Qwen 2.5
        messages = [
            {
                "role": "system",
                "content": "You are an expert technical assistant. Answer the user's question accurately using ONLY the provided Knowledge Graph context."
            },
            {
                "role": "system",
                "content": f"Knowledge Graph Context:\n{kg_context}"
            },
            {
                "role": "user",
                "content": query
            }
        ]

        prompt_text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(prompt_text, return_tensors="pt").to(model.device)

        start_time = time.time()
        with torch.no_grad():
            output_tokens = model.generate(
                **inputs,
                max_new_tokens=150,
                temperature=0.1,
                do_sample=False,
                pad_token_id=tokenizer.eos_token_id
            )
        latency = time.time() - start_time

        pred_text = tokenizer.decode(
            output_tokens[0][inputs.input_ids.shape[1]:],
            skip_special_tokens=True
        ).strip()

        predictions.append(pred_text)
        ground_truths.append(ref_ans)
        latencies.append(latency)

        detailed_records.append({
            "guide": guide_name,
            "question": query,
            "ground_truth": ref_ans,
            "prediction": pred_text,
            "latency_sec": latency
        })
        print(f"\n[Q]: {query}\n[Pred]: {pred_text}\n[Ref]: {ref_ans}\n[Latency]: {latency:.2f}s")

    # Step 5: Calculate and Save Metrics
    print("\nStep 5: Computing test metrics...")
    summary_metrics = compute_metrics(predictions, ground_truths, latencies)

    results_payload = {
        "model": model_name,
        "metrics_summary": summary_metrics,
        "detailed_predictions": detailed_records
    }

    with open(output_metrics_file, "w", encoding="utf-8") as f:
        json.dump(results_payload, f, indent=2)

    print("\n" + "=" * 40)
    print("      EVALUATION METRICS SUMMARY      ")
    print("=" * 40)
    for k, v in summary_metrics.items():
        print(f"  {k:22s}: {v:.4f}" if isinstance(v, float) else f"  {k:22s}: {v}")
    print(f"\nResults successfully saved to: {output_metrics_file}")


if __name__ == "__main__":
    main()