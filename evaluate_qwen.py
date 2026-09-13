"""
Evaluation harness for Qwen2.5 + MyFixit knowledge-graph RAG.

Changes from the original, in rough order of impact on the scores:

  1. Answer-length control. Gold answers average ~18 words. Unconstrained
     generation wraps a correct answer in preamble + caveats + step recap,
     which crushes ROUGE/BLEU/F1 precision even when the content is right.
     A correct answer with that boilerplate scores RL ~0.36; the answer alone
     scores 1.00. Fixed via terse system prompt, few-shot exemplars, a stop
     criterion, output cleanup, and max_new_tokens=64.
  2. Few-shot exemplars in the target register, drawn from guides that are NOT
     in the test suite (no contamination).
  3. Single system message. Two system turns is non-standard; how the second
     one is rendered depends on the chat template version, and your KG context
     was in it. Context now goes in the user turn where it is unambiguous.
  4. token_f1 fixed. The original used set() on both sides and raw .split(),
     so punctuation ("bracket." != "bracket") and repeated tokens were
     mis-scored. Now SQuAD-style: normalize, then multiset overlap.
  5. spec_recall added. For this corpus the answer usually IS a number+unit
     (four T8 screws, 29 ft-lb, 385F). This measures whether the model got the
     specs right, independent of phrasing. Use it as the headline number.
  6. Context compression by question relevance, so the answer is not buried.
  7. Error isolation + resumable JSONL. One bad guide no longer zeroes the run.
  8. Batched left-padded generation + SDPA attention to cut the ~20s/query.
  9. Oracle vs query retrieval modes, so retrieval and generation are
     measured separately rather than conflated.

Usage:
    python evaluate_qwen.py                  # oracle retrieval (generation ceiling)
    python evaluate_qwen.py --mode query     # end-to-end, needs query_retrieve_fn
"""

import argparse
import json
import re
import string
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import torch
from rouge_score import rouge_scorer
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from transformers import AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList

from build_kg import extract_and_build_kg
from graph_retriever import FixitGraphRetriever


# ======================================================================
# 1. Answer normalization and metrics
# ======================================================================

_ARTICLES = {"a", "an", "the"}
_PUNCT = str.maketrans("", "", string.punctuation)

_NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
    "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
    "hundred": 100, "thousand": 1000,
}


def normalize_answer(s: str) -> str:
    """SQuAD-style normalization: lowercase, strip punctuation and articles,
    collapse whitespace. Without this, 'bracket.' and 'bracket' score as a
    miss, which is what opened the gap between your token_f1 and rouge1."""
    s = s.lower()
    s = s.translate(_PUNCT)
    s = " ".join(w for w in s.split() if w not in _ARTICLES)
    return s


def token_f1(pred: str, ref: str) -> float:
    """Multiset (not set) overlap, so repeated tokens count correctly."""
    p = normalize_answer(pred).split()
    r = normalize_answer(ref).split()
    if not p or not r:
        return float(p == r)
    common = Counter(p) & Counter(r)
    n = sum(common.values())
    if n == 0:
        return 0.0
    precision, recall = n / len(p), n / len(r)
    return 2 * precision * recall / (precision + recall)


def extract_specs(text: str) -> set:
    """Pull out the numbers that carry the answer: 4, 4.8, 21, 1/16, 55.4,
    plus spelled-out forms so 'Four' and '4' unify."""
    t = text.lower()
    specs = set()

    for frac in re.findall(r"\b(\d+)\s*/\s*(\d+)\b", t):
        num, den = int(frac[0]), int(frac[1])
        if den:
            specs.add(round(num / den, 4))

    t_nofrac = re.sub(r"\b\d+\s*/\s*\d+\b", " ", t)
    for m in re.findall(r"\b\d+(?:\.\d+)?\b", t_nofrac):
        specs.add(round(float(m), 4))

    for w, v in _NUM_WORDS.items():
        if re.search(rf"\b{w}\b", t):
            specs.add(float(v))

    return specs


def spec_recall(pred: str, ref: str) -> Optional[float]:
    """Fraction of the gold answer's numeric specs that appear in the
    prediction. Returns None when the gold answer has no numbers, so those
    items are excluded rather than scored as 0."""
    gold = extract_specs(ref)
    if not gold:
        return None
    got = extract_specs(pred)
    return len(gold & got) / len(gold)


