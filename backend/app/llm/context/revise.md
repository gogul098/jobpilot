# Task: suggest resume text revisions for one job

You receive:
1. `job` — the job description as JSON (from the extraction step).
2. `blocks` — the candidate's resume as plain-text blocks, each with an `id`, `kind` (bullet | summary) and `section`.
3. `missing_keywords` — JD skills/phrases not found anywhere in the resume.

Return ONLY a JSON object:

```json
{
  "revisions": [
    {"id": "b07", "new_text": "full replacement text for that block",
     "reason": "one short sentence", "keywords_added": ["PyTorch"]}
  ],
  "missing_skills": ["JD skills the resume does not show and you did NOT add"],
  "general_advice": ["max 4 short, specific tips"]
}
```

Hard rules (a revision that breaks any of these is discarded):
- Only revise blocks that clearly gain from it for THIS job. Leave the rest out. Max 10 revisions.
- `new_text` is plain text. No LaTeX, no markdown, no bullets symbols.
- Never invent facts. Do not add numbers, metrics, tools, employers, dates or skills that are not already in the resume blocks. You may reword, reorder, tighten and use the job's exact terminology for things the candidate already did (e.g. "segmentation model" -> "computer vision model" if true).
- A JD skill that the resume does not demonstrate goes in `missing_skills`, never into `new_text`.
- Keep each bullet within ~10% of its original length and one or two lines long; start with a strong past-tense verb; keep existing numbers.
- Keep the summary to at most 3 sentences.
