#!/usr/bin/env python
"""
Production-Ready HR Bot - Main Entry Point
Hierarchical manager + specialists crew with hybrid RAG and Apideck integration
"""

import sys
import warnings
import os
from datetime import datetime
from pathlib import Path

#from hr_bot.crew_hierarchical import HrBotHierarchical
from hr_bot.crew import HrBot
warnings.filterwarnings("ignore", category=SyntaxWarning, module="pysbd")


def run_crew():
    """
    Entry point for crewai run command.
    This is called by the CrewAI CLI.
    """
    run()
    return 0


def run():
    """
    Run the HR Bot crew with a query.
    Usage: 
        crewai run
        or
        hr_bot run [query]
    """
    print("\n" + "="*70)
    print("HR Bot - Production-Ready HR Assistant")
    print("="*70 + "\n")
    
    # Default query for testing
    default_query = "How to download my Form-16 and also tell me how to apply for leaves"
    
    # Check if query is provided as argument
    if len(sys.argv) > 1 and sys.argv[0] != 'crewai':
        query = " ".join(sys.argv[1:])
    else:
        # Use default query for crewai run
        query = default_query
        print(f"Running with default query: '{query}'")
        print("(You can also provide a custom query as an argument)\n")
    
    if not query:
        print("No query provided. Please enter a question.")
        return
    
    inputs = {
        'query': query,
        'context': ''  # Can be populated with additional context if needed
    }
    
    try:
        print("\nProcessing your query...\n")
        bot = HrBot()
        # Use query_with_cache which includes content safety filtering
        result = bot.query_with_cache(query, context=inputs.get('context', ''))
        
        # Print the response
        print("\n" + "="*70)
        print("RESPONSE:")
        print("="*70 + "\n")
        print(result)
        print("\n" + "="*70 + "\n")
        
        return result
        
    except KeyboardInterrupt:
        print("\n\nSession terminated by user.")
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()
        raise


def interactive():
    """
    Run the HR Bot in interactive mode for continuous queries
    """
    print("\n" + "="*70)
    print("HR Bot - Interactive Mode")
    print("="*70 + "\n")
    print("Ask about HR policies or procedures (type 'exit' to quit).\n")
    
    #bot = HrBotHierarchical()
    bot = HrBot()
    
    while True:
        try:
            query = input("\nYour query: ").strip()
            
            if not query:
                continue
            
            if query.lower() in ['exit', 'quit', 'bye']:
                print("\nSession ended.")
                break
            
            inputs = {
                'query': query,
                'context': ''
            }
            
            print("\nProcessing...\n")
            result = bot.query_with_cache(query, context=inputs.get('context', ''))
            
            print("\n" + "-"*70)
            print("Response:")
            print("-"*70 + "\n")
            print(result)
            print("\n" + "-"*70)
            
        except KeyboardInterrupt:
            print("\n\nSession terminated by user.")
            break
        except Exception as e:
            print(f"\nError: {e}")


def setup():
    """
    Setup the HR Bot environment
    """
    print("\n" + "="*70)
    print("HR Bot Setup")
    print("="*70 + "\n")
    
    # Check for required directories
    data_dir = Path("data")
    if not data_dir.exists():
        print("'data' directory not found. Creating it...")
        data_dir.mkdir(exist_ok=True)
        print("Created 'data' directory. Please add HR documents (.docx) to this folder.")
    else:
        doc_count = len(list(data_dir.glob("*.docx")))
        print(f"Found {doc_count} document(s) in 'data' directory")
    
    # Check environment variables
    print("\nChecking required environment variables...")
    
    required_vars = {
        "GOOGLE_API_KEY": "Gemini API key for embeddings and LLM",
        "GEMINI_MODEL": "Gemini model name (optional, defaults to gemini-1.5-flash)"
    }
    
    optional_vars = {
        "APIDECK_API_KEY": "API Deck key for HR system integration",
        "APIDECK_APP_ID": "API Deck application ID",
        "APIDECK_SERVICE_ID": "HR platform service ID"
    }
    
    for var, description in required_vars.items():
        if os.getenv(var):
            print(f"{var} is set")
        else:
            print(f"{var} is NOT set - {description}")
    
    print("\nOptional environment variables:")
    for var, description in optional_vars.items():
        if os.getenv(var):
            print(f"{var} is set")
        else:
            print(f"{var} is NOT set - {description}")
    
    print("\n" + "="*70)
    print("Setup complete. Use 'hr_bot run' to start the bot.")
    print("="*70 + "\n")


def train():
    """
    Train the crew for a given number of iterations.
    """
    if len(sys.argv) < 3:
        print("Usage: hr_bot train <n_iterations> <filename>")
        return
    
    inputs = {
        "query": "What is the maternity leave policy?",
        "context": ""
    }
    
    try:
        HrBotHierarchical().crew().train(
            n_iterations=int(sys.argv[1]),
            filename=sys.argv[2],
            inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while training the crew: {e}")


def replay():
    """
    Replay the crew execution from a specific task.
    """
    if len(sys.argv) < 2:
        print("Usage: hr_bot replay <task_id>")
        return
    
    try:
        HrBotHierarchical().crew().replay(task_id=sys.argv[1])
    except Exception as e:
        raise Exception(f"An error occurred while replaying the crew: {e}")


def test():
    """
    Test the crew execution and returns the results.
    """
    if len(sys.argv) < 3:
        print("Usage: hr_bot test <n_iterations> <eval_llm>")
        return
    
    inputs = {
        "query": "What is the sick leave policy?",
        "context": ""
    }
    
    try:
        HrBotHierarchical().crew().test(
            n_iterations=int(sys.argv[1]),
            eval_llm=sys.argv[2],
            inputs=inputs
        )
    except Exception as e:
        raise Exception(f"An error occurred while testing the crew: {e}")


if __name__ == "__main__":
    run()
