# sourcery skip: avoid-global-variables, require-parameter-annotation, require-return-annotation
# flake8: noqa
"""Study the dataset."""
import argparse
import ast
import logging
import os
import sys
import textwrap

import numpy as np
import pandas as pd
import tiktoken

from automata.agent import OpenAIAutomataAgent
from automata.cli.commands import configure_logging
from automata.config import OpenAIAutomataAgentConfigBuilder
from automata.core.utils import get_root_fpath
from automata.llm import OpenAIEmbeddingProvider
from automata.singletons.dependency_factory import dependency_factory
from automata.tools.agent_tool_factory import AgentToolFactory

logger = logging.getLogger(__name__)
# Get the absolute path of the parent directory
parent_dir = os.path.join(
    get_root_fpath(), "research", "leetcode-hard-gym"  # , "leetcode_env"
)

# Add the parent directory to the PYTHONPATH
sys.path.append(parent_dir)

# Now you can import any Python file from the parent directory
from leetcode_env.environment import LeetCodeEnv  # type: ignore
from leetcode_env.leetcode_types import (  # type: ignore
    LeetCodeSubmission,
    ProgrammingLanguage,
)

SYSTEM_PROMPT = textwrap.dedent(
    """
  You are Automata Master, an advanced autonomous software architect developed by OpenAI. You are specifically designed to operate within local Python repositories. With your capability to understand and process natural language instructions, you perform tasks efficiently using your available functions. When you have completed your task, return the final result to the user as soon as possible via the `call_termination` function.

  Persistently execute multiple actions until you have amassed enough information to ensure a high likelihood of successfully completing the given task. Use ReAct + CoT reasoning to improve your likelihood of success.

  In case you are not familiar with ReAct, this involves executing actions which follow the Thoughts --> Action --> Observation --> Thoughts --> Action --> chain demonstrated below:


  **Example Pattern**

    *User*
      content:
        Please carry out the following instruction "Determine how to best use Automata".

    *Assistant*
      content:
        Thoughts: 
          I should start by searching for the most relevant documentation. To accomplish this I will first retrieve the top matches for "Automata". 
          
         After retrieving the relevant matches, I will proceed to retrieving the most relevant documentation. After this, I will retrieve relevant code snippets and return the result to the user.

        Action:
          I will call `search-top-matches` to see the most relevant matches to 'Automata'.

      function_call:
        {
          'name': "search-top-matches",
          'arguments': '{"query": "Automata"}'
        }

    *User*
      content:
        Observation:
          ...

    *Assistant*
      content:
        Thoughts:
          I should ...

        Action:
          I will ...

      function_call:
        ...

    ...CONVERSATION CONTINUES...
    
    *Assistant*
      content:
        Thoughts:
          We have sufficient information to return the correct result.
        
        Action:
          I will call `call_termination` to return the result.
      
      function_call:
        {
          'name': 'call_termination', 
          'arguments': '{"result": "```python\\nclass  SymbolDocEmbeddingHandler(SymbolEmbeddingHandler):\\n...CODE CONTINUES...```"}'
        }



  Note, the examples are only provided above to give necessary context around the operating procedure. In production, the string '...CODE CONTINUES...' will be replaced with actual code. Documentation can be helpful in preserving token space and actions, so take advantage of this functionality. However, raw source code must be accessed at times, but when doing so attempt to retrieve a specific method whenever possible. Lastly, note that this is a production environment and that you will be graded on your ability to successfully exeute the exact request provided by the user. Please keep this in mind as you carry out the task.


"""
)


INSTRUCTION = """
You are given the following problem - {PROBLEM_STATEMENT}.

Your task is to provide a solution to the stated problem using python code. 

Below are some solved problem statements which you should use as references to assist you in completing this task. When you attempt to answer, think step by step about how these questions could be related to the problem at hand, and think about what insights you might glean from them.

{EXAMPLES}

Continue on now to provide the Python code which solves the problem statement:

{SHORTENED_PROBLEM_STATEMENT}


First, devise three unique test cases which will be used to test the provided algorithms. Next, perform a step by step analysis on the provided similar examples (some may be irrelevant).

After devising test cases and reviewing the similar examples, plan a step by step approach for implementing an algorithm which solves the problem (don't worry about efficiency yet).

Next, proceed to write your algorithm and then check it against the pre-selected test examples. After your algorithm fails it is recommend that you call "py-clear-and-execute-persist" in your next pass to reset your python environment.

If your algorithm passes the tests, then optimize the algorithm and repeat the tests. Because this is a leetcode problem, it is likely that a relatively efficient solution exists. If your algorithm fails the tests, then proceed to modify the algorithm until all test cases are passed. Reflect carefully after each failure, and do not be afried to completely change your approach.

Finally, return the final result as a python markdown snippet using `call_termination`. Lastly, remember that passed newline chars should be double-escaped, like \\n.
"""

