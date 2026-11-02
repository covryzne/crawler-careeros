from browser_use import Agent, ChatBrowserUse, ChatGoogle
from pydantic import BaseModel
from .config import Settings


def create_llm(settings: Settings):
    return ChatGoogle(model=settings.google_model) if settings.provider == "google" else ChatBrowserUse()


def create_agent(task: str, settings: Settings, schema: type[BaseModel]) -> Agent:
    return Agent(task=task, llm=create_llm(settings), output_model_schema=schema)


def parse_output(history, schema: type[BaseModel]):
    structured = getattr(history, "structured_output", None)
    if structured is not None:
        return schema.model_validate(structured)
    raw = history.final_result()
    if not raw:
        raise ValueError("Agent returned no final result")
    return schema.model_validate_json(raw)


def history_debug(history):
    return {
        "done": history.is_done(),
        "successful": history.is_successful(),
        "steps": history.number_of_steps(),
        "visited_urls": history.urls(),
        "action_names": history.action_names(),
        "errors": [str(x) for x in history.errors() if x],
        "final_result": history.final_result(),
    }
