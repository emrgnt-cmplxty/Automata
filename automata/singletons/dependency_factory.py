"""Implementation of the DependencyFactory singleton class."""
# TODO - Move experimental features to an experimental loader.
import logging
import logging.config
import os
from functools import lru_cache
from typing import Any, Dict, List, Set, Tuple

import networkx as nx

from automata.agent import AgentToolkitNames
from automata.code_parsers.py import PyReader
from automata.code_writers.py import PyCodeWriter
from automata.config import EmbeddingDataCategory
from automata.context_providers import (
    SymbolProviderRegistry,
    SymbolProviderSynchronizationContext,
)
from automata.core.base import Singleton
from automata.core.utils import get_embedding_data_fpath, get_logging_config
from automata.embedding import EmbeddingSimilarityCalculator
from automata.experimental.code_parsers import (
    PyContextHandler,
    PyContextHandlerConfig,
    PyContextRetriever,
)
from automata.experimental.memory_store import SymbolDocEmbeddingHandler
from automata.experimental.search import (
    SymbolRank,
    SymbolRankConfig,
    SymbolSearch,
)
from automata.experimental.symbol_embedding.symbol_doc_embedding_builder import (
    SymbolDocEmbeddingBuilder,
)
from automata.experimental.tools.wolfram_alpha_oracle import WolframAlphaOracle
from automata.llm import OpenAIChatCompletionProvider, OpenAIEmbeddingProvider
from automata.memory_store import SymbolCodeEmbeddingHandler
from automata.symbol import ISymbolProvider, SymbolGraph
from automata.symbol_embedding import (
    ChromaSymbolEmbeddingVectorDatabase,
    SymbolCodeEmbedding,
    SymbolCodeEmbeddingBuilder,
    SymbolDocEmbedding,
)
from automata.tools import UnknownToolError
from automata.tools.agent_tool_factory import AgentToolFactory

logger = logging.getLogger(__name__)
logging.config.dictConfig(get_logging_config())