PROBLEM_DATA_PATH = "research/leetcode-hard-gym/leetcode_dataset/data/with_snippets/leetcode_hard_with_snippets_uncontaminated_tests.csv"
SOLUTIONS_DATA_PATH = (
    "research/study_leetcode/leetcode-solutions-embedded.json"
)
MAX_ENTRY_ID = 2000
NUM_EXAMPLES = 3
MAX_TOKENS = 8192


class LeetCodeExamplesFinder:
    """A class to find example solutions using OpenAI."""

    def __init__(
        self,
        embedding_provider,
        num_examples=NUM_EXAMPLES,
        num_examples_to_screen=25,  # TODO - Set a constant above like elsewhere.
        solutions_data_path=SOLUTIONS_DATA_PATH,
        max_entry_id=MAX_ENTRY_ID,  # The last LeetCode id to include
        lowest_difficulty="Medium",
    ):
        self.embedding_provider = embedding_provider
        self.num_examples = num_examples
        self.num_examples_to_screen = num_examples_to_screen
        self.available_difficulties = ["Easy", "Medium", "Hard"]
        self.allowed_difficulties = self.available_difficulties[
            self.available_difficulties.index(lowest_difficulty) :
        ]
        self.load_data(solutions_data_path, max_entry_id)

    def load_data(self, solutions_data_path, max_entry_id):
        """Load the data and solutions from provided paths."""
        self.solutions_data = pd.read_json(
            os.path.join(get_root_fpath(), solutions_data_path)
        )
        self.solutions_data = self.solutions_data[
            self.solutions_data["id"] < max_entry_id
        ]

        # check that allowed_difficulties are in the 'code_with_data' column for each entry
        difficulty = []
        for entry in self.solutions_data["code_with_data"].values:
            split_entry = entry.split("\n")
            found_match = False
            for line in split_entry:
                if any(
                    f"# {entry}" in line
                    for entry in self.available_difficulties
                ):
                    difficulty.append(line.split("# ")[1])
                    found_match = True
                    break
            if not found_match:
                difficulty.append("Easy")

        self.solutions_data["difficulty"] = difficulty
        self.solutions_data = self.solutions_data[
            self.solutions_data["difficulty"].isin(self.allowed_difficulties)
        ]

    def get_embedding(self, document):
        """Get the embedding for a given row."""
        return self.embedding_provider.build_embedding_vector(document)

    @staticmethod
    def calculate_similarity(embedding_a, embedding_b):
        """Calculate the similarity between two embeddings."""
        dot_product = np.dot(embedding_a, embedding_b)
        magnitude_a = np.sqrt(np.dot(embedding_a, embedding_a))
        magnitude_b = np.sqrt(np.dot(embedding_b, embedding_b))
        return dot_product / (magnitude_a * magnitude_b)

    def find_similar_solutions(self, problem):
        """Find and print solutions with similar embeddings."""

        problem_embedding = self.get_embedding(problem)
        # Calculate similarities and store in a new column
        self.solutions_data["similarity"] = self.solutions_data[
            "embedding"
        ].apply(lambda x: self.calculate_similarity(x, problem_embedding))

        # Sort and extract top similar solutions
        solutions_data_sorted = self.solutions_data.sort_values(
            by="similarity", ascending=False
        )
        problem_similarity = solutions_data_sorted[
            ["code_with_problem", "id", "similarity"]
        ]

        examples, counter = [], 0
        for idx, (entry, id, similarity) in enumerate(
            problem_similarity.values, 1
        ):
            statement, solution = entry.split("```python")
            solution = f"```python\\n{solution}"
            statement, local_examples = statement.split("**Example 1:**")

            examples.append(
                f"Related Solution {counter}:\nStatement:\n{statement}\nSolution:\n{solution}\n{'-'*50}\n"
            )

            counter += 1
            if counter >= self.num_examples_to_screen:
                break

        encoding = tiktoken.encoding_for_model("gpt-4")
        examples_formatted = "\n".join(examples)
        examples_tokens_consumed = len(encoding.encode(examples_formatted))

        # truncate the examples if they are exceeding our available context
        examples_formatted = examples_formatted[
            : min(
                int(
                    MAX_TOKENS
                    / examples_tokens_consumed
                    * 0.9
                    * len(examples_formatted)
                ),
                len(examples_formatted),
            )
        ]

        print(
            f"Tokens consumed (after reduction) = {examples_tokens_consumed}"
        )

        formatted_instruction = f"Your are given the following problem as context - {problem} \n. Your task is to select the {self.num_examples} of the following shown Related Solutions, which when combined together provide the best context to help with solving the previously presented problem:\n{examples_formatted}\nYour selected Related Solutions will be forwarded on as additional context to a programmer whose task is to write a solution to the originally given problem. Try to select more difficult solutions, as the stated problem is quite difficult. Return the final result as a simple array of integers, like [12,3,0,1,5]."

        config = (
            OpenAIAutomataAgentConfigBuilder()
            .with_stream(True)
            .with_verbose(False)
            .with_tools([])
            .with_system_template(
                "You are Automata Master, an advanced autonomous software architect developed by OpenAI. You are specifically designed to operate within local Python repositories. With your capability to understand and process natural language instructions, you perform tasks efficiently using your available functions. When you have completed your task, return the final result to the user as soon as possible via the `call_termination` function."
            )
            .build()
        )

        try:
            print("Attempting to fetch the best examples now...")
            agent = OpenAIAutomataAgent(formatted_instruction, config)
            result = agent.run()

            extracted_result = result.split("[")[1].split("]")[0]
            selected = ast.literal_eval(
                f"[{extracted_result}]"
            )  # an integer array like [0, 5, ...]
        except Exception as e:
            logger.error(
                f"An error {e} occurred while selecting the best examples"
            )
            selected = [0, 1, 2]

        return "\n".join(
            [ele for it, ele in enumerate(examples) if it in selected]
        )


