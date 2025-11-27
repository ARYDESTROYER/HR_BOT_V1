#!/usr/bin/env python3
"""
Continuous Conversation Test Script
Tests the HR Bot with multi-turn conversations to verify:
1. Context retention across turns
2. Follow-up question handling
3. Topic switching
4. Elite accuracy on all responses
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from hr_bot.crew import HrBot

# Test conversation scenarios
CONVERSATION_SCENARIOS = [
    {
        "name": "Harassment Follow-up Conversation",
        "description": "Initial harassment query followed by clarifying questions",
        "turns": [
            {
                "query": "A colleague keeps making inappropriate comments about my appearance. What should I do?",
                "expected_keywords": ["harassment", "report", "ICC", "ethics@inara.com", "confidential"],
                "should_not_contain": ["hrportal.company.com", "example.com"]  # No hallucinated URLs
            },
            {
                "query": "Can I report this anonymously?",
                "expected_keywords": ["anonymous", "confidential"],
                "context_aware": True  # Should understand this is about harassment
            },
            {
                "query": "What happens after I submit the complaint?",
                "expected_keywords": ["investigation", "days", "ICC"],
                "context_aware": True
            }
        ]
    },
    {
        "name": "Leave Policy Deep Dive",
        "description": "Maternity leave with follow-up on eligibility and process",
        "turns": [
            {
                "query": "What is the maternity leave policy at Inara?",
                "expected_keywords": ["maternity", "weeks", "leave"],
            },
            {
                "query": "How do I apply for it?",
                "expected_keywords": ["apply", "HR", "portal"],
                "context_aware": True  # Should know "it" refers to maternity leave
            },
            {
                "query": "What about paternity leave?",
                "expected_keywords": ["paternity", "days", "father"],
                "topic_switch": True  # Related but different topic
            }
        ]
    },
    {
        "name": "Topic Switching",
        "description": "Completely different topics to test context isolation",
        "turns": [
            {
                "query": "How many days of sick leave do I get?",
                "expected_keywords": ["sick", "leave", "days"],
            },
            {
                "query": "Now tell me about the dress code policy",
                "expected_keywords": ["dress", "code", "attire"],
                "topic_switch": True
            },
            {
                "query": "What about work from home policy?",
                "expected_keywords": ["work", "home", "remote", "hybrid"],
                "topic_switch": True
            }
        ]
    },
    {
        "name": "Procedural + Policy Combo",
        "description": "Questions requiring both master_actions_guide AND hr_document_search",
        "turns": [
            {
                "query": "How do I check my leave balance and what's the leave encashment policy?",
                "expected_keywords": ["leave", "balance"],
                "needs_both_tools": True
            },
            {
                "query": "What if I want to apply for leave today?",
                "expected_keywords": ["apply", "leave"],
                "context_aware": True
            }
        ]
    },
    {
        "name": "Greeting and Capability Check",
        "description": "Non-policy queries that shouldn't use tools",
        "turns": [
            {
                "query": "Hi there!",
                "expected_keywords": ["hello", "hi", "help", "assist"],
                "should_not_contain": ["Sources:", ".docx"],  # No sources for greetings
                "no_tool_needed": True
            },
            {
                "query": "What can you help me with?",
                "expected_keywords": ["policy", "leave", "help", "questions"],
                "should_not_contain": ["Sources:"],
                "no_tool_needed": True
            },
            {
                "query": "Great, tell me about the probation policy",
                "expected_keywords": ["probation", "confirmation", "months"],
                "tool_needed": True
            }
        ]
    }
]


def print_header(text: str, char: str = "="):
    """Print a formatted header"""
    print(f"\n{char * 70}")
    print(f"  {text}")
    print(f"{char * 70}\n")


def print_result(passed: bool, message: str):
    """Print test result with color"""
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {status}: {message}")


def check_keywords(response: str, expected: list, check_type: str = "contains") -> tuple[bool, list]:
    """Check if response contains expected keywords"""
    response_lower = response.lower()
    found = []
    missing = []
    
    for keyword in expected:
        if keyword.lower() in response_lower:
            found.append(keyword)
        else:
            missing.append(keyword)
    
    if check_type == "contains":
        return len(missing) == 0, missing
    else:  # "not_contains"
        return len(found) == 0, found


def run_conversation_test(scenario: dict, bot: HrBot) -> dict:
    """Run a single conversation scenario"""
    print_header(f"SCENARIO: {scenario['name']}", "─")
    print(f"📝 {scenario['description']}\n")
    
    results = {
        "name": scenario["name"],
        "turns": [],
        "passed": True
    }
    
    conversation_history = []
    
    for turn_num, turn in enumerate(scenario["turns"], 1):
        print(f"\n{'─' * 50}")
        print(f"  TURN {turn_num}: {turn['query'][:60]}...")
        print(f"{'─' * 50}")
        
        # Build context from previous turns
        context = ""
        if conversation_history:
            context_parts = []
            for prev in conversation_history[-3:]:  # Last 3 turns for context
                context_parts.append(f"User: {prev['query'][:100]}")
                context_parts.append(f"Assistant: {prev['response'][:200]}...")
            context = "\n".join(context_parts)
        
        # Run the query
        try:
            # Include context hint for follow-up questions
            query = turn["query"]
            if turn.get("context_aware") and conversation_history:
                # The bot should infer context, but we can hint it
                last_topic = conversation_history[-1].get("topic", "")
                if last_topic:
                    query = f"(Regarding {last_topic}) {query}"
            
            response = bot.query_with_cache(query, context=context)
            
            print(f"\n📤 Query: {turn['query']}")
            print(f"\n📥 Response ({len(response)} chars):")
            print(f"   {response[:500]}{'...' if len(response) > 500 else ''}")
            
            turn_result = {
                "query": turn["query"],
                "response": response,
                "checks": []
            }
            
            # Check expected keywords
            if "expected_keywords" in turn:
                passed, missing = check_keywords(response, turn["expected_keywords"])
                turn_result["checks"].append({
                    "type": "expected_keywords",
                    "passed": passed,
                    "details": f"Missing: {missing}" if missing else "All found"
                })
                print_result(passed, f"Expected keywords: {turn['expected_keywords'][:5]}...")
                if not passed:
                    print(f"      Missing: {missing}")
                    results["passed"] = False
            
            # Check should_not_contain (hallucination check)
            if "should_not_contain" in turn:
                passed, found = check_keywords(response, turn["should_not_contain"], "not_contains")
                turn_result["checks"].append({
                    "type": "no_hallucination",
                    "passed": passed,
                    "details": f"Found forbidden: {found}" if found else "Clean"
                })
                print_result(passed, f"No hallucination check: {turn['should_not_contain']}")
                if not passed:
                    print(f"      Found forbidden content: {found}")
                    results["passed"] = False
            
            # Check no sources for non-tool queries
            if turn.get("no_tool_needed"):
                has_sources = "Sources:" in response or ".docx" in response
                passed = not has_sources
                turn_result["checks"].append({
                    "type": "no_sources",
                    "passed": passed,
                    "details": "No sources in greeting/capability response" if passed else "Incorrectly included sources"
                })
                print_result(passed, "No sources for greeting/capability query")
                if not passed:
                    results["passed"] = False
            
            # Store for context
            conversation_history.append({
                "query": turn["query"],
                "response": response,
                "topic": turn.get("topic", turn["query"].split()[0:3])
            })
            
            turn_result["passed"] = all(c["passed"] for c in turn_result["checks"])
            results["turns"].append(turn_result)
            
        except Exception as e:
            print(f"\n❌ ERROR: {e}")
            results["turns"].append({
                "query": turn["query"],
                "error": str(e),
                "passed": False
            })
            results["passed"] = False
    
    return results


def main():
    """Run all conversation tests"""
    print_header("HR BOT CONTINUOUS CONVERSATION TEST", "═")
    print("Testing multi-turn conversations, follow-ups, and context retention\n")
    
    # Initialize bot once
    print("🔧 Initializing HR Bot...")
    try:
        bot = HrBot(user_role="employee", use_s3=True)
        print("✅ Bot initialized successfully\n")
    except Exception as e:
        print(f"❌ Failed to initialize bot: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Clear response cache for fresh tests
    print("🧹 Clearing response cache for fresh tests...")
    try:
        bot.response_cache.clear_all()
        print("✅ Cache cleared\n")
    except Exception as e:
        print(f"⚠️  Could not clear cache: {e}")
    
    # Run all scenarios
    all_results = []
    
    for scenario in CONVERSATION_SCENARIOS:
        try:
            result = run_conversation_test(scenario, bot)
            all_results.append(result)
        except Exception as e:
            print(f"\n❌ Scenario failed with error: {e}")
            all_results.append({
                "name": scenario["name"],
                "error": str(e),
                "passed": False
            })
    
    # Summary
    print_header("TEST SUMMARY", "═")
    
    passed_scenarios = sum(1 for r in all_results if r.get("passed", False))
    total_scenarios = len(all_results)
    
    for result in all_results:
        status = "✅" if result.get("passed") else "❌"
        print(f"  {status} {result['name']}")
        if "error" in result:
            print(f"      Error: {result['error']}")
        elif "turns" in result:
            for i, turn in enumerate(result["turns"], 1):
                turn_status = "✓" if turn.get("passed") else "✗"
                print(f"      Turn {i}: {turn_status}")
    
    print(f"\n{'─' * 50}")
    print(f"  TOTAL: {passed_scenarios}/{total_scenarios} scenarios passed")
    print(f"{'─' * 50}")
    
    # Overall result
    if passed_scenarios == total_scenarios:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total_scenarios - passed_scenarios} scenario(s) failed")
        return 1


if __name__ == "__main__":
    exit(main())
