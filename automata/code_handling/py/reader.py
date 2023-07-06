from __future__ import annotations

import logging
from typing import Optional, Union

from redbaron import ClassNode, DefNode, Node, RedBaron, StringNode

from automata.navigation.py.navigation_utils import find_syntax_tree_node
from automata.singletons.py_module_loader import py_module_loader

logger = logging.getLogger(__name__)
FSTNode = Union[Node, RedBaron]


class PyReader:
    """Code retriever for fetching python code"""

    NO_RESULT_FOUND_STR = "No Result Found."

    def __init__(self) -> None:
        pass

    def get_source_code(self, module_dotpath: str, object_path: Optional[str] = None) -> str:
        """
        Gets code for a specified module, class, or function/method

        Args:
            module_dotpath (str): The path of the module in dot-separated format (e.g. 'package.module')
            object_path (Optional[str]): The path of the class, function, or method in dot-separated format
                (e.g. 'ClassName.method_name'). If None, the entire module code will be returned

        Returns:
            str: The code for the specified module, class, or function/method, or "No Result Found."
                if not found
        """
        module = py_module_loader.fetch_module(module_dotpath)
        if module:
            result = find_syntax_tree_node(module, object_path)
            if result:
                return result.dumps()

        return PyReader.NO_RESULT_FOUND_STR

    def get_docstring(self, module_dotpath: str, object_path: Optional[str]) -> str:
        """
        Gets the docstring for a specified module, class, or function/method

        Args:
            module_dotpath (str): The path of the module in dot-separated format (e.g. 'package.module')
            object_path (Optional[str]): The path of the class, function, or method in dot-separated format
                (e.g. 'ClassName.method_name'). If None, the module-level docstring will be returned

        Returns:
            str: The docstring for the specified module, class, or function/method, or "No Result Found."
                if not found
        """
        module = py_module_loader.fetch_module(module_dotpath)
        if module:
            return PyReader.get_docstring_from_node(find_syntax_tree_node(module, object_path))
        return PyReader.NO_RESULT_FOUND_STR

    def get_source_code_without_docstrings(
        self, module_dotpath: str, object_path: Optional[str]
    ) -> str:
        """
        Gets code for a specified module, class, or function/method

        Args:
            module_dotpath (str): The path of the module in dot-separated format (e.g. 'package.module')
            object_path (Optional[str]): The path of the class, function, or method in dot-separated format
                (e.g. 'ClassName.method_name'). If None, the entire module code will be returned

        Returns:
            str: The code for the specified module, class, or function/method, or "No Result Found."
                if not found
        """

        def _remove_docstrings(node: FSTNode) -> None:
            """
            Remove docstrings from the specified node, recursively

            Args:
                node: The FST node
                    to remove docstrings from
            """

            if isinstance(node, (DefNode, ClassNode, RedBaron)):
                filtered_node = node.filtered()
                if filtered_node and isinstance(filtered_node[0], StringNode):
                    index = filtered_node[0].index_on_parent
                    node.pop(index)
                child_nodes = node.find_all(lambda identifier: identifier in ("def", "class"))
                for child_node in child_nodes:
                    if child_node is not node:
                        _remove_docstrings(child_node)

        module = py_module_loader.fetch_module(module_dotpath)

        if module:
            module_copy = RedBaron(module.dumps())
            result = find_syntax_tree_node(module_copy, object_path)

            if result:
                _remove_docstrings(result)
                return result.dumps()
        return PyReader.NO_RESULT_FOUND_STR

    @staticmethod
    def get_docstring_from_node(node: Optional[FSTNode]) -> str:
        """
        Gets the docstring from the specified node

        Args:
            node: The FST node to get the docstring from
        """
        if not node:
            return PyReader.NO_RESULT_FOUND_STR

        if isinstance(node, (ClassNode, DefNode, RedBaron)):
            filtered_nodes = node.filtered()  # get rid of extra whitespace
            if isinstance(filtered_nodes[0], StringNode):
                return filtered_nodes[0].value.replace('"""', "").replace("'''", "")
        return ""

    @staticmethod
    def _create_line_number_tuples(node: FSTNode, start_line: int, start_col: int):
        """
        Creates a list of tuples of line numbers and lines from the specified node

        Args:
            node: The FST node to create the line number tuples from
            start_line: The starting line number
            start_col: The starting column number
        """
        result = []
        for i, line in enumerate(node.dumps().strip().splitlines()):
            if i == 0 and not line.startswith(" " * (start_col - 1)):
                line = " " * (start_col - 1) + line
            result.append((start_line + i, line))
        return result
