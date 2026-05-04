"""
LLM Factory — Config-driven model selection for each agent.

Priority order when agent model is set to "auto":
  1. Smart agents (diagnostic, repair): Google Gemini → AgentRouter → Groq
  2. Fast agents (validator, simulation, execution): Groq → Google → AgentRouter

Override per agent in .env:
  DIAGNOSTIC_MODEL=google:gemini-2.5-pro
  REPAIR_MODEL=agentrouter:claude-opus-4-6
  VALIDATOR_MODEL=groq:llama-3.3-70b-versatile
"""

import os
import logging
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# PROVIDER CONSTRUCTORS
# ═══════════════════════════════════════════════════════════

def _make_groq(model: str = "llama-3.3-70b-versatile", temperature: float = 0):
    from langchain_groq import ChatGroq
    return ChatGroq(model_name=model, temperature=temperature)


def _make_google(model: str = "gemini-2.5-pro", temperature: float = 0):
    from langchain_google_genai import ChatGoogleGenerativeAI
    return ChatGoogleGenerativeAI(
        model=model,
        temperature=temperature,
        google_api_key=os.getenv("GOOGLE_API_KEY"),
    )


def _make_agentrouter(model: str = "claude-opus-4-6", temperature: float = 0):
    from langchain_openai import ChatOpenAI
    key = os.getenv("AGENT_ROUTER_API_KEY")
    return ChatOpenAI(
        base_url="https://agentrouter.org/v1",
        api_key=key,
        model=model,
        temperature=temperature,
        default_headers={"Authorization": f"Bearer {key}"},
    )


# ═══════════════════════════════════════════════════════════
# AVAILABILITY CHECKS
# ═══════════════════════════════════════════════════════════

def _has_groq() -> bool:
    return bool(os.getenv("GROQ_API_KEY"))

def _has_google() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY"))

def _has_agentrouter() -> bool:
    return bool(os.getenv("AGENT_ROUTER_API_KEY"))


# ═══════════════════════════════════════════════════════════
# AUTO-SELECT LOGIC
# ═══════════════════════════════════════════════════════════

# Smart agents need best reasoning — prefer premium models
_SMART_PRIORITY = [
    ("google", "gemini-2.5-pro", _has_google, _make_google),
    ("agentrouter", "claude-opus-4-6", _has_agentrouter, _make_agentrouter),
    ("groq", "llama-3.3-70b-versatile", _has_groq, _make_groq),
]

# Fast agents need speed — prefer Groq
_FAST_PRIORITY = [
    ("groq", "llama-3.3-70b-versatile", _has_groq, _make_groq),
    ("google", "gemini-2.5-pro", _has_google, _make_google),
    ("agentrouter", "claude-opus-4-6", _has_agentrouter, _make_agentrouter),
]

# Which agents are "smart" vs "fast"
_AGENT_TIER = {
    "diagnostic": "smart",
    "repair": "smart",
    "validator": "fast",
    "simulation": "fast",
    "execution": "fast",
}


def get_llm(agent_name: str, temperature: float = 0):
    """
    Get the best available LLM for a given agent.

    Args:
        agent_name: one of "diagnostic", "repair", "validator", "simulation", "execution"
        temperature: LLM temperature (0 = deterministic)

    Returns:
        A LangChain chat model instance.

    Raises:
        ValueError if no provider is available.
    """
    # Check for per-agent override in env
    env_key = f"{agent_name.upper()}_MODEL"
    override = os.getenv(env_key, "auto")

    if override != "auto":
        return _build_from_override(override, temperature, agent_name)

    # Auto-select based on tier
    tier = _AGENT_TIER.get(agent_name, "fast")
    priority = _SMART_PRIORITY if tier == "smart" else _FAST_PRIORITY

    for provider_name, default_model, check_fn, make_fn in priority:
        if check_fn():
            try:
                llm = make_fn(model=default_model, temperature=temperature)
                logger.info(
                    f"LLM [{agent_name}]: {provider_name}:{default_model} "
                    f"(tier={tier}, temp={temperature})"
                )
                return llm
            except Exception as e:
                logger.warning(f"LLM [{agent_name}]: {provider_name} failed: {e}")
                continue

    raise ValueError(
        f"No LLM provider available for '{agent_name}'. "
        f"Set at least one of: GROQ_API_KEY, GOOGLE_API_KEY, AGENT_ROUTER_API_KEY in .env"
    )


def _build_from_override(spec: str, temperature: float, agent_name: str):
    """Build LLM from explicit 'provider:model' spec."""
    if ":" in spec:
        provider, model = spec.split(":", 1)
    else:
        # Guess provider from model name
        model = spec
        if "gemini" in model.lower():
            provider = "google"
        elif "claude" in model.lower() or "opus" in model.lower():
            provider = "agentrouter"
        else:
            provider = "groq"

    makers = {
        "groq": _make_groq,
        "google": _make_google,
        "agentrouter": _make_agentrouter,
    }

    make_fn = makers.get(provider)
    if not make_fn:
        raise ValueError(f"Unknown provider '{provider}' in {agent_name} override '{spec}'")

    llm = make_fn(model=model, temperature=temperature)
    logger.info(f"LLM [{agent_name}]: {provider}:{model} (override, temp={temperature})")
    return llm


def get_model_name(agent_name: str) -> str:
    """Get the model name string for logging/DB (without creating the LLM)."""
    env_key = f"{agent_name.upper()}_MODEL"
    override = os.getenv(env_key, "auto")

    if override != "auto":
        return override if ":" in override else f"custom:{override}"

    tier = _AGENT_TIER.get(agent_name, "fast")
    priority = _SMART_PRIORITY if tier == "smart" else _FAST_PRIORITY

    for provider_name, default_model, check_fn, _ in priority:
        if check_fn():
            return f"{provider_name}:{default_model}"

    return "none"
