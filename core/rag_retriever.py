import sys
import os
sys.path.append("C:\\stlibs")
from langchain_text_splitters import MarkdownHeaderTextSplitter 
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_community.vectorstores import Chroma
from dotenv import load_dotenv
from langchain_core.runnables import RunnableLambda

load_dotenv()

CORE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CORE_DIR)
KB_FILE_PATH = os.path.join(PROJECT_ROOT, "knowledge_base", "factory_troubleshooting_manual.md")
CHROMA_DB_DIR = os.path.join(PROJECT_ROOT, "data", "chroma_db")

embedding_model = HuggingFaceEmbeddings(model="sentence-transformers/all-MiniLM-L6-v2")

# def initialize_knowledge_base():
#     """Reads the Markdown manual, splits it by headers, and stores it in ChromaDB."""
#     # 1. Read the raw Markdown text
#     with open(KB_FILE_PATH, "r", encoding="utf-8") as f:
#         markdown_document = f.read()

#     # 2. Define the headers we want to split on
#     headers_to_split_on = [
#         ("##", "Header 2"),
#         ("###", "Header 3"),
#     ]

#     # 3. Split the document
#     markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
#     md_header_splits = markdown_splitter.split_text(markdown_document)

#     # 4. Save to Chroma DB
#     print(f"Storing {len(md_header_splits)} chunks into ChromaDB at {CHROMA_DB_DIR}...")
#     vectorstore = Chroma.from_documents(
#         documents=md_header_splits,
#         embedding=embedding_model,
#         persist_directory=CHROMA_DB_DIR
#     )
#     print("Knowledge base initialized successfully!")
#     return vectorstore

# if __name__ == "__main__":
#     if not os.path.exists(CHROMA_DB_DIR):
#         print("ChromaDB directory does not exist. Initializing knowledge base...")
#         initialize_knowledge_base()
#     else:
#         print("ChromaDB directory already exists. Skipping initialization.")

load_content_of_K_B_file = RunnableLambda(lambda kb_file_path : open(kb_file_path, "r", encoding="utf-8").read())
headers_to_split_on = [
        ("##", "Header 2"),
        ("###", "Header 3"),
    ]
markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on, strip_headers=False)
split_markdown_content = RunnableLambda(lambda content: markdown_splitter.split_text(content))

def format_chunks(chunks):
    for chunk in chunks:
        # Prepend the section headers so the embedding model has context
        context = " > ".join(str(v) for k, v in chunk.metadata.items() if "Header" in k)
        if context:
            chunk.page_content = f"Context: {context}\n\n{chunk.page_content}"
    return chunks

format_chunks_runnable = RunnableLambda(format_chunks)

store_in_chroma_db = RunnableLambda(lambda chunks: Chroma.from_documents(
    documents=chunks,
    embedding=embedding_model,
    persist_directory=CHROMA_DB_DIR
))

make_rag_database = load_content_of_K_B_file | split_markdown_content | format_chunks_runnable | store_in_chroma_db

if __name__ == "__main__":
    if not os.path.exists(CHROMA_DB_DIR):
        print("ChromaDB directory does not exist. Initializing knowledge base...")
        make_rag_database.invoke(input=KB_FILE_PATH)
    else:
        print("ChromaDB directory already exists. Skipping initialization.")
    
    db_retriever = Chroma(embedding_function=embedding_model, persist_directory=CHROMA_DB_DIR).as_retriever(search_type="mmr", search_kwargs={"k": 3, "fetch_k": 10, "lambda_mult": 0.8})

    while True:
        user_query = input("\nEnter your question (or 'exit' to quit): ")
        if user_query.lower() == "exit":
            print("Exiting the RAG retriever. Goodbye!")
            break

        results = db_retriever.invoke(user_query)
        print(f"\nRetrieved {len(results)} relevant document(s):")
        for i, doc in enumerate(results, 1):
            print(f"\nDocument {i}:\n{doc.page_content}\n")