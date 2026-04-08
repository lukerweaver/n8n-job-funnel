from services.prompt_rendering import render_application_prompt, render_user_prompt
from tests.helpers import seed_application, seed_job, seed_prompt, seed_resume, seed_user


def test_render_user_prompt_treats_backslashes_as_literal_text(db_session):
    prompt = seed_prompt(
        db_session,
        key="classification-prompt",
    )
    prompt.prompt_type = "classification"
    prompt.user_prompt_template = "Classify this role:\n{{description}}"
    db_session.commit()

    job = seed_job(db_session, job_id="job-backslash", description=r"Windows path C:\Temp\Test and token \T")

    rendered = render_user_prompt(job, prompt)

    assert r"C:\Temp\Test" in rendered
    assert r"\T" in rendered


def test_render_application_prompt_treats_backslashes_as_literal_text(db_session):
    prompt = seed_prompt(db_session)
    prompt.user_prompt_template = "Resume:\n{{resume}}\n\nDescription:\n{{description}}"
    db_session.commit()

    user = seed_user(db_session)
    job = seed_job(db_session, description=r"JD with \T escape-looking text")
    resume = seed_resume(db_session, user=user, content=r"Resume mentions C:\Tools\Thing")
    application = seed_application(db_session, user=user, job=job, resume=resume)

    rendered = render_application_prompt(application, prompt)

    assert r"C:\Tools\Thing" in rendered
    assert r"\T" in rendered
