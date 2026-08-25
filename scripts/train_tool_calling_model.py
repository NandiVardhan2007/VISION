"""
VISION Custom Tool-Calling Fine-Tuning Pipeline.
Trains LLaMA-3.1-8B-Instruct or Qwen-2.5-7B/14B-Instruct using QLoRA / PEFT SFTTrainer
on VISION's 159-tool function calling dataset.

Supports:
- HuggingFace PEFT QLoRA 4-bit
- FlashAttention-2 & Gradient Checkpointing
- Completion-only loss via DataCollatorForCompletionOnlyLM when the tokenizer's
  chat template is supported; falls back to full-sequence loss otherwise.
- Automatic export of the final LoRA adapter + tokenizer for GGUF conversion.
"""

import os
import sys
import json
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATASETS_DIR = PROJECT_ROOT / "data" / "datasets"
OUTPUT_DIR = PROJECT_ROOT / "data" / "models" / "vision-tool-calling-qlora"


def parse_args():
    parser = argparse.ArgumentParser(description="Train VISION Function Calling LLM")
    parser.add_argument("--base_model", type=str, default="Qwen/Qwen2.5-7B-Instruct",
                        help="Base model: Qwen/Qwen2.5-7B-Instruct, meta-llama/Llama-3.1-8B-Instruct, etc.")
    parser.add_argument("--train_file", type=str, default=str(DATASETS_DIR / "train_tool_calls.jsonl"))
    parser.add_argument("--val_file", type=str, default=str(DATASETS_DIR / "val_tool_calls.jsonl"))
    parser.add_argument("--output_dir", type=str, default=str(OUTPUT_DIR))
    parser.add_argument("--batch_size", type=int, default=4)
    parser.add_argument("--grad_accum_steps", type=int, default=4)
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--lora_rank", type=int, default=16)
    parser.add_argument("--lora_alpha", type=int, default=32)
    parser.add_argument("--max_seq_length", type=int, default=2048)
    return parser.parse_args()


def load_dataset_records(filepath: str) -> List[Dict[str, Any]]:
    records = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line.strip()))
    return records


def format_conversations_for_tokenizer(
    records: List[Dict[str, Any]],
    tokenizer: Any,
    max_seq_length: int = 2048,
) -> Tuple[List[Dict[str, str]], Optional[Any]]:
    """
    Formats OpenAI-style tool calls into the tokenizer's chat template.

    Returns (formatted_records, response_template_collator_or_None).
    When completion-only masking is available the collator computes loss on
    assistant responses/tool calls only; otherwise full-sequence loss is used
    and the caller should say so.
    """
    formatted = []
    collator = None

    # Locate the end-of-assistant-turn marker in the rendered template so we can
    # mask everything before it (completion-only loss).
    response_template = None
    try:
        probe = tokenizer.apply_chat_template(
            [{"role": "assistant", "content": "x"}],
            tokenize=False,
            add_generation_prompt=False,
        )
        if isinstance(probe, str) and probe:
            marker = "x" + (tokenizer.eos_token or "")
            if marker in probe:
                response_template = probe.split("x")[0].rsplit("\n", 1)[0] + "\n"
    except Exception:
        response_template = None

    use_masking = False
    if response_template:
        try:
            from trl import DataCollatorForCompletionOnlyLM
            collator = DataCollatorForCompletionOnlyLM(
                response_template=response_template,
                tokenizer=tokenizer,
            )
            use_masking = True
        except Exception:
            collator = None

    for rec in records:
        messages = rec.get("messages", [])
        tools = rec.get("tools", [])

        text = None
        try:
            if hasattr(tokenizer, "apply_chat_template"):
                text = tokenizer.apply_chat_template(
                    conversation=messages,
                    tools=tools if tools else None,
                    tokenize=False,
                    add_generation_prompt=False,
                )
        except Exception:
            text = None

        if not text:
            # Fallback ChatML formatter (matches Qwen/ChatML conventions closely
            # enough that DataCollatorForCompletionOnlyLM still finds the marker).
            parts = []
            for m in messages:
                role = m.get("role")
                content = m.get("content") or ""
                tcalls = m.get("tool_calls")
                if tcalls:
                    content += f"\n<tool_call>\n{json.dumps(tcalls)}\n</tool_call>"
                parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
            text = "\n".join(parts) + "\n"

        formatted.append({"text": text})

    if not use_masking:
        print("[!] Completion-only loss unavailable for this tokenizer template; "
              "falling back to full-sequence loss.")

    return formatted, collator


