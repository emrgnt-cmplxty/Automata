"""
Runs the symbol doc embedding process for the given symbol graph.
"""

import logging
import os
from typing import List, Optional, Union

from tqdm import tqdm

from automata.cli.cli_utils import initialize_py_module_loader
from automata.context_providers.symbol_synchronization_context import (
    SymbolProviderSynchronizationContext,
)
from automata.experimental.memory_store import SymbolDocEmbeddingHandler
from automata.llm import OpenAIEmbeddingProvider
from automata.memory_store import SymbolCodeEmbeddingHandler
from automata.singletons.dependency_factory import (
    DependencyFactory,
    dependency_factory,
)
from automata.symbol import Symbol
from automata.symbol.graph.symbol_graph import SymbolGraph
from automata.symbol.symbol_utils import get_rankable_symbols
from automata.symbol_embedding import (
    ChromaSymbolEmbeddingVectorDatabase,
    SymbolCodeEmbedding,
    SymbolDocEmbedding,
)

logger = logging.getLogger(__name__)


def initialize_providers(
    embedding_level: int,
    symbols: Optional[Union[str, List[Symbol]]] = None,
    **kwargs,
) -> tuple[SymbolDocEmbeddingHandler, list[Symbol]]:
    """Initialize the resources needed to build the doc embeddings."""

    project_name = kwargs.get("project_name") or "automata"
    initialize_py_module_loader(**kwargs)

    symbol_graph = SymbolGraph(
        os.path.join(
            DependencyFactory.DEFAULT_SCIP_FPATH, f"{project_name}.scip"
        )
    )

    if isinstance(symbols, str):
        dotpaths = parse_dotpaths(symbols)
        symbols = map_dotpaths_to_symbols(dotpaths, symbol_graph)

    code_embedding_db = ChromaSymbolEmbeddingVectorDatabase(
        project_name,
        persist_directory=DependencyFactory.DEFAULT_CODE_EMBEDDING_FPATH,
        factory=SymbolCodeEmbedding.from_args,
    )

    doc_embedding_db = ChromaSymbolEmbeddingVectorDatabase(
        project_name,
        persist_directory=DependencyFactory.DEFAULT_DOC_EMBEDDING_FPATH,
        factory=SymbolDocEmbedding.from_args,
    )

    embedding_provider = OpenAIEmbeddingProvider()

    dependency_factory.set_overrides(
        **{
            "symbol_graph": symbol_graph,
            "code_embedding_db": code_embedding_db,
            "doc_embedding_db": doc_embedding_db,
            "embedding_provider": embedding_provider,
            "disable_synchronization": True,  # We synchronzie locally
        }
    )

    if embedding_level == 3:
        raise NotImplementedError(
            "Embedding level 3 is not supported at this moment."
        )

    symbol_code_embedding_handler: SymbolCodeEmbeddingHandler = (
        dependency_factory.get("symbol_code_embedding_handler")
    )
    symbol_doc_embedding_handler: SymbolDocEmbeddingHandler = (
        dependency_factory.get("symbol_doc_embedding_handler")
    )

    with SymbolProviderSynchronizationContext() as synchronization_context:
        synchronization_context.register_provider(symbol_graph)
        synchronization_context.register_provider(
            symbol_code_embedding_handler
        )
        synchronization_context.synchronize()

    symbol_doc_embedding_handler.is_synchronized = True

    all_defined_symbols = symbol_graph.get_sorted_supported_symbols()
    filtered_symbols = sorted(
        get_rankable_symbols(all_defined_symbols), key=lambda x: x.dotpath
    )

    return symbol_doc_embedding_handler, filtered_symbols


def parse_dotpaths(dotpaths: str) -> List[str]:
    """Parses a comma-separated string of dotpaths into a list of dotpaths."""

    return [dotpath.strip() for dotpath in dotpaths.split(",")]


def map_dotpaths_to_symbols(
    dotpaths: List[str], symbol_graph: SymbolGraph
) -> List[Symbol]:
    """Maps a list of dotpaths to their corresponding Symbol objects."""

    all_symbols = symbol_graph.get_sorted_supported_symbols()
    return [symbol for symbol in all_symbols if symbol.dotpath in dotpaths]


def main(*args, **kwargs) -> str:
    """
    Update the symbol code embedding based on the specified SCIP index file.
    """

    symbol_doc_embedding_handler, filtered_symbols = initialize_providers(
        **kwargs
    )

    logger.info("Looping over filtered symbols...")
    for symbol in tqdm(filtered_symbols):
        try:
            if "automata.tests" in symbol.dotpath:
                continue
            logger.info(f"Caching embedding for {symbol}")
            symbol_doc_embedding_handler.process_embedding(symbol)
        except Exception as e:
            logger.info(f"Error {e} for symbol {symbol}")

    return "Success"
