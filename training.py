from datasets import load_dataset
from peft import LoraConfig, get_peft_model
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

# 1. Load Model & Tokenizer
model_id = "Qwen/Qwen2.5-7B-Instruct"
tokenizer = AutoTokenizer.from_pretrained(model_id)
bnb_config = BitsAndBytesConfig(
    load_in_4bit=True, bnb_4bit_compute_dtype="bfloat16"
)
model = AutoModelForCausalLM.from_pretrained(
    model_id, quantization_config=bnb_config, device_map="auto"
)

# 2. Set up LoRA Configuration
lora_config = LoraConfig(
    r=16,
    lora_alpha=32,
    lora_dropout=0.05,
    target_modules=[
        "q_proj",
        "k_proj",
        "v_proj",
        "o_proj",
        "gate_proj",
        "up_proj",
        "down_proj",
    ],
    task_type="CAUSAL_LM",
)
model = get_peft_model(model, lora_config)


# 3. Load & Format Dataset from Folder
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


# Point directly to your folder path and load all JSON files under it
raw_dataset = load_dataset(
    "json", data_files="MyFixit-Dataset/jsons/*.json", split="train"
)
dataset = raw_dataset.map(format_example)

# 4. Initialize Trainer
trainer = SFTTrainer(
    model=model,
    train_dataset=dataset,
    args=SFTConfig(
        output_dir="./qwen-repair-sft",
        num_train_epochs=3,
        per_device_train_batch_size=4,
        learning_rate=2e-4,
        dataset_text_field="text",  # Explicitly specify the formatted text column
    ),
)

trainer.train()