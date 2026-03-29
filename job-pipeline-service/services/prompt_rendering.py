import re

from models import JobApplication, JobPosting, PromptLibrary


PLACEHOLDER_PATTERNS = {
    "job_id": re.compile(r"{{\s*job_id\s*}}"),
    "resume": re.compile(r"{{\s*resume\s*}}"),
    "description": re.compile(r"{{\s*description\s*}}"),
}


def render_user_prompt(job: JobPosting, prompt: PromptLibrary) -> str:
    rendered = str(prompt.user_prompt_template or "")
    replacements = {
        "job_id": job.job_id or "",
        # Resume content is moving to the Resume model. Until scoring is fully
        # application-based, keep {{resume}} working by sourcing generic prompt
        # context when present.
        "resume": prompt.context or "",
        "description": job.description or "",
    }

    for key, pattern in PLACEHOLDER_PATTERNS.items():
        rendered = pattern.sub(str(replacements[key]), rendered)

    return rendered


def render_application_prompt(application: JobApplication, prompt: PromptLibrary) -> str:
    rendered = str(prompt.user_prompt_template or "")
    posting = application.job_posting
    resume = application.resume
    replacements = {
        "job_id": posting.job_id or "",
        "resume": resume.content or "",
        "description": posting.description or "",
    }

    for key, pattern in PLACEHOLDER_PATTERNS.items():
        rendered = pattern.sub(str(replacements[key]), rendered)

    return rendered
