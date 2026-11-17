# Task: extract a job description into JSON

You receive the raw text of one job posting. Return ONLY a JSON object with exactly these keys.
Use null or [] when the posting does not say. Never guess facts that are not in the text.

```json
{
  "title": "string, role title as written",
  "company": "string or null",
  "location": "string or null (city, country)",
  "work_mode": "onsite | hybrid | remote | unknown",
  "employment_type": "internship | full-time | contract | ... or null",
  "seniority": "intern | entry | junior | mid | senior | null",
  "duration": "string or null, e.g. '6 months'",
  "stipend_or_salary": "string or null, exactly as written",
  "eligibility": ["batch year, degree, branch, CGPA, location rules ..."],
  "responsibilities": ["short phrases, max 8"],
  "hard_skills": [
    {"name": "canonical skill, e.g. 'PyTorch'", "importance": "must | nice",
     "aliases": ["other spellings an ATS might match, e.g. 'torch'"]}
  ],
  "soft_skills": ["communication", "..."],
  "keywords": ["other exact phrases a recruiter would search, e.g. 'computer vision', 'A/B testing'"],
  "deadline": "string or null",
  "apply_email": "email address in the posting or null",
  "red_flags": ["fees, unpaid, vague role, unrealistic asks ... only if present"],
  "interview_focus": ["topics the candidate should prepare, inferred only from the posting"]
}
```

Rules
- `importance` is "must" when the posting says required/must/minimum qualifications, otherwise "nice".
- Keep skill names short and canonical (e.g. "Kubernetes", not "experience working with Kubernetes clusters").
- At most 25 hard_skills and 20 keywords.