def compute_metrics(preds: List[str], refs: List[str], gen_lat: List[float],
                    ret_lat: List[float]) -> Dict[str, Any]:
    scorer = rouge_scorer.RougeScorer(["rouge1", "rouge2", "rougeL"], use_stemmer=True)
    smooth = SmoothingFunction().method1

    r1, r2, rl, bleu, f1, em, specs = [], [], [], [], [], [], []

    for p, g in zip(preds, refs):
        pn, gn = normalize_answer(p), normalize_answer(g)
        em.append(1.0 if pn == gn else 0.0)

        s = scorer.score(g.lower(), p.lower())
        r1.append(s["rouge1"].fmeasure)
        r2.append(s["rouge2"].fmeasure)
        rl.append(s["rougeL"].fmeasure)

        bleu.append(sentence_bleu([gn.split()], pn.split(), smoothing_function=smooth)
                    if pn.split() else 0.0)
        f1.append(token_f1(p, g))

        sr = spec_recall(p, g)
        if sr is not None:
            specs.append(sr)

    out = {
        "spec_recall": float(np.mean(specs)) if specs else None,
        "spec_recall_n": len(specs),
        "token_f1": float(np.mean(f1)),
        "rouge1": float(np.mean(r1)),
        "rouge2": float(np.mean(r2)),
        "rougeL": float(np.mean(rl)),
        "bleu": float(np.mean(bleu)),
        "exact_match": float(np.mean(em)),
        "avg_generation_seconds": float(np.mean(gen_lat)) if gen_lat else 0.0,
        "avg_retrieval_seconds": float(np.mean(ret_lat)) if ret_lat else 0.0,
        "mean_pred_words": float(np.mean([len(p.split()) for p in preds])) if preds else 0.0,
        "mean_gold_words": float(np.mean([len(g.split()) for g in refs])) if refs else 0.0,
        "total_scored": len(preds),
    }
    return out


# ======================================================================
# 2. Prompt construction
# ======================================================================

SYSTEM_PROMPT = (
    "You are a technical assistant for device repair guides.\n"
    "Answer ONLY from the provided context.\n"
    "Rules:\n"
    "- Reply with ONE short sentence, 25 words maximum.\n"
    "- Give only the specific fact asked for. Copy exact numbers, sizes, "
    "screw types, torques and units from the context.\n"
    "- No preamble. Never begin with 'Based on', 'According to' or 'The answer is'.\n"
    "- Do not list the repair steps. Do not add safety warnings or caveats.\n"
    "- If the context does not contain the answer, reply exactly: INSUFFICIENT CONTEXT"
)

# Exemplars are drawn from guides 7, 1402 and 36823, none of which appear in
# the 50-question test suite. They teach register and length, not content.
FEW_SHOT = [
    (
        "Guide: PowerBook G3 Wallstreet Modem Replacement\n"
        "Step 6: Remove the two Phillips screws from the heat shield. One screw is "
        "shorter than the other. When putting the Wallstreet back together, this "
        "screw goes in the middle of the heat shield.",
        "How many Phillips screws hold the heat shield, and where does the shorter one go?",
        "Two Phillips screws, and the shorter one goes in the middle of the heat shield.",
    ),
    (
        "Guide: PlayStation 2 Power Board Replacement\n"
        "Step 0: Use the flat edge of a metal spudger to pry the eight flat screw "
        "covers out. Remove the following eight screws securing the top cover to the "
        "bottom case: Four 55.4 mm Philips screws Four 18.0 mm Phillips screws",
        "Which screws secure the top cover to the bottom case on a PlayStation 2?",
        "Eight Phillips screws: four 55.4 mm and four 18.0 mm.",
    ),
    (
        "Guide: Nikon Coolpix L610 Camera Lens Replacement\n"
        "Step 8: Remove the 6 (3.70 mm) screws on the metal cover. Two of those screws "
        "are covered by black plastic covers. Be careful of the red and black wires on "
        "the top. If the flash is charged you could get a mild shock.",
        "Why be careful of the red and black wires under the metal cover?",
        "If the flash is charged you could get a mild shock.",
    ),
]


