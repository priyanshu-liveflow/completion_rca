#!/usr/bin/env python3
"""Patch codegraphcontext to add Groovy and PowerShell language support.

Run once after installing dependencies:
    .venv/bin/python src/main/indexer/lang_support/patch_codegraphcontext.py

Prerequisites:
    - codegraphcontext installed in .venv
    - tree-sitter-groovy installed (uv pip install /path/to/tree-sitter-groovy)
    - tree-sitter-language-pack installed (has PowerShell grammar)
"""
import shutil
import sys
from pathlib import Path


def find_site_packages() -> Path:
    """Find the codegraphcontext installation."""
    for p in sys.path:
        candidate = Path(p) / "codegraphcontext"
        if candidate.exists():
            return candidate
    raise RuntimeError("codegraphcontext not found in sys.path")


def patch_language_aliases(cgc_path: Path):
    """Add groovy and powershell to LANGUAGE_ALIASES."""
    manager = cgc_path / "utils" / "tree_sitter_manager.py"
    content = manager.read_text()
    changed = False

    if '"groovy": "groovy"' not in content:
        content = content.replace(
            '"css": "css",',
            '"css": "css",\n    "groovy": "groovy",'
        )
        changed = True

    if '"powershell": "powershell"' not in content:
        content = content.replace(
            '"groovy": "groovy",',
            '"groovy": "groovy",\n    "powershell": "powershell",\n    "ps1": "powershell",'
        )
        changed = True

    # Add to pack names if missing
    if '"groovy": "groovy"' not in content.split("LANGUAGE_PACK_NAMES")[-1] if "LANGUAGE_PACK_NAMES" in content else True:
        if "LANGUAGE_PACK_NAMES" in content and '"groovy"' not in content.split("LANGUAGE_PACK_NAMES")[1].split("}")[0]:
            content = content.replace(
                '"c_sharp": "csharp",',
                '"c_sharp": "csharp",\n    "groovy": "groovy",\n    "powershell": "powershell",'
            )
            changed = True

    # Add grammar override for groovy (uses murtaza64's grammar, not language-pack)
    override = '''

# --- Language grammar overrides (Groovy + PowerShell) ---
_original_load = _load_tree_sitter_dependencies

def _load_tree_sitter_dependencies_with_overrides():
    L, P, orig_get = _original_load()
    def get_with_overrides(name):
        if name == 'groovy':
            import tree_sitter_groovy as _tsg
            return L(_tsg.language())
        return orig_get(name)
    return L, P, get_with_overrides

_load_tree_sitter_dependencies = _load_tree_sitter_dependencies_with_overrides
_Language = None
_Parser = None
_get_language = None
# --- End overrides ---
'''
    if "grammar overrides" not in content:
        content += override
        changed = True

    if changed:
        manager.write_text(content)
    print("  ✓ LANGUAGE_ALIASES patched (groovy, powershell)")


def patch_graph_builder(cgc_path: Path):
    """Add .groovy and .ps1 to the parsers dict and remove .ps1 from generic."""
    builder = cgc_path / "tools" / "graph_builder.py"
    content = builder.read_text()
    changed = False

    if '".groovy": "groovy"' not in content:
        content = content.replace(
            '".css": "css",',
            '".css": "css",\n            ".groovy": "groovy",'
        )
        changed = True

    if '".ps1": "powershell"' not in content:
        content = content.replace(
            '".groovy": "groovy",',
            '".groovy": "groovy",\n            ".ps1": "powershell",'
        )
        changed = True

    # Remove .ps1 from generic extensions so it gets parsed properly
    if '".ps1"' in content.split("_GENERIC_EXTENSIONS")[1].split("}")[0] if "_GENERIC_EXTENSIONS" in content else False:
        content = content.replace('".ps1", ', '')
        changed = True

    if changed:
        builder.write_text(content)
    print("  ✓ graph_builder patched (.groovy, .ps1)")


def patch_tree_sitter_parser(cgc_path: Path):
    """Add groovy and powershell elif blocks to TreeSitterParser.__init__."""
    parser_file = cgc_path / "tools" / "tree_sitter_parser.py"
    content = parser_file.read_text()

    if "GroovyTreeSitterParser" in content:
        print("  ✓ tree_sitter_parser already patched")
        return

    # Insert after the CSS block
    css_block_end = 'self.language_specific_parser = CSSTreeSitterParser(self)'
    insertion = '''
        elif self.language_name == "groovy":
            from .languages.groovy import GroovyTreeSitterParser
            self.language_specific_parser = GroovyTreeSitterParser(self)
        elif self.language_name == "powershell":
            from .languages.powershell import PowerShellTreeSitterParser
            self.language_specific_parser = PowerShellTreeSitterParser(self)'''

    content = content.replace(css_block_end, css_block_end + insertion)
    parser_file.write_text(content)
    print("  ✓ tree_sitter_parser patched (groovy, powershell)")


def copy_parsers(cgc_path: Path):
    """Copy our parser files into codegraphcontext/tools/languages/."""
    lang_dir = cgc_path / "tools" / "languages"
    src_dir = Path(__file__).parent

    for lang_file in ("groovy.py", "powershell.py"):
        src = src_dir / lang_file
        dst = lang_dir / lang_file
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  ✓ {lang_file} copied to {lang_dir.name}/")
        else:
            print(f"  ✗ {lang_file} not found at {src}")


def main():
    print("Patching codegraphcontext for Groovy + PowerShell support...\n")

    cgc_path = find_site_packages()
    print(f"Found: {cgc_path}\n")

    copy_parsers(cgc_path)
    patch_language_aliases(cgc_path)
    patch_graph_builder(cgc_path)
    patch_tree_sitter_parser(cgc_path)

    print("\n✓ Done. You can now index .groovy and .ps1 files:")
    print("  codegraphcontext index /path/to/repo")


if __name__ == "__main__":
    main()
