import os
import uuid
from enum import Enum
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel

from automata.core.base.tool import Tool


class ConfigCategory(Enum):
    """
    A class to represent the different categories of configuration options
    """

    AGENT = "agent"
    PROMPT = "prompt"
    SYMBOL = "symbol"
    INSTRUCTION = "instruction_configs"


class InstructionConfigVersion(Enum):
    """
    InstructionConfigVersion: Enum of instruction versions.
    Corresponds to the name of the yaml file in automata/configs/instruction_configs.
    """

    AGENT_INTRODUCTION = "agent_introduction"


class AvailableAgentTool(Enum):
    PY_READER = "py_reader"
    PY_WRITER = "py_writer"
    SYMBOL_SEARCH = "symbol_search"
    CONTEXT_ORACLE = "context_oracle"


class AgentConfigName(Enum):
    """
    AgentConfigName: Enum of agent config names.
    Corresponds to the name of the yaml file in automata/config/agent/
    """

    # Helper Configs
    DEFAULT = "default"
    TEST = "test"
    # The initializer is a dummy agent used to spoof the initial message context.
    AUTOMATA_INITIALIZER = "automata_initializer"

    # Production Configs
    AUTOMATA_READER = "automata_reader"
    AUTOMATA_WRITER = "automata_writer"
    AUTOMATA_READER_AND_WRITER = "automata_reader_and_writer"
    AUTOMATA_MAIN = "automata_main"


class AutomataAgentConfig(BaseModel):
    """
    Args:
        config_name (AgentConfigName): The config_name of the agent to use.
        tool_builders (Dict[ToolkitType, Toolkit]): A dictionary of toolkits to use.
        instructions (str): A string of instructions to execute.
        system_template (str): A string of instructions to execute.
        system_template_variables (List[str]): A list of required input variables for the instruction template.
        system_template_formatter (Dict[str, str]): A user provided dictionary of input variables and corresponding text.
        model (str): The model to use for the agent.
        stream (bool): Whether to stream the results back to the main.
        verbose (bool): Whether to print the results to stdout.
        max_iters (int): The maximum number of iterations to run.
        temperature (float): The temperature to use for the agent.
        session_id (Optional[str]): The session ID to use for the agent.
        instruction_version (InstructionConfigVersion): Config version of the introduction instruction.
    """

    class Config:
        SUPPORTED_MODELS = ["gpt-4", "gpt-3.5-turbo", "gpt-3.5-turbo-16k", "gpt-3.5-turbo-0613"]
        arbitrary_types_allowed = True

    config_name: AgentConfigName = AgentConfigName.DEFAULT
    tools: List[Tool] = []
    instructions: str = ""
    description: str = ""
    system_template: str = ""
    system_template_variables: List[str] = []
    system_template_formatter: Dict[str, str] = {}
    model: str = "gpt-4"
    stream: bool = False
    verbose: bool = False
    is_new_agent: bool = True
    max_iterations: int = 50
    temperature: float = 0.7
    session_id: Optional[str] = None
    system_instruction: Optional[str] = None
    instruction_version: InstructionConfigVersion = InstructionConfigVersion.AGENT_INTRODUCTION

    class TemplateFormatter:
        @staticmethod
        def create_default_formatter(
            config: "AutomataAgentConfig", max_default_overview_symbols: int = 100
        ) -> Dict[str, str]:
            """
            Create a default template formatter.

            Args:
                config (AutomataAgentConfig): The AutomataAgentConfig to use.

            Returns:
                Dict[str, str]: The default template formatter.

            Raises:
                NotImplementedError: If the config_name is not supported.

            TODO:
                - Consider how we might implement dependency injection across this call stack
                - Replace symbol_search with symbol_rank when it is implemented on DependencyFactory
            """
            formatter = {}
            if config.config_name == AgentConfigName.AUTOMATA_READER:
                from automata.core.agent.tool.tool_utils import DependencyFactory

                symbol_search = DependencyFactory().get("symbol_search")
                symbol_rank = symbol_search.symbol_rank
                ranks = symbol_rank.get_ranks()
                symbol_dotpaths = [
                    ".".join(symbol.dotpath.split(".")[1:])
                    for symbol, _ in ranks[:max_default_overview_symbols]
                ]
                formatter["symbol_rank_overview"] = "\n".join(sorted(symbol_dotpaths))
            elif config.config_name == AgentConfigName.AUTOMATA_MAIN:
                pass
            elif config.config_name == AgentConfigName.AUTOMATA_WRITER:
                raise NotImplementedError(
                    "AutomataWriter does not have a default template formatter."
                )

            return formatter

    def setup(self) -> None:
        """Setup the agent."""
        if not self.session_id:
            self.session_id = str(uuid.uuid4())
        if not self.system_template_formatter:
            self.system_template_formatter = (
                AutomataAgentConfig.TemplateFormatter.create_default_formatter(self)
            )
        if not self.system_instruction:
            self.system_instruction = self._formatted_prompt()

    @classmethod
    def load_automata_yaml_config(cls, config_name: AgentConfigName) -> Dict:
        """
        Loads the automata.yaml config file.

        Args:
            config_name (AgentConfigName): The config_name of the agent to use.

        Returns:
            Dict: The loaded yaml config.
        """
        file_dir_path = os.path.dirname(os.path.abspath(__file__))
        config_abs_path = os.path.join(
            file_dir_path, ConfigCategory.AGENT.value, f"{config_name.value}.yaml"
        )

        with open(config_abs_path, "r") as file:
            loaded_yaml = yaml.safe_load(file)
        loaded_yaml["config_name"] = config_name
        return loaded_yaml

    @classmethod
    def load(cls, config_name: AgentConfigName) -> "AutomataAgentConfig":
        """Loads the config for the agent."""
        if config_name == AgentConfigName.DEFAULT:
            return AutomataAgentConfig()

        loaded_yaml = cls.load_automata_yaml_config(config_name)
        return AutomataAgentConfig(**loaded_yaml)

    def _formatted_prompt(self) -> str:
        """
        Format system_template with the entries in the system_template_formatter.

        Returns:
            str: Formatted system_template string.
        """
        formatter_keys = set(self.system_template_formatter.keys())
        template_vars = set(self.system_template_variables)

        # Now check if the keys in formatter and template_vars match exactly
        if formatter_keys != template_vars:
            raise ValueError(
                f"Keys in system_template_formatter ({formatter_keys}) do not match system_template_variables ({template_vars})."
            )

        # Substitute variable placeholders in the system_template with their corresponding values
        formatted_prompt = self.system_template
        for variable, value in self.system_template_formatter.items():
            formatted_prompt = formatted_prompt.replace("{" + variable + "}", value)

        return formatted_prompt
