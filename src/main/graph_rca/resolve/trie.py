"""FragmentTrie — O(m) longest-prefix log template matching."""
from __future__ import annotations

import json


class _TrieNode:
    __slots__ = ('children', 'entries')

    def __init__(self):
        self.children: dict[str, _TrieNode] = {}
        self.entries: list[tuple[list[str], str, int, int]] | None = None  # (frags, fname, fid, line)


class FragmentTrie:
    """Character-level trie keyed by first static fragment. O(m) lookup."""

    def __init__(self):
        self.root = _TrieNode()
        self._size = 0

    def insert(self, key: str, fragments: list[str], fname: str, fid: int, line: int = 0):
        key = key.strip()
        if not key or len(key) < 3:
            return
        # Single-fragment: allow if distinctive (contains symbols like =, ::, --, :)
        # or long enough. Reject only trivial short words.
        if len(fragments) == 1:
            has_symbol = any(c in key for c in '=:/-#@')
            if len(key) < 10 and not has_symbol:
                return
        node = self.root
        for ch in key:
            if ch not in node.children:
                node.children[ch] = _TrieNode()
            node = node.children[ch]
        if node.entries is None:
            node.entries = []
        node.entries.append((fragments, fname, fid, line))
        self._size += 1

    def find_longest(self, text: str) -> list[tuple[list[str], str, int, int]] | None:
        """Walk trie, return entries at deepest matching node."""
        node = self.root
        best = None
        for ch in text:
            if ch not in node.children:
                break
            node = node.children[ch]
            if node.entries is not None:
                best = node.entries
        return best

    def find_and_verify(self, text: str) -> list[tuple[str, int, int]]:
        """Find longest prefix, verify remaining fragments. Returns [(fname, fid, line)]."""
        entries = self.find_longest(text)
        if not entries:
            return []
        matches = []
        for fragments, fname, fid, line in entries:
            if len(fragments) == 1:
                matches.append((fname, fid, line))
            else:
                pos = len(fragments[0])
                ok = True
                for frag in fragments[1:]:
                    idx = text.find(frag, pos)
                    if idx == -1:
                        ok = False
                        break
                    pos = idx + len(frag)
                if ok:
                    matches.append((fname, fid, line))
        return matches

    @property
    def size(self) -> int:
        return self._size

    def serialize(self) -> str:
        items = []
        self._collect(self.root, items)
        return json.dumps(items)

    def _collect(self, node: _TrieNode, items: list):
        if node.entries:
            for frags, fname, fid, line in node.entries:
                items.append([frags, fname, fid, line])
        for child in node.children.values():
            self._collect(child, items)

    @classmethod
    def deserialize(cls, data: str) -> "FragmentTrie":
        return cls.from_list(json.loads(data))

    @classmethod
    def from_list(cls, items: list) -> "FragmentTrie":
        trie = cls()
        for item in items:
            frags = item[0]
            fname = item[1]
            fid = item[2]
            line = item[3] if len(item) > 3 else 0
            if frags and frags[0]:
                trie.insert(frags[0], frags, fname, fid, line)
        return trie

    @classmethod
    def from_cache(cls, repo_name: str) -> "FragmentTrie | None":
        """Load trie from .flow_cache if available and fresh."""
        from ..index.cache import load_cache
        result = load_cache(repo_name)
        if not result:
            return None
        trie_data, meta = result
        trie = cls()
        for row in trie_data:
            frags, fname, fid = row[0], row[1], row[2]
            line = row[3] if len(row) > 3 else 0
            if frags and frags[0]:
                trie.insert(frags[0], frags, fname, fid, line or 0)
        return trie

    @classmethod
    def from_graph(cls, graph, repo_name: str) -> "FragmentTrie":
        """Build trie from all LogTemplate nodes in FalkorDB. Includes class + line."""
        result = graph.query(
            'MATCH (lt:LogTemplate)-[:EMITTED_BY]->(f:Function) '
            'OPTIONAL MATCH (c:Class)-[:CONTAINS]->(f) '
            'WHERE lt.repo_path CONTAINS $repo '
            'RETURN lt.static_fragments, COALESCE(c.name + "." + f.name, f.name), id(f), lt.line_in_function',
            params={"repo": repo_name}
        )
        trie = cls()
        if result.result_set:
            for row in result.result_set:
                frags, fname, fid = row[0], row[1], row[2]
                line = row[3] if len(row) > 3 else 0
                if frags and frags[0]:
                    trie.insert(frags[0], frags, fname, fid, line or 0)
        return trie
