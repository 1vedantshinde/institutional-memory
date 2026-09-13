#!/usr/bin/env python3
"""Train a Qwen2.5 model on the iFixit JSON repair-manual format.

This script reads the JSON files under MyFixit-Dataset/jsons, converts each
repair guide into a compact prompt/response pair, trains a Qwen2.5 model with
LoRA, and saves test-set predictions to a separate text file.

Usage examples:
  python train.py --dry-run --max-train-examples 5
  python train.py --model-name Qwen/Qwen2.5-7B-Instruct --epochs 2
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def read_json_records(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON file that may be either a list of objects or NDJSON."""
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception:
        return []

    if not raw.strip():
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        records: List[Dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
        return records

    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if isinstance(data, dict):
        for key in ("data", "items", "manuals", "records", "guides"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [data]
    return []


def extract_step_text(step: Dict[str, Any]) -> str:
    lines = step.get("Lines") or []
    parts: List[str] = []
    for line in lines:
        if isinstance(line, dict):
            text = line.get("Text") or line.get("text") or ""
            if text:
                parts.append(_safe_string(text))
    if parts:
        return " ".join(parts)

    text_raw = step.get("Text_raw") or step.get("text_raw") or ""
    if text_raw:
        return _safe_string(text_raw)
    return ""


def compact_toolbox(toolbox: Iterable[Any]) -> List[str]:
    tools: List[str] = []
    for item in toolbox or []:
        if isinstance(item, dict):
            name = item.get("Name")
            if isinstance(name, list):
                tools.extend([_safe_string(v) for v in name if _safe_string(v)])
            elif isinstance(name, str):
                tools.append(_safe_string(name))
        elif isinstance(item, str):
            tools.append(_safe_string(item))
    return tools[:12]


def compact_steps(steps: Iterable[Dict[str, Any]], max_steps: int = 6) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    for step in list(steps)[:max_steps]:
        if not isinstance(step, dict):
            continue
        step_text = extract_step_text(step)
        extracted = step.get("Tools_extracted") or []
        if isinstance(extracted, str):
            extracted = [extracted]
        output.append(
            {
                "Order": step.get("Order"),
                "Text": step_text,
                "Tools_extracted": [
                    _safe_string(tool) for tool in extracted if _safe_string(tool)
                ],
            }
        )
    return output


def build_manual_record(record: Dict[str, Any]) -> Dict[str, Any]:
    title = _safe_string(record.get("Title") or record.get("title") or "Unknown title")
    category = _safe_string(
        record.get("Category") or record.get("category") or "Unknown category"
    )
    subject = _safe_string(record.get("Subject") or record.get("subject") or "")
    toolbox = compact_toolbox(record.get("Toolbox") or [])
    steps = compact_steps(record.get("Steps") or [])

    return {
        "Title": title,
        "Category": category,
        "Subject": subject,
        "Toolbox": toolbox,
        "Steps": steps,
    }


def build_pairs_from_directory(data_dir: str, max_examples: int | None = None) -> List[Dict[str, str]]:
    """Build prompt/response pairs from all JSON files in a directory."""
    pairs: List[Dict[str, str]] = []
    root = Path(data_dir)
    if not root.exists():
        raise FileNotFoundError(f"Data directory not found: {root}")

    files = sorted(root.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No .json files found under: {root}")

    for file_path in files:
        for record in read_json_records(file_path):
            if not isinstance(record, dict):
                continue
            compact = build_manual_record(record)
            if not compact["Title"]:
                continue

            prompt = (
                "You are given an iFixit repair manual in JSON format. "
                "Keep the same JSON structure and values, but return a compact, valid JSON object.\n\n"
                f"Input JSON:\n{json.dumps(compact, ensure_ascii=False)}"
            )
            response = json.dumps(compact, ensure_ascii=False)
            pairs.append({"instruction": prompt, "response": response})

            if max_examples is not None and len(pairs) >= max_examples:
                return pairs

    return pairs


def format_example_for_qwen(example: Dict[str, str], tokenizer: Any) -> Dict[str, str]:
    prompt = example["instruction"]
    response = example["response"]
    text = tokenizer.apply_chat_template(
        [
            {"role": "user", "content": prompt},
            {"role": "assistant", "content": response},
        ],
        tokenize=False,
        add_generation_prompt=False,
    )
    return {"text": text}


def train_model(args: argparse.Namespace) -> None:
    import inspect

    from datasets import Dataset
    from peft import LoraConfig, get_peft_model
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
    from trl import SFTConfig, SFTTrainer
    import torch

    data_dir = Path(args.data_dir)
    pairs = build_pairs_from_directory(str(data_dir), args.max_train_examples)
    if len(pairs) < 2:
        raise ValueError(
            f"Not enough training examples were generated from {data_dir}. "
            "Check the JSON files or use a different directory."
        )

    dataset = Dataset.from_list(pairs)
    split = dataset.train_test_split(test_size=args.test_size, seed=args.seed)
    train_dataset = split["train"]
    test_dataset = split["test"]

    tokenizer = AutoTokenizer.from_pretrained(args.model_name)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    if torch.cuda.is_available():
        bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_compute_dtype=torch.bfloat16,
            bnb_4bit_use_double_quant=True,
        )
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name,
            quantization_config=bnb_config,
            device_map="auto",
        )
    else:
        model = AutoModelForCausalLM.from_pretrained(
            args.model_name,
            device_map={"": "cpu"},
            torch_dtype=torch.float32,
        )

    lora_config = LoraConfig(
        r=args.lora_r,
        lora_alpha=args.lora_alpha,
        lora_dropout=args.lora_dropout,
        target_modules=[
            "q_proj",
            "k_proj",
            "v_proj",
            "o_proj",
            "gate_proj",
            "up_proj",
            "down_proj",
        ],
        bias="none",
        task_type="CAUSAL_LM",
    )
    model = get_peft_model(model, lora_config)

    train_dataset = train_dataset.map(
        lambda x: format_example_for_qwen(x, tokenizer),
        batched=False,
    )
    test_dataset = test_dataset.map(
        lambda x: format_example_for_qwen(x, tokenizer),
        batched=False,
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    sft_kwargs = dict(
        output_dir=str(output_dir),
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.learning_rate,
        num_train_epochs=args.epochs,
        logging_steps=10,
        bf16=torch.cuda.is_available(),
        fp16=not torch.cuda.is_available(),
        load_best_model_at_end=False,
        remove_unused_columns=False,
        report_to=[],
        dataset_text_field="text",
    )

    sft_params = inspect.signature(SFTConfig).parameters
    if "eval_strategy" in sft_params:
        sft_kwargs["eval_strategy"] = "epoch"
    elif "evaluation_strategy" in sft_params:
        sft_kwargs["evaluation_strategy"] = "epoch"
    if "save_strategy" in sft_params:
        sft_kwargs["save_strategy"] = "epoch"

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_dataset,
        eval_dataset=test_dataset,
        args=SFTConfig(**sft_kwargs),
    )

    trainer.train()

    results_path = output_dir / args.results_file
    results_path.parent.mkdir(parents=True, exist_ok=True)

    with results_path.open("w", encoding="utf-8") as f:
        f.write(f"Qwen2.5 training results\n")
        f.write(f"Model: {args.model_name}\n")
        f.write(f"Train examples: {len(train_dataset)}\n")
        f.write(f"Test examples: {len(test_dataset)}\n\n")

        for idx, example in enumerate(test_dataset):
            prompt = example["text"]
            prompt_only = prompt.rsplit("<|assistant|>", 1)[0] if "<|assistant|>" in prompt else prompt
            inputs = tokenizer(prompt_only, return_tensors="pt").to(model.device)
            with torch.no_grad():
                generated = model.generate(
                    **inputs,
                    max_new_tokens=min(256, args.max_new_tokens),
                    do_sample=True,
                    temperature=0.2,
                    top_p=0.9,
                    eos_token_id=tokenizer.eos_token_id,
                )
            prediction = tokenizer.decode(
                generated[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True
            )

            ground_truth = example["text"][example["text"].rfind("<|assistant|>") + len("<|assistant|>") :]
            f.write(f"Example {idx}\n")
            f.write(f"Prompt:\n{prompt_only}\n\n")
            f.write(f"Ground Truth:\n{ground_truth}\n\n")
            f.write(f"Prediction:\n{prediction}\n\n")
            f.write("-" * 80 + "\n\n")

    print(f"Training finished. Test results file saved to: {results_path}")


def dry_run(args: argparse.Namespace) -> None:
    pairs = build_pairs_from_directory(args.data_dir, args.max_train_examples)
    print(f"JSON files scanned: {len(sorted(Path(args.data_dir).glob('*.json')))}")
    print(f"Generated training examples: {len(pairs)}")
    if not pairs:
        raise ValueError("No training examples were generated.")
    for i in range(min(2, len(pairs))):
        item = pairs[i]
        print(f"\nExample {i + 1}:")
        print(item["instruction"][:600])
        print("\nResponse preview:")
        print(item["response"][:400])


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Qwen2.5 on the iFixit JSON repair dataset.")
    parser.add_argument("--data-dir", default="MyFixit-Dataset/jsons", help="Directory containing the JSON repair-manual files.")
    parser.add_argument("--model-name", default="Qwen/Qwen2.5-7B-Instruct", help="Qwen2.5 model to fine-tune.")
    parser.add_argument("--output-dir", default="./qwen2.5-myfixit", help="Directory for checkpoints and logs.")
    parser.add_argument("--results-file", default="test_results.txt", help="Text file for saved evaluation results.")
    parser.add_argument("--epochs", type=int, default=2, help="Number of training epochs.")
    parser.add_argument("--batch-size", type=int, default=2, help="Per-device training batch size.")
    parser.add_argument("--learning-rate", type=float, default=2e-4, help="Learning rate.")
    parser.add_argument("--lora-r", type=int, default=16, help="LoRA rank.")
    parser.add_argument("--lora-alpha", type=int, default=32, help="LoRA alpha.")
    parser.add_argument("--lora-dropout", type=float, default=0.05, help="LoRA dropout.")
    parser.add_argument("--test-size", type=float, default=0.1, help="Fraction of the dataset used for testing.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed.")
    parser.add_argument("--max-train-examples", type=int, default=None, help="Optional cap on training examples for quick testing.")
    parser.add_argument("--max-new-tokens", type=int, default=256, help="Max generation tokens for the test prediction output.")
    parser.add_argument("--dry-run", action="store_true", help="Build and preview the dataset without running a full training session.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.dry_run:
        dry_run(args)
        return

    train_model(args)


if __name__ == "__main__":
    main()
