from models import PromptLibrary
from services.classification_service import classify_job
from services.llm_client import LlmClient
from services.settings_service import get_or_create_app_settings
from tests.helpers import seed_job


class FakeClient(LlmClient):
    def __init__(self, response: str):
        super().__init__(provider="fake", model="fake-model")
        self._response = response
        self.system_prompt: str | None = None
        self.user_prompt: str | None = None

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        self.system_prompt = system_prompt
        self.user_prompt = user_prompt
        return self._response


def test_classify_job_uses_target_roles_as_classification_keys(db_session):
    job = seed_job(db_session, description="Product marketing growth role")
    prompt = PromptLibrary(
        prompt_key="default",
        prompt_type="classification",
        prompt_version=1,
        system_prompt="Classify this job.",
        user_prompt_template="Job: {{job.description}}",
        is_active=True,
    )
    db_session.add(prompt)
    settings = get_or_create_app_settings(db_session)
    settings.target_roles = ["Product Marketing", "Growth"]
    db_session.commit()
    client = FakeClient('{"classification_key":"Product Marketing"}')

    result = classify_job(db_session, job, prompt=prompt, client=client)

    assert result.outcome == "classified"
    assert job.classification_key == "Product Marketing"
    assert client.system_prompt is not None
    assert "Product Marketing | Growth | Other" in client.system_prompt