def compress_context(context: str, question: str, max_chars: int = 6000,
                     head_lines: int = 2) -> str:
    """Keep the header lines and the question-relevant lines, in original order.
    A no-op when the context already fits. Long undifferentiated subgraph dumps
    bury the one line that answers the question."""
    context = (context or "").strip()
    if len(context) <= max_chars:
        return context

    lines = context.split("\n")
    head, body = lines[:head_lines], lines[head_lines:]

    q_terms = {w for w in normalize_answer(question).split() if len(w) > 2}
    scored = []
    for i, line in enumerate(body):
        terms = set(normalize_answer(line).split())
        overlap = len(q_terms & terms) / (len(q_terms) or 1)
        scored.append((overlap, i, line))

    scored.sort(key=lambda x: -x[0])
    budget = max_chars - sum(len(l) + 1 for l in head)
    keep, used = [], 0
    for _, i, line in scored:
        if used + len(line) + 1 > budget:
            continue
        keep.append((i, line))
        used += len(line) + 1

    keep.sort(key=lambda x: x[0])
    return "\n".join(head + [l for _, l in keep])


def build_messages(question: str, kg_context: str) -> List[Dict[str, str]]:
    """One system message. Few-shot as real conversation turns, which the chat
    template handles correctly, rather than pasted into the system prompt."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ctx, q, a in FEW_SHOT:
        messages.append({"role": "user", "content": f"Context:\n{ctx}\n\nQuestion: {q}"})
        messages.append({"role": "assistant", "content": a})
    messages.append({"role": "user", "content": f"Context:\n{kg_context}\n\nQuestion: {question}"})
    return messages


# ======================================================================
# 3. Output cleanup
# ======================================================================

_PREAMBLE = re.compile(
    r"^\s*(?:based on|according to|per|from)\b[^.,]{0,80}[.,]\s*|"
    r"^\s*(?:the\s+)?answer\s*(?:is)?\s*:\s*|"
    r"^\s*(?:sure|certainly|of course)[,!]\s*",
    re.IGNORECASE,
)


def clean_prediction(text: str) -> str:
    """Strip boilerplate the model adds despite instructions. Each of these
    costs real precision: see the verbosity table in the README."""
    t = (text or "").strip()
    t = t.split("\n\n")[0].strip()          # drop trailing step lists / notes
    prev = None
    while prev != t:                         # preambles can stack
        prev = t
        t = _PREAMBLE.sub("", t).strip()
    t = t.strip('"').strip()
    # drop a trailing offer-to-help sentence
    t = re.sub(r"\s*(let me know|if you (need|have)|hope this helps)\b.*$", "", t,
               flags=re.IGNORECASE).strip()
    return t


class StopOnNewline(StoppingCriteria):
    """Halt at the first blank line. Saves tokens and prevents step recaps."""

    def __init__(self, tokenizer, prompt_len: int):
        self.tok = tokenizer
        self.prompt_len = prompt_len

    def __call__(self, input_ids, scores, **kwargs) -> bool:
        for row in input_ids:
            text = self.tok.decode(row[self.prompt_len:], skip_special_tokens=True)
            if "\n\n" not in text:
                return False
        return True


# ======================================================================
# 4. Generation
# ======================================================================

def make_generate_fn(model, tokenizer, max_new_tokens: int = 64, batch_size: int = 8
                     ) -> Callable[[List[List[Dict[str, str]]]], List[str]]:
    """Batched, left-padded, greedy. Set batch_size=1 for bit-exact
    reproducibility; higher values trade a little numerical drift for a large
    wall-clock win."""

    def generate(batch_messages: List[List[Dict[str, str]]]) -> List[str]:
        outputs: List[str] = []
        for i in range(0, len(batch_messages), batch_size):
            chunk = batch_messages[i:i + batch_size]
            texts = [
                tokenizer.apply_chat_template(m, tokenize=False, add_generation_prompt=True)
                for m in chunk
            ]
            enc = tokenizer(texts, return_tensors="pt", padding=True).to(model.device)
            prompt_len = enc.input_ids.shape[1]

            with torch.inference_mode():
                out = model.generate(
                    **enc,
                    max_new_tokens=max_new_tokens,
                    do_sample=False,              # greedy; no temperature/top_p
                    num_beams=1,
                    repetition_penalty=1.0,
                    pad_token_id=tokenizer.pad_token_id,
                    eos_token_id=tokenizer.eos_token_id,
                    stopping_criteria=StoppingCriteriaList(
                        [StopOnNewline(tokenizer, prompt_len)]),
                )

            for row in out:
                text = tokenizer.decode(row[prompt_len:], skip_special_tokens=True)
                outputs.append(clean_prediction(text))
        return outputs

    return generate


# ======================================================================
# 5. Evaluation loop
# ======================================================================

def run_eval(test_suite, retriever, generate_fn, mode="oracle",
             query_retrieve_fn=None, out_path="eval_records.jsonl",
             resume=True, max_context_chars=6000) -> List[Dict[str, Any]]:

    if mode == "query" and query_retrieve_fn is None:
        raise ValueError('mode="query" requires query_retrieve_fn. In oracle mode the '
                         'retriever is handed the gold guide title, so the result is a '
                         'generation ceiling, not retrieval accuracy.')

    out_path = Path(out_path)
    done = set()
    if resume and out_path.exists():
        for line in out_path.open():
            try:
                done.add(json.loads(line)["question"])
            except (json.JSONDecodeError, KeyError):
                continue
        if done:
            print(f"Resuming: {len(done)} records already in {out_path}")

    pending = [it for it in test_suite if it["question"] not in done]
    records: List[Dict[str, Any]] = []

    # --- retrieval pass (cheap, do it up front so generation can batch) ---
    print(f"Retrieving context for {len(pending)} questions (mode={mode})...")
    prepared = []
    for item in pending:
        rec = {
            "guide_target": item["guide_target"],
            "question": item["question"],
            "ground_truth": item["ground_truth"],
            "mode": mode,
            "error": None,
        }
        try:
            t0 = time.perf_counter()
            if mode == "oracle":
                ctx = retriever.retrieve_guide_subgraph_context(item["guide_target"])
            else:
                ctx = query_retrieve_fn(item["question"])
            rec["retrieval_seconds"] = time.perf_counter() - t0

            ctx = (ctx or "").strip()
            rec["retrieval_hit"] = (
                None if mode == "oracle"
                else item["guide_target"].lower() in ctx.lower()
            )
            ctx = compress_context(ctx, item["question"], max_chars=max_context_chars)
            rec["context_chars"] = len(ctx)
            rec["context_empty"] = not ctx
            prepared.append((rec, ctx))
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["prediction"] = None
            traceback.print_exc()
            records.append(rec)
            with out_path.open("a") as f:
                f.write(json.dumps(rec) + "\n")

    # --- generation pass ---
    print(f"Generating {len(prepared)} answers...")
    for rec, ctx in prepared:
        try:
            t0 = time.perf_counter()
            pred = generate_fn([build_messages(rec["question"], ctx)])[0]
            rec["generation_seconds"] = time.perf_counter() - t0
            rec["prediction"] = pred
            rec["abstained"] = pred.upper().startswith("INSUFFICIENT CONTEXT")
            rec["pred_words"] = len(pred.split())
        except Exception as e:
            rec["error"] = f"{type(e).__name__}: {e}"
            rec["prediction"] = None
            traceback.print_exc()

        records.append(rec)
        with out_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")

        flag = "ERR " if rec["error"] else ("ABS " if rec.get("abstained") else "ok  ")
        print(f"  {flag} {rec.get('generation_seconds', 0):5.1f}s  "
              f"{rec['guide_target'][:46]}")
        if not rec["error"]:
            print(f"       pred: {rec['prediction'][:100]}")
            print(f"       gold: {rec['ground_truth'][:100]}")

    return records


def summarize(records, model_name, out_file="qwen2.5_test_metrics.json"):
    errors = [r for r in records if r["error"]]
    ok = [r for r in records if not r["error"]]
    empty = [r for r in ok if r.get("context_empty")]
    abstained = [r for r in ok if r.get("abstained")]
    scored = [r for r in ok if not r.get("abstained")]

    print("\n" + "=" * 52)
    print("            EVALUATION SUMMARY")
    print("=" * 52)
    print(f"  {'attempted':<26}{len(records)}")
    print(f"  {'errored':<26}{len(errors)}")
    print(f"  {'empty context':<26}{len(empty)}")
    print(f"  {'abstained':<26}{len(abstained)}")
    print(f"  {'scored':<26}{len(scored)}")

    if errors:
        kinds = Counter(r["error"].split(":")[0] for r in errors)
        print("\n  error types:")
        for k, v in kinds.most_common():
            print(f"    {k:<24}{v}")

    if records and records[0]["mode"] == "query":
        hits = sum(1 for r in ok if r.get("retrieval_hit"))
        print(f"\n  {'retrieval accuracy':<26}{hits}/{len(ok)} "
              f"({hits / max(len(ok), 1):.1%})")

    metrics = {}
    if scored:
        metrics = compute_metrics(
            [r["prediction"] for r in scored],
            [r["ground_truth"] for r in scored],
            [r.get("generation_seconds", 0.0) for r in scored],
            [r.get("retrieval_seconds", 0.0) for r in scored],
        )
        print()
        for k, v in metrics.items():
            if v is None:
                print(f"  {k:<26}n/a")
            elif isinstance(v, float):
                print(f"  {k:<26}{v:.4f}")
            else:
                print(f"  {k:<26}{v}")

        ratio = metrics["mean_pred_words"] / max(metrics["mean_gold_words"], 1e-9)
        if ratio > 2.0:
            print(f"\n  WARNING: predictions are {ratio:.1f}x longer than gold. "
                  "ROUGE/BLEU are being suppressed by verbosity rather than by "
                  "wrong content. Inspect the worst cases below.")

        worst = sorted(scored, key=lambda r: token_f1(r["prediction"], r["ground_truth"]))[:3]
        print("\n  lowest-scoring items:")
        for r in worst:
            print(f"    [{token_f1(r['prediction'], r['ground_truth']):.2f}] {r['guide_target'][:44]}")
            print(f"          pred: {r['prediction'][:90]}")
            print(f"          gold: {r['ground_truth'][:90]}")

    payload = {
        "model": model_name,
        "mode": records[0]["mode"] if records else None,
        "counts": {
            "attempted": len(records), "errored": len(errors),
            "empty_context": len(empty), "abstained": len(abstained),
            "scored": len(scored),
        },
        "metrics_summary": metrics,
        "detailed_predictions": records,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  saved -> {out_file}")
    return metrics


# ======================================================================
# 6. Main
# ======================================================================

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen2.5-7B-Instruct")
    ap.add_argument("--data-dir", default="./MyFixit-Dataset/jsons")
    ap.add_argument("--mode", choices=["oracle", "query"], default="oracle")
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--out", default="qwen2.5_test_metrics.json")
    ap.add_argument("--records", default="eval_records.jsonl")
    ap.add_argument("--no-resume", action="store_true")
    args = ap.parse_args()

    from golden_test_suite import test_suite

    print("Step 1: Building Knowledge Graph...")
    kg = extract_and_build_kg(args.data_dir)
    retriever = FixitGraphRetriever(kg)

    print(f"Step 2: Loading {args.model}...")
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    # Left padding is required for correct batched decoder-only generation.
    tokenizer.padding_side = "left"
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        device_map="auto",
        attn_implementation="sdpa",
        trust_remote_code=True,
    )
    model.eval()
    model.generation_config.temperature = None   # silence unused-flag warnings
    model.generation_config.top_p = None
    model.generation_config.top_k = None

    generate_fn = make_generate_fn(model, tokenizer,
                                   max_new_tokens=args.max_new_tokens,
                                   batch_size=args.batch_size)

    print("Step 3: Warmup...")
    try:
        generate_fn([build_messages("Warmup?", "Warmup context.")])
    except Exception:
        print("  warmup failed, continuing")

    print("Step 4: Running inference...")
    records = run_eval(
        test_suite, retriever, generate_fn,
        mode=args.mode,
        query_retrieve_fn=None,   # supply your production retrieval fn for --mode query
        out_path=args.records,
        resume=not args.no_resume,
    )

    print("\nStep 5: Computing metrics...")
    summarize(records, args.model, out_file=args.out)


if __name__ == "__main__":
    main()
