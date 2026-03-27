"""
LLM Client Module
Uses GROQ API (FREE) with smart model selection.
"""

import json
import logging
from typing import Optional

from groq import Groq

from config.settings import GROQ_API_KEY, LLM_TEMPERATURE

logger = logging.getLogger(__name__)

MODEL_HEAVY = "llama-3.3-70b-versatile"
MODEL_LIGHT = "llama-3.1-8b-instant"


class LLMClient:
    """
    LLM Client using GROQ (FREE API).
    Heavy tasks: 70B model
    Light tasks: 8B model
    """

    def __init__(self):
        if not GROQ_API_KEY:
            logger.error("❌ GROQ_API_KEY not found in .env file!")
            raise ValueError("GROQ_API_KEY is required. Get it free at https://console.groq.com")

        self.client = Groq(api_key=GROQ_API_KEY)
        self.temperature = LLM_TEMPERATURE
        logger.info(f"✅ LLM Client initialized")
        logger.info(f"   Heavy model: {MODEL_HEAVY}")
        logger.info(f"   Light model: {MODEL_LIGHT}")

    def ask(self, prompt: str, system_prompt: Optional[str] = None,
            model: str = MODEL_HEAVY, max_tokens: int = 2000,
            temperature: Optional[float] = None) -> str:
        try:
            messages = []
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature or self.temperature,
                max_tokens=max_tokens
            )

            result = response.choices[0].message.content
            logger.debug(f"LLM [{model}] responded ({len(result)} chars)")
            return result

        except Exception as e:
            logger.error(f"❌ LLM API Error [{model}]: {e}")
            return f"LLM_ERROR: {str(e)}"

    def diagnose_fault(self, sensor_data: dict, rag_context: str) -> str:
        system_prompt = """You are an expert PLC diagnostic agent for an industrial 
conveyor sorting system. Analyze sensor data and determine root cause.

Respond in JSON format with: root_cause, confidence (0-100), severity, 
evidence (list), reasoning, alternative_causes, urgency, recommended_action."""

        prompt = f"""Analyze this sensor data:

SENSOR DATA:
{json.dumps(sensor_data, indent=2)}

KNOWLEDGE BASE:
{rag_context}

Provide diagnosis in JSON format."""

        return self.ask(prompt, system_prompt, model=MODEL_HEAVY)

    def suggest_repair(self, diagnosis: str, rag_context: str) -> str:
        system_prompt = """You are an expert PLC repair agent. Propose specific 
repair solutions with exact parameter values.

Respond in JSON format with solutions list, each having: id, name, description,
parameters_to_change, expected_result, risk_level, trade_offs."""

        prompt = f"""Propose repairs for this diagnosis:

DIAGNOSIS:
{diagnosis}

KNOWLEDGE:
{rag_context}

Provide solutions in JSON format."""

        return self.ask(prompt, system_prompt, model=MODEL_HEAVY)

    def validate_safety(self, proposed_change: dict, safety_rules: str) -> str:
        system_prompt = """You are a safety validation agent. Check proposed PLC 
changes for safety issues. Be thorough and conservative.

Respond in JSON with: verdict (PASS/FAIL), risk_score (0-100), checks, concerns."""

        prompt = f"""Validate this change:

PROPOSED CHANGE:
{json.dumps(proposed_change, indent=2)}

SAFETY RULES:
{safety_rules}

Provide validation in JSON format."""

        return self.ask(prompt, system_prompt, model=MODEL_HEAVY)

    def explain_to_human(self, diagnosis: str, repair: str,
                         simulation: str, operator_level: str = "intermediate") -> str:
        level_instructions = {
            "beginner": "Use very simple language. No technical jargon.",
            "intermediate": "Use balanced technical detail.",
            "expert": "Use full technical language. Include raw data."
        }

        system_prompt = f"""You are explaining a PLC fault to a factory operator.
{level_instructions.get(operator_level, level_instructions['intermediate'])}
Be clear and honest about risks."""

        prompt = f"""Explain this to the operator:

Diagnosis: {diagnosis}
Proposed Fix: {repair}
Simulation: {simulation}

Help them decide to APPROVE or REJECT."""

        return self.ask(prompt, system_prompt, model=MODEL_HEAVY)

    def format_alert(self, raw_alert: dict) -> str:
        prompt = f"Convert to 2-3 sentence alert:\n{json.dumps(raw_alert)}"
        return self.ask(prompt, model=MODEL_LIGHT, max_tokens=200)

    def summarize_performance(self, metrics: dict) -> str:
        prompt = f"Summarize in 3-4 bullet points:\n{json.dumps(metrics)}"
        return self.ask(prompt, model=MODEL_LIGHT, max_tokens=300)

    def test_connection(self) -> dict:
        results = {}

        print("  Testing heavy model (llama-3.3-70b-versatile)...")
        try:
            response = self.ask("Say exactly: HEAVY_MODEL_OK", model=MODEL_HEAVY, max_tokens=20)
            if "ERROR" not in response:
                results["heavy_model"] = True
                print(f"    ✅ Heavy model working: {response.strip()}")
            else:
                results["heavy_model"] = False
                print(f"    ❌ Heavy model error: {response}")
        except Exception as e:
            results["heavy_model"] = False
            print(f"    ❌ Heavy model error: {e}")

        print("  Testing light model (llama-3.1-8b-instant)...")
        try:
            response = self.ask("Say exactly: LIGHT_MODEL_OK", model=MODEL_LIGHT, max_tokens=20)
            if "ERROR" not in response:
                results["light_model"] = True
                print(f"    ✅ Light model working: {response.strip()}")
            else:
                results["light_model"] = False
                print(f"    ❌ Light model error: {response}")
        except Exception as e:
            results["light_model"] = False
            print(f"    ❌ Light model error: {e}")

        return results