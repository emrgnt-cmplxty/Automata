from automata.eval import SymbolSearchAction
from automata.llm import FunctionCall


def mock_tool_response_with_search_action_completion():
    return {
        "choices": [
            {
                "message": {
                    "role": "tool",
                    "content": "SymbolSearchAction(query='test_query', search_results=['result1', 'result2'])",
                }
            }
        ]
    }


EXPECTED_TOOL_ACTIONS = [
    SymbolSearchAction(
        query="test_query_1", search_results=["result1", "result2"]
    ),
    SymbolSearchAction(
        query="test_query_2", search_results=["result1", "result2"]
    ),
]
FUNCTION_CALLS = [
    FunctionCall(
        name="symbol-rank-search", arguments={"query": "test_query_1"}
    ),
    FunctionCall(
        name="symbol-rank-search", arguments={"query": "test_query_2"}
    ),
]

params = {
    # previous params
    "test_tool_evaluation_harness_and_metrics": [
        mock_tool_response_with_search_action_completion(),
    ],
}
