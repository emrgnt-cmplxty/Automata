"""The `AgentToolFactory` class is responsible for creating tools from a given agent tool name."""
# TODO - Move experimental tools to a separate package
import logging
import logging.config
from typing import Any, Dict, List, Sequence, Tuple, Set

from automata.agent import AgentToolkitNames
from automata.code_parsers.py import PyReader
from automata.code_writers.py import PyCodeWriter
from automata.config.config_base import LLMProvider
from automata.core.utils import get_logging_config
from automata.tools.core.wolfram_alpha_oracle import WolframAlphaOracle
from automata.tools import Tool, UnknownToolError

logger = logging.getLogger(__name__)
logging.config.dictConfig(get_logging_config())


class AgentToolFactory:
    """The AgentToolFactory class is responsible for creating tools from a given agent tool name."""

    TOOLKIT_TYPE_TO_ARGS: Dict[AgentToolkitNames, List[Tuple[str, Any]]] = {
        AgentToolkitNames.WOLFRAM_ALPHA_ORACLE: [
            ("wolfram_alpha_oracle", WolframAlphaOracle)
        ],
        AgentToolkitNames.PY_READER: [("py_reader", PyReader)],
        AgentToolkitNames.PY_WRITER: [("py_writer", PyCodeWriter)],
        AgentToolkitNames.PY_INTERPRETER: [],
    }

    @staticmethod
    def create_tools_from_builder(
        agent_tool: AgentToolkitNames, **kwargs
    ) -> Sequence[Tool]:
        """Uses the Builder Registry to create tools from a given agent tool name."""
        from automata.singletons.toolkit_registry import (  # import here for easy mocking
            OpenAIAutomataAgentToolkitRegistry,
        )

        for builder in OpenAIAutomataAgentToolkitRegistry.get_all_builders():
            if builder.can_handle(agent_tool):
                if builder.LLM_PROVIDER == LLMProvider.OPENAI:
                    return builder(**kwargs).build_for_open_ai()
                else:
                    return builder(**kwargs).build()

        raise UnknownToolError(agent_tool.value)

    @staticmethod
    def build_tools(toolkits: List[str], **kwargs) -> List[Tool]:
        """Given a list of tools this method builds the tools and returns them."""
        tools: List[Tool] = []

        for tool_name in toolkits:
            tool_name = tool_name.strip()
            agent_tool_manager = AgentToolkitNames(tool_name)

            if agent_tool_manager is None:
                raise UnknownToolError(agent_tool_manager)

            tools.extend(
                AgentToolFactory.create_tools_from_builder(
                    agent_tool_manager, **kwargs
                )
            )

        return tools
