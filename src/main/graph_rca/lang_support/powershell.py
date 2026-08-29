"""PowerShell language parser for CodeGraphContext.
Uses tree-sitter-language-pack powershell grammar."""
from pathlib import Path
from typing import Dict, List, Optional


class PowerShellTreeSitterParser:
    """PowerShell parser that extracts functions, classes, and calls."""

    def __init__(self, ts_parser):
        self.ts_parser = ts_parser

    def parse(self, path: Path, is_dependency: bool = False, **kwargs) -> Dict:
        source = path.read_text(errors="replace")
        tree = self.ts_parser.parser.parse(source.encode())
        root = tree.root_node

        classes = []
        functions = []
        function_calls = []
        imports = []

        self._walk(root, source, classes, functions, function_calls, imports, None)

        # Script-level: if no functions found but file has param() block, treat file as a function
        if not functions and not classes:
            for child in root.children:
                if child.type == "statement_list":
                    for stmt in child.children:
                        if stmt.type == "param_block":
                            functions.append({
                                "name": path.stem,
                                "class_name": None,
                                "class_context": None,
                                "params": self._parse_param_block(stmt),
                                "parameters": self._parse_param_block(stmt),
                                "args": self._parse_param_block(stmt),
                                "arg_types": [],
                                "source": source,
                                "start_line": 1,
                                "end_line": root.end_point[0] + 1,
                                "line_number": 1,
                                "path": None,
                                "lang": "powershell",
                                "context": None,
                            })
                            break

        return {
            "path": path,
            "functions": functions,
            "classes": classes,
            "variables": [],
            "imports": imports,
            "function_calls": function_calls,
            "orm_mappings": [],
            "is_dependency": is_dependency,
            "lang": "powershell",
        }

    def _walk(self, node, source, classes, functions, calls, imports, current_class):
        if node.type == "function_statement":
            fn = self._parse_function(node, source, current_class)
            if fn:
                functions.append(fn)
                self._extract_calls(node, calls)
                return

        elif node.type == "class_statement":
            cls = self._parse_class(node, source)
            if cls:
                classes.append(cls)
                for child in node.children:
                    if child.type == "class_method_definition":
                        fn = self._parse_class_method(child, source, cls["name"])
                        if fn:
                            functions.append(fn)
                            self._extract_calls(child, calls)
                return

        elif node.type == "command":
            call = self._parse_command_call(node)
            if call:
                calls.append(call)

        for child in node.children:
            self._walk(child, source, classes, functions, calls, imports, current_class)

    def _parse_function(self, node, source, current_class) -> Optional[Dict]:
        name = None
        for child in node.children:
            if child.type == "function_name":
                name = child.text.decode()
                break
        if not name:
            return None

        params = []
        for child in node.children:
            if child.type == "script_block":
                for sb_child in child.children:
                    if sb_child.type == "param_block":
                        params = self._parse_param_block(sb_child)
                        break

        return {
            "name": name,
            "class_name": current_class,
            "class_context": current_class,
            "params": params,
            "parameters": params,
            "args": params,
            "arg_types": [],
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "powershell",
            "context": None,
        }

    def _parse_class(self, node, source) -> Optional[Dict]:
        name = None
        bases = []
        for child in node.children:
            if child.type == "simple_name":
                if name is None:
                    name = child.text.decode()
                else:
                    bases.append(child.text.decode())
        if not name:
            return None
        return {
            "name": name,
            "extends": bases[0] if bases else None,
            "implements": [],
            "bases": bases,
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "powershell",
            "qualified_name": None,
        }

    def _parse_class_method(self, node, source, current_class) -> Optional[Dict]:
        name = None
        for child in node.children:
            if child.type == "simple_name":
                name = child.text.decode()
                break
        if not name:
            return None

        params = []
        for child in node.children:
            if child.type == "class_parameter_list":
                params = self._parse_class_params(child)
                break

        return {
            "name": name,
            "class_name": current_class,
            "class_context": current_class,
            "params": params,
            "parameters": params,
            "args": params,
            "arg_types": [],
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "powershell",
            "context": None,
        }

    def _parse_param_block(self, node) -> List[str]:
        params = []
        for child in node.children:
            if child.type == "parameter":
                for c in child.children:
                    if c.type == "variable" or c.type == "simple_variable":
                        params.append(c.text.decode().lstrip("$"))
                        break
        return params

    def _parse_class_params(self, node) -> List[str]:
        params = []
        for child in node.children:
            if child.type == "simple_name":
                params.append(child.text.decode())
        return params

    def _parse_command_call(self, node) -> Optional[Dict]:
        for child in node.children:
            if child.type == "command_name":
                name = child.text.decode()
                if not name.startswith("$"):
                    return {"name": name, "line": node.start_point[0] + 1, "line_number": node.start_point[0] + 1}
                break
        return None

    def _extract_calls(self, node, calls):
        if node.type == "command":
            call = self._parse_command_call(node)
            if call:
                calls.append(call)
        for child in node.children:
            self._extract_calls(child, calls)