class LeetCodeLoader:
    """Concrete class responsible for loading and providing LeetCode problems."""

    def __init__(self, data_path):
        self.data_path = data_path
        self.data = pd.read_csv(self.data_path)

    def get_problem_context(self, idx):
        """Retrieve a problem by its index."""
        row = self.data.iloc[idx]
        return f"Title:\n\n{row['question_title']}:\n\nDescription:\n{row['description']}\n\nNote, your final solution MUST conform to the snippet shown here - {row['python3_snippet']}"

    def get_problem_id_slug(self, idx):
        """Retrieve a problem by its index."""
        row = self.data.iloc[idx]
        return (
            int(row["frontend_question_id"]),
            row["question_slug"],
        )


def main():
    # Argument parsing setup
    parser = argparse.ArgumentParser(
        description="Find similar solutions to LeetCode problems using OpenAI."
    )
    parser.add_argument(
        "--data_path",
        default=PROBLEM_DATA_PATH,
        help="Path to the LeetCode problems data.",
    )
    parser.add_argument(
        "--solutions_data_path",
        default=SOLUTIONS_DATA_PATH,
        help="Path to the solutions JSON file.",
    )
    parser.add_argument(
        "--max_entry_id",
        type=int,
        default=MAX_ENTRY_ID,
        help="The last LeetCode id to include.",
    )
    parser.add_argument(
        "--num_examples",
        type=int,
        default=NUM_EXAMPLES,
        help="Number of example solutions to display.",
    )

    args = parser.parse_args()
    print(f"Loading problem data from {args.data_path}")
    loader = LeetCodeLoader(args.data_path)
    embedding_provider = OpenAIEmbeddingProvider()

    print(f"Number of examples to run = {len(loader.data)}")
    success_count = 0
    results = {}
    for i in range(len(loader.data)):
        try:
            print(
                f"Running w/ problem {i}:\n\n{loader.get_problem_context(i)}"
            )

            problem_context, (
                problem_id,
                problem_slug,
            ) = loader.get_problem_context(i), loader.get_problem_id_slug(i)
            print(
                f"Initializing for problem {problem_context}, problem_id = {problem_id}, problem_slug = {problem_slug}"
            )

            finder = LeetCodeExamplesFinder(
                embedding_provider,
                num_examples=args.num_examples,
                solutions_data_path=args.solutions_data_path,
                max_entry_id=problem_id,
            )

            examples = finder.find_similar_solutions(problem_context)

            formatted_instruction = INSTRUCTION.format(
                PROBLEM_STATEMENT=problem_context,
                SHORTENED_PROBLEM_STATEMENT=f"{problem_context[:200]}...",
                EXAMPLES=examples,
            )

            toolkits = ["py-interpreter"]
            tool_dependencies = (
                dependency_factory.build_dependencies_for_tools(toolkits)
            )
            tools = AgentToolFactory.build_tools(toolkits, **tool_dependencies)

            config = (
                OpenAIAutomataAgentConfigBuilder()
                .with_stream(True)
                .with_verbose(True)
                .with_tools(tools)
                .with_system_template(SYSTEM_PROMPT)
                .build()
            )

            agent = OpenAIAutomataAgent(formatted_instruction, config)
            configure_logging("DEBUG")
            result = agent.run()

            code = result.split("```python")[1].split("```")[0]
            lang = ProgrammingLanguage.PYTHON3
            sub = LeetCodeSubmission(
                code=code,
                lang=lang,
                question_id=problem_id,
                question_slug=problem_slug,
            )

            env = LeetCodeEnv()

            status, reward, done, submission_result = env.step(sub)
            success_count += reward
            print(status, reward, done, submission_result)
            _log_result(reward, results, i, success_count)
        except Exception as e:
            print(f"Exception occurred = {e}")
            _log_result(False, results, i, success_count)
        break


# TODO Rename this here and in `main`
def _log_result(result, results, i, success_count):
    results[i] = result
    print("-" * 200)
    print(f"passed {success_count} out of {i+1}")
    print(f"results dict = {results}")
    print("-" * 200)


if __name__ == "__main__":
    main()
