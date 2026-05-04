import logging
from pydantic import BaseModel, Field
from langchain_groq import ChatGroq
from langgraph.prebuilt import create_react_agent

logging.basicConfig(level=logging.INFO)

class MyOutput(BaseModel):
    summary: str = Field(description="Summary of the process")
    confidence: int = Field(description="Confidence from 0 to 100")

def test():
    llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)
    agent = create_react_agent(llm, tools=[], response_format=MyOutput)
    
    result = agent.invoke({"messages": [("user", "Analyze the factory metrics and give 95 confidence.")]})
    print("KEYS IN RESULT:", result.keys())
    if "structured_response" in result:
        print("STRUCTURED RESPONSE:", result["structured_response"])
    else:
        last_msg = result["messages"][-1]
        print("LAST MESSAGE CONTENT:", last_msg.content)
        if hasattr(last_msg, 'tool_calls'):
            print("TOOL CALLS:", last_msg.tool_calls)

if __name__ == "__main__":
    test()
