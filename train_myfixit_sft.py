"""
Fine-tune Qwen2.5-7B-Instruct (QLoRA) on the MyFixit-Dataset repair guides.

Point DATASET_DIR at your local `MyFixit-Dataset/jsons` folder. The script
walks every .json file in that folder, turns each repair guide into an
(instruction, response) pair, and trains on the whole thing.

Usage:
    python train_myfixit_sft.py --data_dir /path/to/MyFixit-Dataset/jsons
"""

import argparse
import json
import random
from pathlib import Path

from datasets import Dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig, get_peft_model
from trl import SFTTrainer, SFTConfig

MODEL_ID = "Qwen/Qwen2.5-7B-Instruct"


# --------------------------------------------------------------------------
# 1. Load every guide out of the jsons folder
# --------------------------------------------------------------------------
def iter_guides(jsons_dir):
    """Yield one guide dict at a time from every .json file in jsons_dir.

    MyFixit-Dataset ships each category file (Appliance.json, Laptop.json,
    ...) as JSON-Lines: one guide object per line. This also falls back to
    a plain JSON array/single object per file, in case a folder mixes
    formats.
    """
    jsons_dir = Path(jsons_dir)
    files = sorted(jsons_dir.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No .json files found under {jsons_dir}")

    for fp in files:
        with open(fp, "r", encoding="utf-8") as f:
            first_char = f.read(1)
            f.seek(0)
            if first_char == "[":
                for guide in json.load(f):
                    yield guide
            else:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        continue


def guide_to_examples(guide):
    """Turn one MyFixit guide into one instruction/response pair PER STEP.

    Each example asks for a single step of a named guide, so the model
    learns the granular action-by-action structure rather than one long
    monologue per guide.
    """
    title = (guide.get("Title") or "").strip()
    category = (guide.get("Category") or "").strip()
    steps = sorted(guide.get("Steps", []), key=lambda s: s.get("Order", 0))

    ordered_steps = []
    for step in steps:
        text = (step.get("Text_raw") or "").strip()
        if text:
            ordered_steps.append(step)

    if not title or not ordered_steps:
        return []

    total = len(ordered_steps)
    examples = []
    for i, step in enumerate(ordered_steps):
        step_num = i + 1
        instruction = (
            f"In the repair guide '{title}'"
            + (f" (Category: {category})" if category else "")
            + f", what is step {step_num} of {total}?"
        )
        response = (step.get("Text_raw") or "").strip()

        step_tools = sorted({
            t.strip() for t in step.get("Tools_extracted", []) if t
        })
        if step_tools:
            response += "\n\nTools used in this step: " + ", ".join(step_tools)

        examples.append({"instruction": instruction, "response": response})

    return examples


def build_dataset(jsons_dir):
    examples = []
    for guide in iter_guides(jsons_dir):
        examples.extend(guide_to_examples(guide))
    if not examples:
        raise ValueError("Parsed 0 usable examples — check the folder path/format.")
    return examples


# --------------------------------------------------------------------------
# 2. Main
# --------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data_dir", required=True,
                         help="Path to MyFixit-Dataset/jsons")
    parser.add_argument("--output_dir", default="./qwen-repair-sft")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--eval_holdout", type=int, default=10,
                         help="How many examples to hold out for the results check")
    args = parser.parse_args()

    print(f"Scanning {args.data_dir} ...")
    examples = build_dataset(args.data_dir)
    print(f"Built {len(examples)} instruction/response pairs from the jsons folder.")

    random.seed(42)
    random.shuffle(examples)
    eval_examples = examples[: args.eval_holdout]
    train_examples = examples[args.eval_holdout:]

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    def format_example(ex):
        return {
            "text": tokenizer.apply_chat_template(
                [
                    {"role": "user", "content": ex["instruction"]},
                    {"role": "assistant", "content": ex["response"]},
                ],
                tokenize=False,
            )
        }

    train_dataset = Dataset.from_list(train_examples).map(format_example)

    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_compute_dtype="bfloat16",
        bnb_4bit_quant_type="nf4",
    )
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_ID, quantization_config=bnb_config, device_map="auto"
    )

    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_dataset,
        args=SFTConfig(
            output_dir=args.output_dir,
            num_train_epochs=args.epochs,
            per_device_train_batch_size=4,
            gradient_accumulation_steps=4,
            learning_rate=2e-4,
            logging_steps=10,
            save_strategy="epoch",
            bf16=True,
        ),
    )

    trainer.train()
    trainer.save_model(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print(f"\nAdapter saved to {args.output_dir}")

    # ----------------------------------------------------------------
    # 3. Show results on held-out examples
    # ----------------------------------------------------------------
    print("\n" + "=" * 80)
    print("RESULTS ON HELD-OUT EXAMPLES")
    print("=" * 80)
    model.eval()
    for ex in eval_examples:
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": ex["instruction"]}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
        output_ids = model.generate(
            **inputs,
            max_new_tokens=400,
            do_sample=True,
            temperature=0.7,
            top_p=0.9,
        )
        generated = tokenizer.decode(
            output_ids[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
        )

        print(f"\n--- INSTRUCTION ---\n{ex['instruction']}")
        print(f"\n--- MODEL OUTPUT ---\n{generated}")
        print(f"\n--- GROUND TRUTH (for comparison) ---\n{ex['response']}")
        print("-" * 80)


if __name__ == "__main__":
    main()