class DependencyFactory(metaclass=Singleton):
    """Creates dependencies for input Tool construction."""

    DEFAULT_SCIP_FPATH = os.path.join(
        get_embedding_data_fpath(),
        EmbeddingDataCategory.INDICES.to_path(),
    )

    DEFAULT_CODE_EMBEDDING_FPATH = os.path.join(
        get_embedding_data_fpath(),
        EmbeddingDataCategory.CODE_EMBEDDING.to_path(),
    )

    DEFAULT_DOC_EMBEDDING_FPATH = os.path.join(
        get_embedding_data_fpath(),
        EmbeddingDataCategory.DOC_EMBEDDING.to_path(),
    )

    # Used to cache the symbol subgraph across multiple instances
    _class_cache: Dict[Tuple[str, ...], Any] = {}

    def __init__(self, **kwargs) -> None:
        """
        Keyword Args (Defaults):
            disable_synchronization (False): Disable synchronization of ISymbolProvider dependencies and created classes?
            symbol_graph_scip_fpath (DependencyFactory.DEFAULT_SCIP_FPATH): Filepath to the SCIP index file.
            code_embedding_db (ChromaSymbolEmbeddingVectorDatabase): Database responsible for code embeddings.
            doc_embedding_db (ChromaSymbolEmbeddingVectorDatabase): Database responsible for doc embeddings.
            coding_project_path (get_root_py_fpath()): Filepath to the root of the coding project.
            symbol_rank_config (SymbolRankConfig()): Configuration for the SymbolRank algorithm.
            embedding_provider (OpenAIEmbedding()): The embedding provider to use.
            llm_completion_provider (OpenAIChatCompletionProvider()): The LLM completion provider to use.
            py_retriever_doc_embedding_db (None): The doc embedding database to use for the PyContextRetriever.
            py_context_handler_config (PyContextHandlerConfig())
        }
        """
        self._instances: Dict[str, Any] = {}
        self.overrides = kwargs

    def set_overrides(self, **kwargs) -> None:
        """Sets overrides for the dependency factory."""
        if self._class_cache:
            raise ValueError(
                "Cannot set overrides after dependencies have been created."
            )

        for override_obj in kwargs.values():
            if isinstance(override_obj, ISymbolProvider) and not kwargs.get(
                "disable_synchronization", False
            ):
                self._synchronize_provider(override_obj)

        self.overrides = kwargs

    def get(self, dependency: str) -> Any:
        """
        Gets a dependency by name.
        The dependency argument corresponds to the names of the creation methods of the DependencyFactory class
        without the 'create_' prefix. For example, to get a SymbolGraph instance you'd call `get('symbol_graph')`.

        Raises:
            Exception: If the dependency is not found.
        """
        if dependency in self.overrides:
            return self.overrides[dependency]

        if dependency in self._instances:
            return self._instances[dependency]

        method_name = f"create_{dependency}"
        if not hasattr(self, method_name):
            raise ValueError(f"Dependency {dependency} not found.")

        creation_method = getattr(self, method_name)
        logger.info(f"Creating dependency {dependency}")
        instance = creation_method()
        self._instances[dependency] = instance

        # Perform synchronization
        if isinstance(instance, ISymbolProvider):
            self._synchronize_provider(instance)

        return instance

    def build_dependencies_for_tools(
        self, toolkits: List[str]
    ) -> Dict[str, Any]:
        """Builds and returns a dictionary of all dependencies required by the given list of tools."""

        # Identify all unique dependencies
        dependencies: Set[str] = set()
        for tool_name in toolkits:
            tool_name = tool_name.strip()
            agent_tool = AgentToolkitNames(tool_name)

            if agent_tool is None:
                raise UnknownToolError(agent_tool)

            for dependency_name, _ in AgentToolFactory.TOOLKIT_TYPE_TO_ARGS[
                agent_tool
            ]:
                dependencies.add(dependency_name)

        # Build dependencies
        tool_dependencies = {}
        logger.info(f"Building dependencies for toolkits {toolkits}...")
        for dependency in dependencies:
            logger.info(f"Building {dependency}...")
            tool_dependencies[dependency] = self.get(dependency)

        return tool_dependencies

    def _synchronize_provider(self, provider: ISymbolProvider) -> None:
        """Synchronize an `ISymbolProvider` instance."""

        if not self.overrides.get("disable_synchronization", False):
            with SymbolProviderSynchronizationContext() as synchronization_context:
                synchronization_context.register_provider(provider)
                synchronization_context.synchronize()

    @lru_cache()
    def create_symbol_graph(self) -> SymbolGraph:
        """
        Creates a `SymbolGraph` instance.

        Associated Keyword Args:
            symbol_graph_scip_fpath (DependencyFactory.DEFAULT_SCIP_FPATH)
        """
        return self.overrides.get(
            "symbol_graph",
            SymbolGraph(
                os.path.join(
                    DependencyFactory.DEFAULT_SCIP_FPATH, "automata.scip"
                )
            ),
        )

    @lru_cache()
    def create_subgraph(self) -> nx.DiGraph:
        """Calls the `default_rankable_subgraph` method of `SymbolGraph`."""

        symbol_graph: SymbolGraph = self.get("symbol_graph")
        return symbol_graph.default_rankable_subgraph

    @lru_cache()
    def create_symbol_rank(self) -> SymbolRank:
        """
        Creates a SymbolRank instance.

        Associated Keyword Args:
            symbol_rank_config (SymbolRankConfig())
        """

        subgraph: nx.DiGraph = self.get("subgraph")
        return SymbolRank(
            subgraph,
            self.overrides.get("symbol_rank_config", SymbolRankConfig()),
        )

    @lru_cache()
    def create_symbol_code_embedding_handler(
        self,
    ) -> SymbolCodeEmbeddingHandler:
        """
        Creates a `SymbolCodeEmbeddingHandler` instance.

        Associated Keyword Args:
            code_embedding_db (ChromaSymbolEmbeddingVectorDatabase): Database responsible for code embeddings.
            embedding_provider (OpenAIEmbedding())
        """

        code_embedding_db = self.overrides.get(
            "code_embedding_db",
            ChromaSymbolEmbeddingVectorDatabase(
                "automata",
                persist_directory=DependencyFactory.DEFAULT_CODE_EMBEDDING_FPATH,
                factory=SymbolCodeEmbedding.from_args,
            ),
        )
        embedding_provider: OpenAIEmbeddingProvider = self.overrides.get(
            "embedding_provider", OpenAIEmbeddingProvider()
        )
        embedding_builder: SymbolCodeEmbeddingBuilder = (
            SymbolCodeEmbeddingBuilder(embedding_provider)
        )

        return SymbolCodeEmbeddingHandler(code_embedding_db, embedding_builder)

    @lru_cache()
    def create_symbol_doc_embedding_handler(self) -> SymbolDocEmbeddingHandler:
        """
        Creates a `SymbolDocEmbeddingHandler` instance.

        Associated Keyword Args:
            doc_embedding_db (ChromaSymbolEmbeddingVectorDatabase): Database responsible for doc embeddings.
            embedding_provider (OpenAIEmbedding())
        """

        doc_embedding_db = self.overrides.get(
            "doc_embedding_db",
            ChromaSymbolEmbeddingVectorDatabase(
                "automata",
                persist_directory=DependencyFactory.DEFAULT_DOC_EMBEDDING_FPATH,
                factory=SymbolDocEmbedding.from_args,
            ),
        )
        embedding_provider: OpenAIEmbeddingProvider = self.overrides.get(
            "embedding_provider", OpenAIEmbeddingProvider()
        )
        llm_completion_provider: OpenAIChatCompletionProvider = (
            self.overrides.get(
                "llm_completion_provider", OpenAIChatCompletionProvider()
            )
        )
        symbol_search: SymbolSearch = self.get("symbol_search")
        handler: PyContextHandler = self.get("py_context_handler")

        embedding_builder = SymbolDocEmbeddingBuilder(
            embedding_provider, llm_completion_provider, symbol_search, handler
        )

        return SymbolDocEmbeddingHandler(doc_embedding_db, embedding_builder)

    @lru_cache()
    def create_symbol_search(self) -> SymbolSearch:
        """
        Creates a `SymbolSearch` instance.

        Associated Keyword Args:
            symbol_rank_config (SymbolRankConfig())
        """
        symbol_graph: SymbolGraph = self.get("symbol_graph")
        symbol_rank_config: SymbolRankConfig = self.overrides.get(
            "symbol_rank_config", SymbolRankConfig()
        )
        symbol_code_embedding_handler: SymbolCodeEmbeddingBuilder = self.get(
            "symbol_code_embedding_handler"
        )
        embedding_similarity_calculator: EmbeddingSimilarityCalculator = (
            self.get("embedding_similarity_calculator")
        )
        return SymbolSearch(
            symbol_graph,
            symbol_rank_config,
            # FIXME - Fix this type ignore
            symbol_code_embedding_handler,  # type: ignore
            embedding_similarity_calculator,
        )

    @lru_cache()
    def create_py_context_retriever(self) -> PyContextRetriever:
        """Creates PyContextRetriever for use in all dependencies."""
        return PyContextRetriever()

    def create_py_context_handler(self) -> PyContextHandler:
        """
        Creates PyContextHandler for use in all dependencies.

        Associated Keyword Args:
            py_context_handler_config (PyContextHandlerConfig())
        """

        py_context_handler_config = self.overrides.get(
            "py_context_handler_config", PyContextHandlerConfig()
        )
        retriever = self.get("py_context_retriever")
        symbol_search = self.get("symbol_search")
        return PyContextHandler(
            py_context_handler_config, retriever, symbol_search
        )

    @lru_cache()
    def create_embedding_similarity_calculator(
        self,
    ) -> EmbeddingSimilarityCalculator:
        """
        Associated Keyword Args:
            embedding_provider (OpenAIEmbedding())
        """
        embedding_provider: OpenAIEmbeddingProvider = self.overrides.get(
            "embedding_provider", OpenAIEmbeddingProvider()
        )
        return EmbeddingSimilarityCalculator(embedding_provider)

    @lru_cache()
    def create_py_reader(self) -> PyReader:
        """Creates `PyReader` for use in all dependencies."""
        return PyReader()

    @lru_cache()
    def create_py_writer(self) -> PyCodeWriter:
        """Creates `PyCodeWriter` for use in all dependencies."""
        return PyCodeWriter(self.get("py_reader"))

    @lru_cache()
    def create_wolfram_alpha_oracle(self) -> WolframAlphaOracle:
        """Creates and returns an instance of WolframAlphaOracle."""
        return WolframAlphaOracle()

    def reset(self) -> None:
        """Resets the entire dependency cache."""

        SymbolProviderRegistry.reset()
        self._class_cache = {}
        self._instances = {}
        self.overrides = {}

        # Clear the LRU caches
        for attr_name in dir(self):
            if attr_name.startswith("create_"):
                attr_value = getattr(self, attr_name)
                if callable(attr_value) and hasattr(attr_value, "cache_clear"):
                    attr_value.cache_clear()


# sourcery skip: avoid-global-variables
dependency_factory = DependencyFactory()
