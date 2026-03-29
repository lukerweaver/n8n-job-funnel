from datetime import datetime, timezone

from models import JobApplication, JobPosting, PromptLibrary, Resume, ScoreRun, ScoreRunItem, User


def seed_job(session, *, job_id="job-1", status="new", description="Role details", source="linkedin") -> JobPosting:
    job = JobPosting(
        job_id=job_id,
        source=source,
        status=status,
        company_name="Acme",
        title="PM",
        description=description,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
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


def seed_score_run(session, *, job: JobPosting, status="queued") -> ScoreRun:
    run = ScoreRun(
        status=status,
        requested_status="new",
        requested_source=None,
        prompt_key=None,
        force=False,
        selected_count=1,
    )
    session.add(run)
    session.flush()
    session.add(ScoreRunItem(score_run_id=run.id, job_posting_id=job.id, status="queued"))
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


def seed_resume(session, *, user: User, name="Resume", prompt_key="default", content="Resume Content") -> Resume:
    resume = Resume(
        user_id=user.id,
        name=name,
        prompt_key=prompt_key,
        classification_key=prompt_key,
        content=content,
        is_active=True,
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
) -> JobApplication:
    application = JobApplication(
        user_id=user.id,
        job_posting_id=job.id,
        resume_id=resume.id,
        status=status,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    session.add(application)
    session.commit()
    session.refresh(application)
    return application
