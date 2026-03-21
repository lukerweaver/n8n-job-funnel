import re

from models import JobPosting, PromptLibrary


PLACEHOLDER_PATTERNS = {
    "job_id": re.compile(r"{{\s*job_id\s*}}"),
    "resume": re.compile(r"{{\s*resume\s*}}"),
    "description": re.compile(r"{{\s*description\s*}}"),
}


def render_user_prompt(job: JobPosting, prompt: PromptLibrary) -> str:
    rendered = str(prompt.user_prompt_template or "")
    replacements = {
        "job_id": job.job_id or "",
        "resume": prompt.base_resume_template or "",
        "description": job.description or "",
    }

    for key, pattern in PLACEHOLDER_PATTERNS.items():
        rendered = pattern.sub(str(replacements[key]), rendered)

    return rendered
