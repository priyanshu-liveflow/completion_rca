"""Groovy language parser for CodeGraphContext.
Uses murtaza64/tree-sitter-groovy grammar. Extracts classes, methods, calls."""
from pathlib import Path
from typing import Dict, List, Optional


class GroovyTreeSitterParser:
    """Minimal Groovy parser that extracts classes, functions, and calls."""

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

        # First pass: detect classes and walk normally
        self._walk(root, source, classes, functions, function_calls, imports, None)

        # Second pass: detect flat class structure (class keyword + identifier as siblings)
        # and assign class_context to functions that follow
        root_children = list(root.children)
        current_class_name = None
        for i, child in enumerate(root_children):
            if child.type == "class" and i + 1 < len(root_children) and root_children[i + 1].type == "identifier":
                name = source[root_children[i + 1].start_byte:root_children[i + 1].end_byte].strip()
                name = name.split()[0] if name else None
                if name:
                    current_class_name = name
                    if not any(c["name"] == name for c in classes):
                        classes.append({
                            "name": name, "extends": None, "implements": [], "bases": [],
                            "source": "", "start_line": child.start_point[0] + 1,
                            "end_line": child.end_point[0] + 1, "line_number": child.start_point[0] + 1,
                            "path": None, "lang": "groovy", "qualified_name": None,
                        })

        # Assign class_context to functions that don't have one
        if current_class_name:
            for fn in functions:
                if not fn.get("class_context"):
                    fn["class_context"] = current_class_name

        # Handle leaked methods from command-parsed classes
        if classes and not current_class_name:
            last_class = classes[-1]["name"]
            for child in root_children:
                if child.type == "command" and not self._is_class_command(child, source):
                    fn = self._try_parse_command_method(child, source, last_class)
                    if fn and fn["name"] not in [f["name"] for f in functions]:
                        functions.append(fn)

        return {
            "path": path,
            "functions": functions,
            "classes": classes,
            "variables": [],
            "imports": imports,
            "function_calls": function_calls,
            "orm_mappings": [],
            "is_dependency": is_dependency,
            "lang": "groovy",
        }

    def _walk(self, node, source, classes, functions, calls, imports, current_class):
        if node.type == "groovy_import":
            name = self._get_qualified_name(node)
            if name:
                imports.append({"name": name, "alias": None})

        elif node.type in ("class_definition", "class"):
            cls = self._parse_class(node, source)
            if cls:
                classes.append(cls)
                # Walk class body for methods
                for child in node.children:
                    if child.type == "closure":
                        self._walk_class_body(child, source, classes, functions, calls, imports, cls["name"])
                return

        elif node.type == "command" and self._is_class_command(node, source):
            # Grammar parses some class declarations as: command(unit("class"), block("ClassName { ... }"))
            cls = self._parse_class_from_command(node, source)
            if cls:
                classes.append(cls)
                # Methods may be inside the block OR as subsequent siblings (grammar loses scope)
                for child in node.children:
                    if child.type == "block":
                        for sub in child.children:
                            if sub.type == "command":
                                fn = self._try_parse_command_method(sub, source, cls["name"])
                                if fn:
                                    functions.append(fn)
                # Also check subsequent sibling commands at same level (methods that leaked out)
                # This is handled by setting current_class for the remaining walk
                # We DON'T return here — let the walk continue with current_class set
                current_class = cls["name"]
                return  # but we DO return to avoid re-walking children

        elif node.type in ("function_definition", "function_declaration"):
            fn = self._parse_function(node, source, current_class)
            if fn:
                functions.append(fn)
                for child in node.children:
                    if child.type == "closure":
                        self._extract_calls(child, calls)
                return

        elif node.type == "juxt_function_call" or node.type == "function_call":
            call = self._parse_call(node)
            if call:
                calls.append(call)

        for child in node.children:
            self._walk(child, source, classes, functions, calls, imports, current_class)

    def _walk_class_body(self, body_node, source, classes, functions, calls, imports, current_class):
        """Walk class body handling all Groovy method patterns."""
        children = list(body_node.children)
        i = 0
        while i < len(children):
            child = children[i]

            if child.type in ("function_definition", "function_declaration"):
                fn = self._parse_function(child, source, current_class)
                if fn:
                    functions.append(fn)
                    for c in child.children:
                        if c.type == "closure":
                            self._extract_calls(c, calls)

            elif child.type == "function_call":
                # Pattern: execute(args) throws X { ... }
                # function_call is the method name + params, closure follows
                ids = [c.text.decode() for c in child.children if c.type == "identifier"]
                if ids:
                    name = ids[0]
                    # Find the closure body (may be 1-3 siblings ahead, past throws/annotations)
                    body = None
                    for j in range(i + 1, min(i + 4, len(children))):
                        if children[j].type == "closure":
                            body = children[j]
                            break
                    if body:
                        fn = {
                            "name": name,
                            "class_name": current_class,
                            "class_context": current_class,
                            "params": self._parse_params_from_arglist(child),
                            "parameters": self._parse_params_from_arglist(child),
                            "args": self._parse_params_from_arglist(child),
                            "arg_types": [],
                            "source": source[child.start_byte:body.end_byte],
                            "start_line": child.start_point[0] + 1,
                            "end_line": body.end_point[0] + 1,
                            "line_number": child.start_point[0] + 1,
                            "path": None,
                            "lang": "groovy",
                            "context": None,
                        }
                        functions.append(fn)
                        self._extract_calls(body, calls)

            elif child.type == "groovy_import":
                name = self._get_qualified_name(child)
                if name:
                    imports.append({"name": name, "alias": None})

            elif child.type == "class_definition":
                # Inner class
                cls = self._parse_class(child, source)
                if cls:
                    classes.append(cls)
                    for c in child.children:
                        if c.type == "closure":
                            self._walk_class_body(c, source, classes, functions, calls, imports, cls["name"])

            i += 1

    def _is_class_command(self, node, source) -> bool:
        """Check if a 'command' node is actually a class declaration misparsed by grammar."""
        children = list(node.children)
        if len(children) < 2:
            return False
        first = children[0]
        if first.type == "unit":
            text = source[first.start_byte:first.end_byte].strip()
            return text == "class"
        return False

    def _parse_class_from_command(self, node, source) -> Optional[Dict]:
        """Parse class from a command node: command(unit("class"), block("ClassName { ... }"))"""
        children = list(node.children)
        name = None
        for child in children:
            if child.type == "block":
                # First unit/identifier in the block is the class name
                for sub in child.children:
                    if sub.type == "unit":
                        name = source[sub.start_byte:sub.end_byte].strip()
                        break
                    elif sub.type == "identifier":
                        name = source[sub.start_byte:sub.end_byte].strip()
                        break
                break
        if not name:
            return None
        return {
            "name": name,
            "extends": None,
            "implements": [],
            "bases": [],
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "groovy",
            "qualified_name": None,
        }

    _GROOVY_KEYWORDS = frozenset(['if', 'for', 'while', 'switch', 'try', 'else', 'catch', 'finally', 'return', 'throw', 'new', 'assert'])

    def _try_parse_command_method(self, node, source, class_name) -> Optional[Dict]:
        """Try to parse a command node as a method. Methods have a block child with '{'.
        Structure: command(unit..., unit..., block(unit(func:name(...)), {, body...))"""
        block = None
        for child in node.children:
            if child.type == "block":
                has_brace = any(c.type == "{" for c in child.children)
                if has_brace:
                    block = child
                    break
        if not block:
            return None  # It's a field, not a method

        # Extract method name from the block's first unit/func child
        name = None
        for child in block.children:
            if child.type in ("unit", "func"):
                text = source[child.start_byte:child.end_byte].strip()
                paren = text.find('(')
                if paren > 0:
                    name = text[:paren].strip()
                    break
                elif text == '{':
                    continue
            elif child.type == "{":
                continue

        if not name:
            return None

        # Filter out keywords mistaken for method names
        if name in self._GROOVY_KEYWORDS:
            return None

        return {
            "name": name,
            "class_context": class_name,
            "params": [],
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "groovy",
            "context": class_name,
        }

    def _parse_class(self, node, source) -> Optional[Dict]:
        name = None
        extends = None
        for child in node.children:
            if child.type == "identifier":
                if name is None:
                    name = child.text.decode()
                elif extends is None and child.prev_sibling and child.prev_sibling.type == "extends":
                    extends = child.text.decode()
        if not name:
            return None
        return {
            "name": name,
            "extends": extends,
            "implements": [],
            "bases": [extends] if extends else [],
            "source": source[node.start_byte:node.end_byte],
            "start_line": node.start_point[0] + 1,
            "end_line": node.end_point[0] + 1,
            "line_number": node.start_point[0] + 1,
            "path": None,
            "lang": "groovy",
            "qualified_name": None,
        }

    def _parse_function(self, node, source, current_class) -> Optional[Dict]:
        name = None
        # In groovy grammar: identifiers after access_modifier/type are the name
        # The LAST identifier before parameter_list is the function name
        ids = []
        for child in node.children:
            if child.type == "identifier":
                ids.append(child.text.decode())
            elif child.type == "parameter_list":
                break
        name = ids[-1] if ids else None
        if not name:
            return None

        # Extract parameters
        params = []
        for child in node.children:
            if child.type == "parameter_list":
                params = self._parse_params(child)
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
            "lang": "groovy",
            "context": None,
        }

    def _parse_params(self, node) -> List[str]:
        params = []
        for child in node.children:
            if child.type == "parameter":
                ids = [c.text.decode() for c in child.children if c.type == "identifier"]
                if ids:
                    params.append(ids[-1])
        return params

    def _parse_params_from_arglist(self, func_call_node) -> List[str]:
        """Extract param names from a function_call's argument_list."""
        for child in func_call_node.children:
            if child.type == "argument_list":
                # argument_list text is like "(Type name, Type2 name2)"
                ids = [c.text.decode() for c in child.children if c.type == "identifier"]
                # Every other identifier is a param name (Type, name, Type2, name2)
                return ids[1::2] if len(ids) > 1 else ids
        return []

    def _parse_call(self, node) -> Optional[Dict]:
        ids = [c.text.decode() for c in node.children if c.type == "identifier"]
        if ids:
            return {"name": ids[0], "line": node.start_point[0] + 1, "line_number": node.start_point[0] + 1}
        return None

    def _extract_calls(self, node, calls):
        if node.type in ("juxt_function_call", "function_call"):
            call = self._parse_call(node)
            if call:
                calls.append(call)
        for child in node.children:
            self._extract_calls(child, calls)

    def _get_qualified_name(self, node) -> Optional[str]:
        for child in node.children:
            if child.type == "qualified_name":
                return child.text.decode()
        return None
