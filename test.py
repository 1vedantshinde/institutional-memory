import torch
from transformers import AutoTokenizer, AutoModelForCausalLM
from peft import PeftModel

# --- Configuration ---
base_model_name = "Qwen/Qwen2.5-7B-Instruct"
adapter_path = "./qwen2.5-myfixit/checkpoint-34500"  # The folder from your training logs

print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(base_model_name)

print("Loading base model...")
# Using bfloat16 or float16 is highly recommended for a 7B model to fit in GPU memory
base_model = AutoModelForCausalLM.from_pretrained(
    base_model_name,
    torch_dtype=torch.bfloat16, 
    device_map="auto" # Automatically places layers on available GPUs/CPU
)

print("Applying PEFT adapter...")
model = PeftModel.from_pretrained(base_model, adapter_path)

# Optional: If you want slightly faster inference, you can merge the adapter into the base model
# model = model.merge_and_unload()

def generate_answer(user_prompt):
    # Qwen-Instruct models expect a specific chat format. 
    # Adjust the system prompt if you used a different one during training.
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": user_prompt}
    ]
    
    # Apply Qwen's built-in chat template
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    # Tokenize input and move to the same device as the model
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    # Generate the response
    with torch.no_grad():
        generated_ids = model.generate(
            **model_inputs,
            max_new_tokens=512,  # Adjust based on how long you want the answer to be
            temperature=0.7,     # Lower = more deterministic, Higher = more creative
            top_p=0.9,
            do_sample=True,
            pad_token_id=tokenizer.eos_token_id
        )
    
    # Slice the output to only return the newly generated text (ignoring the prompt)
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    
    # Decode back to text
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response

# --- Test the model ---
if __name__ == "__main__":
    test_input = "How to Dry Wet Canon PowerShot SD850 IS Camera Components"
    
    print("\n--- Inference Test ---")
    print(f"User: {test_input}")
    print("Generating...")
    
    output = generate_answer(test_input)
    print(f"\nModel Output:\n{output}")