"""Single place to choose the LLM, so the whole project can switch providers with one setting."""

import os
from dotenv import load_dotenv

load_dotenv()


def get_llm(temperature: float = 0):
    """Return a chat model based on the LLM_PROVIDER setting in .env (default: groq)."""
    provider = os.getenv("LLM_PROVIDER", "groq")

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"), temperature=temperature)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5"), temperature=temperature)

    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
