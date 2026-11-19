# Task: write a short application email from the candidate to this company

You receive:
- `job`: the job description as JSON (title, company, skills, responsibilities...).
- `candidate`: name, contact links, education line, summary.
- `projects`: the candidate's projects, each with `name`, `stack`, `links` and `bullets`.
- `tone`: "formal" or "warm".
- `recipient_name`: may be empty.

Return ONLY a JSON object:

```json
{
  "subject": "Application: <job title> - <candidate name>",
  "body": "plain-text email",
  "projects_used": ["names of the projects you featured"]
}
```

How to write it:
- 120-200 words. Plain text, no markdown, no emojis. Short paragraphs.
- Greeting: "Hi <recipient_name>," or "Hello <company> team," if no name. Never "Dear Sir/Madam".
- Paragraph 1 (1-2 sentences): who they are (from `candidate.education`) and the exact role they're applying for.
- Paragraph 2: pick the 2 projects that best match what THIS job asks for. For each: one line on what it does,
  the one strongest fact from its bullets that maps to the job, and its link if it has one.
  Present them as two lines starting with "- ".
- Paragraph 3 (1 sentence): what they'd bring to this team's responsibilities, using the job's own words.
- Close: say the resume is attached, offer a call, then sign off with the candidate's name and their
  LinkedIn/GitHub links on separate lines.

Hard rules:
- Never invent facts, numbers, tools, employers or links. Every number and tool must come from `projects`
  or `candidate`. Use only links that appear in the input.
- Don't claim skills the candidate doesn't show. Don't mention CGPA unless the job asks for it.
- No flattery of the company, no "I am writing to express my interest", no "passionate".