def train_hf_peft(args):
    print("==================================================")
    print(f"  Training Base Model: {args.base_model}")
    print(f"  Dataset: {args.train_file}")
    print(f"  Output:  {args.output_dir}")
    print("==================================================")

    try:
        import torch
        import transformers
        from transformers import (
            AutoModelForCausalLM,
            AutoTokenizer,
            BitsAndBytesConfig,
            TrainingArguments,
        )
        from datasets import Dataset
    except ImportError as e:
        print(f"\n[!] Required fine-tuning packages missing: {e}")
        print("[!] To install training dependencies on a GPU machine, run:")
        print("    pip install torch transformers peft trl bitsandbytes datasets accelerate")
        print("\n[*] You can also run this script directly on Google Colab / RunPod / Vast.ai.")
        return

    from packaging.version import Version
    transformers_version = Version(transformers.__version__)

    # 1. 4-bit Quantization Config
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    print("[*] Loading tokenizer & base model in 4-bit NF4...")
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model_kwargs: Dict[str, Any] = dict(
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(args.base_model, **model_kwargs)

    # 2. LoRA Adapter Config — applied once, via SFTTrainer's peft_config so we
    # never double-wrap the model.
    from peft import LoraConfig

    peft_config = LoraConfig(
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"],
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
    )

    # 3. Load & Format Datasets
    print("[*] Preparing conversational datasets...")
    train_records = load_dataset_records(args.train_file)
    val_records = load_dataset_records(args.val_file)

    train_data, collator = format_conversations_for_tokenizer(
        train_records, tokenizer, args.max_seq_length
    )
    val_data, _ = format_conversations_for_tokenizer(
        val_records, tokenizer, args.max_seq_length
    )
    if collator is None:
        print("[!] WARNING: loss is computed over the FULL sequence (system+user "
              "included), which dilutes the tool-call signal. Consider a chat-"
              "template that supports completion-only masking.")

    train_ds = Dataset.from_list(train_data)
    val_ds = Dataset.from_list(val_data)

    # 4. Training Arguments (compatible with both old and new transformers APIs)
    ta_kwargs: Dict[str, Any] = dict(
        output_dir=args.output_dir,
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.grad_accum_steps,
        learning_rate=args.lr,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        num_train_epochs=args.epochs,
        logging_steps=10,
        save_strategy="steps",
        save_steps=100,
        save_total_limit=2,
        fp16=not torch.cuda.is_bf16_supported(),
        bf16=torch.cuda.is_bf16_supported(),
        optim="paged_adamw_8bit",
        report_to="none",
    )
    eval_kwargs: Dict[str, Any] = {}
    if transformers_version >= Version("4.46"):
        ta_kwargs["eval_strategy"] = "steps"
        ta_kwargs["eval_steps"] = 50
    else:
        ta_kwargs["evaluation_strategy"] = "steps"
        ta_kwargs["eval_steps"] = 50
    training_args = TrainingArguments(**ta_kwargs)

    # 5. Trainer — SFTTrainer API differs across trl versions
    from trl import SFTTrainer

    sft_extra: Dict[str, Any] = {}
    try:
        # trl >= 0.13-ish: config object carries dataset/tokenizer settings
        from trl import SFTConfig
        sft_config_kwargs = dict(
            dataset_text_field="text",
            max_seq_length=args.max_seq_length,
            **ta_kwargs,
            **eval_kwargs,
        )
        sft_config = SFTConfig(**sft_config_kwargs)
        trainer = SFTTrainer(
            model=model,
            args=sft_config,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            peft_config=peft_config,
            data_collator=collator,
            processing_class=tokenizer,
        )
    except (ImportError, TypeError):
        # Legacy trl: keyword constructor
        trainer = SFTTrainer(
            model=model,
            args=training_args,
            train_dataset=train_ds,
            eval_dataset=val_ds,
            peft_config=peft_config,
            dataset_text_field="text",
            max_seq_length=args.max_seq_length,
            tokenizer=tokenizer,
            data_collator=collator,
        )

    print(f"[*] Launching fine-tuning training loop "
          f"(completion-only loss: {'yes' if collator else 'NO - full sequence'})...")
    trainer.train()

    print(f"[OK] Training complete. Saving final LoRA adapter to {args.output_dir}...")
    trainer.model.save_pretrained(args.output_dir)
    tokenizer.save_pretrained(args.output_dir)
    print("==================================================")
    print("  Model Successfully Fine-Tuned for VISION Tools  ")
    print("==================================================")


def main():
    args = parse_args()
    train_hf_peft(args)


if __name__ == "__main__":
    main()
