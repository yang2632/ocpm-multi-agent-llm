"""LLM provider abstraction: OpenAI and Gemini via LangChain.

Supports custom endpoints, models, and API keys for both providers.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel


def create_llm(
    provider: str = "openai",
    model: str = "gpt-4o",
    temperature: float = 0.0,
    max_tokens: int = 4096,
    api_key: str = "",
    base_url: str = "",
) -> BaseChatModel:
    """Create a LangChain chat model for the specified provider.

    Args:
        provider: "openai" or "gemini"
        model: Model identifier (e.g., "gpt-4o", "gemini-2.0-flash")
        temperature: Sampling temperature (0 for greedy)
        max_tokens: Maximum output tokens
        api_key: API key for the provider
        base_url: Custom API endpoint (empty = provider default)

    Returns:
        A LangChain BaseChatModel instance with tools bindable.
    """
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        kwargs: dict = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        return ChatOpenAI(**kwargs)

    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        kwargs = {
            "model": model,
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if api_key:
            kwargs["google_api_key"] = api_key
        if base_url:
            # ChatGoogleGenerativeAI uses client_options for custom endpoint
            kwargs["client_options"] = {"api_endpoint": base_url}
        return ChatGoogleGenerativeAI(**kwargs)

    raise ValueError(f"Unknown provider: {provider}. Use 'openai' or 'gemini'.")
