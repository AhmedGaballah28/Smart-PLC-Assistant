from agents.supervisor_graph import supervisor_app
import sys

try:
    print("Generating graph image...")
    # .get_graph() converts the compiled app into a drawable graph structure
    png_bytes = supervisor_app.get_graph().draw_mermaid_png()
    
    with open("supervisor_graph.png", "wb") as f:
        f.write(png_bytes)
        
    print("Successfully saved to supervisor_graph.png!")
except Exception as e:
    print(f"Error generating graph: {e}", file=sys.stderr)
