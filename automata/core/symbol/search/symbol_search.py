from copy import deepcopy
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import networkx as nx
import numpy as np

from automata.core.coding.py.module_loader import ModuleLoader
from automata.core.embedding.symbol_similarity import SymbolSimilarity
from automata.core.symbol.graph import SymbolGraph
from automata.core.symbol.parser import parse_symbol
from automata.core.symbol.search.rank import SymbolRank, SymbolRankConfig
from automata.core.symbol.symbol_types import Symbol, SymbolReference
from automata.core.symbol.symbol_utils import convert_to_fst_object

SymbolReferencesResult = Dict[str, List[SymbolReference]]
SymbolRankResult = List[Tuple[Symbol, float]]
SourceCodeResult = Optional[str]
ExactSearchResult = Dict[str, List[int]]


class SymbolSearch:
    """Searches for symbols in a SymbolGraph"""

    def __init__(
        self,
        symbol_graph: SymbolGraph,
        symbol_code_similarity: SymbolSimilarity,
        symbol_rank_config: SymbolRankConfig,
        code_subgraph: SymbolGraph.SubGraph,
        module_loader: ModuleLoader,
    ) -> None:
        """
        Args:
            symbol_graph (SymbolGraph): A SymbolGraph
            symbol_code_similarity (SymbolSimilarity): A SymbolSimilarity object with a code embedding handler
            symbol_rank_config (Optional[SymbolRankConfig]): A SymbolRankConfig object
            code_subgraph: A subgraph of the SymbolGraph

            TODO - We should modify SymbolSearch to receive a completed instance of SymbolRank.
        """

        if code_subgraph.parent != symbol_graph:
            raise ValueError("code_subgraph must be a subgraph of symbol_graph")

        graph_symbols = symbol_graph.get_all_available_symbols()
        embedding_symbols = symbol_code_similarity.embedding_handler.get_all_supported_symbols()
        available_symbols = set(graph_symbols).intersection(set(embedding_symbols))
        SymbolSearch.filter_graph(code_subgraph.graph, available_symbols)

        # TODO - Do we need to filter the SymbolGraph as well?
        self.symbol_graph = symbol_graph
        self.symbol_code_similarity = symbol_code_similarity
        symbol_code_similarity.set_available_symbols(available_symbols)
        self.symbol_rank = SymbolRank(code_subgraph.graph, config=symbol_rank_config)
        self.module_loader = module_loader

    def symbol_rank_search(self, query: str) -> SymbolRankResult:
        """
        Fetches the list of the SymbolRank similar symbols ordered by rank

        Args:
            query (str): The query to search for

        Returns:
            A list of tuples of the form (symbol_uri, rank)
        """
        query_vec = self.symbol_code_similarity.get_query_similarity_dict(query)
        transformed_query_vec = SymbolSearch.transform_dict_values(
            query_vec, SymbolSearch.shifted_z_score_powered
        )
        return self.symbol_rank.get_ranks(query_to_symbol_similarity=transformed_query_vec)

    def symbol_references(self, symbol_uri: str) -> SymbolReferencesResult:
        """
        Gets the list a symbol-based search

        Args:
            symbol_uri (str): The symbol to search for

        Returns:
            A dict of paths to files that contain the
                symbol and corresponding line numbers
        """
        # TODO - Add parsing upstream or here to parse references
        return self.symbol_graph.get_references_to_symbol(parse_symbol(symbol_uri))

    def retrieve_source_code_by_symbol(self, symbol_uri: str) -> SourceCodeResult:
        """
        Finds the raw text of a module, class, method, or standalone function

        Args:
            symbol_uri (str): The symbol to retrieve

        Returns:
            The raw text of the symbol or None if not found
        """
        node = convert_to_fst_object(parse_symbol(symbol_uri), self.module_loader)
        return str(node) if node else None

    def exact_search(self, pattern: str) -> ExactSearchResult:
        """
        Performs a exact search across the indexed codebase

        Args:
            pattern (str): The pattern to search for

        Returns:
            A dict of paths to files that contain the pattern and corresponding line numbers
        """
        return self._find_pattern_in_modules(pattern)

    def process_query(
        self, query: str
    ) -> Union[SymbolReferencesResult, SymbolRankResult, SourceCodeResult, ExactSearchResult,]:
        """
        Processes an NLP-formatted query and return the results of the appropriate search

        Args:
            query: The query to process

        Returns:
            The results of the search
        """
        parts = query.split()
        if len(parts) < 2:
            raise ValueError(
                "Invalid NLP query. It must have at least two parts: 'type:...' and 'query...'"
            )

        search_type = parts[0][len("type:") :].lower()
        query_remainder = " ".join(parts[1:])

        if search_type == "symbol_references":
            return self.symbol_references(query_remainder)
        elif search_type == "symbol_rank":
            return self.symbol_rank_search(query_remainder)
        elif search_type == "exact":
            return self.exact_search(query_remainder)
        elif search_type == "source":
            return self.retrieve_source_code_by_symbol(query_remainder)
        else:
            raise ValueError(f"Unknown search type: {search_type}")

    @staticmethod
    def filter_graph(graph: nx.DiGraph, available_symbols: Set[Symbol]) -> None:
        """
        Filters a graph to only contain nodes that are in the available_symbols set

        Args:
            graph: The graph to filter
            available_symbols: The set of symbols to keep
        """
        graph_nodes = deepcopy(graph.nodes())
        for symbol in graph_nodes:
            if symbol not in available_symbols:
                graph.remove_node(symbol)

    @staticmethod
    def shifted_z_score_powered(
        values: Union[List[float], np.ndarray], power: int = 3
    ) -> np.ndarray:
        """
        Compute z-score of a list of values

        Args:
            values: List of values to compute z-score for

        Returns:
            List of z-scores
        """
        if not isinstance(values, np.ndarray):
            values = np.array(values)

        mean = np.mean(values)
        std_dev = np.std(values)
        zscores = [(value - mean) / std_dev for value in values]
        return (zscores - np.min(zscores)) ** power

    @staticmethod
    def transform_dict_values(
        dictionary: Dict[Any, float], func: Callable[[List[float]], np.ndarray]
    ) -> Dict[Any, float]:
        """
        Apply a function to each value in a dictionary and return a new dictionary

        Args:
            dictionary: Dictionary to transform
            func: Function to apply to each value

        Returns:
            Dictionary with transformed values
        """
        # Apply the function to the accumulated values
        transformed_values = func([dictionary[key] for key in dictionary])

        return {key: transformed_values[i] for i, key in enumerate(dictionary)}

    def _find_pattern_in_modules(self, pattern: str) -> Dict[str, List[int]]:
        """
        Finds exact line matches for a given pattern string in all modules

        Args:
            pattern (str): The pattern string to search for

        Returns:
            Dict[str, List[int]]: A dictionary with module paths as keys and a list of line numbers as values
        """
        matches = {}
        for module_path, module in self.module_loader.items():
            if module:
                lines = module.dumps().splitlines()
                line_numbers = [i + 1 for i, line in enumerate(lines) if pattern in line.strip()]
                if line_numbers:
                    matches[module_path] = line_numbers
        return matches
