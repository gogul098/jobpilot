"""Spelling variants an ATS search would treat as the same skill. Extend freely."""
from __future__ import annotations

GROUPS = [
    ["machine learning", "ml"], ["deep learning", "dl"], ["artificial intelligence", "ai"],
    ["natural language processing", "nlp"], ["computer vision", "cv", "image segmentation", "object detection"],
    ["large language models", "large language model", "llm", "llms"],
    ["pytorch", "torch"], ["tensorflow", "tf", "keras"], ["scikit-learn", "sklearn", "scikit learn"],
    ["hugging face", "huggingface", "transformers"], ["javascript", "js"], ["typescript", "ts"],
    ["postgresql", "postgres"], ["kubernetes", "k8s"], ["amazon web services", "aws"],
    ["google cloud", "gcp", "google cloud platform"], ["microsoft azure", "azure"],
    ["ci/cd", "ci cd", "github actions", "continuous integration"], ["rest api", "rest apis", "restful"],
    ["fine-tuning", "fine tuning", "finetuning", "qlora", "lora", "peft"],
    ["retrieval augmented generation", "rag"], ["opencv", "open cv"], ["node.js", "nodejs", "node"],
    ["c++", "cpp"], ["golang", "go"], ["data structures", "dsa", "data structures and algorithms"],
    ["mlops", "ml ops"], ["fastapi", "fast api"], ["numpy", "np"], ["pandas", "pd"],
]
_INDEX: dict[str, list[str]] = {}
for g in GROUPS:
    for term in g:
        _INDEX[term] = g


def variants(name: str, aliases: list[str]) -> list[str]:
    out = {name.lower(), *[a.lower() for a in aliases]}
    for t in list(out):
        out.update(_INDEX.get(t, []))
    # very short aliases like "go"/"ts"/"cv" only count when they are the JD's own term
    return [v for v in out if len(v) > 2 or v == name.lower()]
