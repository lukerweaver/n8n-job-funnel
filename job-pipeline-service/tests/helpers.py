from datetime import datetime, timezone

from models import JobApplication, JobPosting, PromptLibrary, Resume, Run, RunItem, User


def seed_job(
    session,
    *,
    job_id="job-1",
    description="Role details",
    source="linkedin",
    created_at=None,
) -> JobPosting:
    created_at = created_at or datetime.now(timezone.utc)
    job = JobPosting(
        job_id=job_id,
        source=source,
        company_name="Acme",
        title="PM",
        description=description,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def seed_prompt(session, *, key="default", version=1, active=True) -> PromptLibrary:
    prompt = PromptLibrary(
        prompt_key=key,
        prompt_type="scoring",
        prompt_version=version,
        system_prompt="System",
        user_prompt_template="User {{job.description}}",
        context="Resume",
        is_active=active,
    )
    session.add(prompt)
    session.commit()
    session.refresh(prompt)
    return prompt


def seed_score_run(session, *, job: JobPosting, status="queued") -> Run:
    run = Run(
        status=status,
        requested_status="new",
        requested_source=None,
        classification_key=None,
        prompt_key=None,
        force=False,
        selected_count=1,
    )
    session.add(run)
    session.flush()
    session.add(RunItem(run_id=run.id, job_posting_id=job.id, status="queued"))
    session.commit()
    session.refresh(run)
    return run


def seed_user(session, *, name="User", email="user@example.com") -> User:
    user = User(
        name=name,
        email=email,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def seed_resume(
    session,
    *,
    user: User,
    name="Resume",
    prompt_key="default",
    classification_key=None,
    content="Resume Content",
    is_default=False,
) -> Resume:
    resume = Resume(
        user_id=user.id,
        name=name,
        prompt_key=prompt_key,
        classification_key=prompt_key if classification_key is None else classification_key,
        content=content,
        is_active=True,
        is_default=is_default,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(resume)
    session.commit()
    session.refresh(resume)
    return resume


def seed_application(
    session,
    *,
    user: User,
    job: JobPosting,
    resume: Resume,
    status="new",
    score=None,
    created_at=None,
    scored_at=None,
) -> JobApplication:
    created_at = created_at or datetime.now(timezone.utc)
    application = JobApplication(
        user_id=user.id,
        job_posting_id=job.id,
        resume_id=resume.id,
        status=status,
        score=score,
        scored_at=scored_at,
        created_at=created_at,
        updated_at=created_at,
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application
