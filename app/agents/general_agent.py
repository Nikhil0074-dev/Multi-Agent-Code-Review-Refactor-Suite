from app.agents.base import BaseAgent


class GeneralAgent(BaseAgent):
    """Single-agent baseline used for comparison experiments."""

    name = "general"
    prompt_name = "general.md"
