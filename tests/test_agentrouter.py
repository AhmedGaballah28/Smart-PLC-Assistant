import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

key = os.getenv("AGENT_ROUTER_API_KEY")
if not key:
    print("NO API KEY FOUND")
    exit(1)

print(f"Key starts with: {key[:10]}...")

# AgentRouter expects the key as Authorization: Bearer <token>
# ChatOpenAI should handle this, but let's try with explicit default_headers
llm = ChatOpenAI(
    base_url="https://agentrouter.org/v1",
    api_key=key,
    model="claude-opus-4-6",
    temperature=0,
    default_headers={
        "Authorization": f"Bearer {key}",
    }
)

try:
    print("Invoking AgentRouter Opus...")
    result = llm.invoke([("user", "Respond with a single word: SUCCESS.")])
    print(f"Result: {result.content}")
except Exception as e:
    print(f"Error: {e}")
