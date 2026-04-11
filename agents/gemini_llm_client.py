"""
Gemini LLM Client — Google AI Studio API
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

MODEL_HEAVY = "gemini-1.5-pro"
MODEL_LIGHT  = "gemini-1.5-flash"


class GeminiLLMClient:
    """
    Gemini API client — drop-in replacement for the GROQ LLMClient.
    Get your API key free at https://aistudio.google.com/app/apikey
    """

    def __init__(self, api_key: str, temperature: float = 0.3):
        if not GENAI_AVAILABLE:
            raise ImportError("Run: pip install google-generativeai")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY is required.")
        genai.configure(api_key=api_key)
        self.temperature = temperature
        self._heavy = genai.GenerativeModel(MODEL_HEAVY)
        self._light  = genai.GenerativeModel(MODEL_LIGHT)
        logger.info(f"✅ Gemini client ready  heavy={MODEL_HEAVY}  light={MODEL_LIGHT}")

    def ask(self, prompt: str, system_prompt: Optional[str] = None,
            use_heavy: bool = True, max_tokens: int = 2000) -> str:
        try:
            model = self._heavy if use_heavy else self._light
            full_prompt = f"{system_prompt}\n\n---\n\n{prompt}" if system_prompt else prompt
            resp = model.generate_content(
                full_prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=max_tokens, temperature=self.temperature
                ),
            )
            return resp.text
        except Exception as e:
            logger.error(f"Gemini error: {e}")
            return f"LLM_ERROR: {e}"

    def diagnose_fault(self, sensor_data: dict, rag_context: str) -> str:
        sys = ("You are an expert PLC diagnostic agent. Respond ONLY with valid JSON: "
               '{"root_cause":"","confidence":0-100,"severity":"LOW|MEDIUM|HIGH|CRITICAL",'
               '"evidence":[],"reasoning":"","alternative_causes":[],"urgency":"LOW|MEDIUM|HIGH",'
               '"recommended_action":""}')
        p = f"Sensor data:\n{json.dumps(sensor_data,indent=2)}\n\nKnowledge:\n{rag_context or 'None'}"
        return self.ask(p, sys, use_heavy=True)

    def suggest_repair(self, diagnosis: str, rag_context: str) -> str:
        sys = ('You are a PLC repair agent. Respond ONLY with valid JSON: '
               '{"solutions":[{"id":1,"name":"","description":"","parameters_to_change":{},'
               '"expected_result":"","risk_level":"LOW|MEDIUM|HIGH","estimated_downtime_min":0,"trade_offs":""}]}')
        p = f"Diagnosis:\n{diagnosis}\n\nKnowledge:\n{rag_context or 'None'}"
        return self.ask(p, sys, use_heavy=True)

    def validate_safety(self, proposed_change: dict, safety_rules: str) -> str:
        sys = ('Safety validator. Respond ONLY with valid JSON: '
               '{"verdict":"PASS|FAIL|CONDITIONAL","risk_score":0-100,"checks":[],"concerns":[]}')
        p = f"Change:\n{json.dumps(proposed_change,indent=2)}\n\nRules:\n{safety_rules}"
        return self.ask(p, sys, use_heavy=False, max_tokens=800)

    def format_alert(self, raw_alert: dict) -> str:
        return self.ask(f"Write 2 sentences summarising this factory alert for an operator:\n{json.dumps(raw_alert)}", use_heavy=False, max_tokens=150)

    def summarize_performance(self, metrics: dict) -> str:
        return self.ask(f"Summarise production performance in 3 bullet points:\n{json.dumps(metrics)}", use_heavy=False, max_tokens=250)

    def test_connection(self) -> dict:
        results = {}
        for label, heavy in [("heavy", True), ("light", False)]:
            try:
                r = self.ask("Reply with OK", use_heavy=heavy, max_tokens=10)
                results[label] = "ERROR" not in r
                print(f"  {'✅' if results[label] else '❌'} {label}: {r.strip()[:40]}")
            except Exception as e:
                results[label] = False
                print(f"  ❌ {label}: {e}")
        return results
