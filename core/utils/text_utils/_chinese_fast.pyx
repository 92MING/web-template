# cython: language_level=3, boundscheck=False, wraparound=False
"""Aho-Corasick–style single-pass Cantonese → Mandarin replacer.

Builds a trie from the canton→PTH dictionary (longest keys first),
then scans the text once, greedily matching the longest prefix at each
position.  This replaces the O(dict_size × text_len) linked-list
approach with O(text_len × max_key_len).
"""


cdef class _TrieNode:
    cdef dict children
    cdef str value       # replacement value if this node terminates a key
    cdef int key_len     # length of the key at this node (0 = not a terminal)

    def __cinit__(self):
        self.children = {}
        self.value = None
        self.key_len = 0


cdef class CantonTrie:
    """Trie built from an OrderedDict[str, str] (canton → mandarin)."""
    cdef _TrieNode root
    cdef int max_key_len

    def __cinit__(self):
        self.root = _TrieNode()
        self.max_key_len = 0

    cpdef void build(self, dict mapping):
        """Insert all keys from *mapping* into the trie."""
        cdef str key, val
        cdef _TrieNode node, child
        cdef Py_ssize_t i, klen
        cdef Py_UCS4 ch

        self.root = _TrieNode()
        self.max_key_len = 0
        for key, val in mapping.items():
            klen = len(key)
            if klen <= 1:
                continue   # single-char keys are excluded (matches Python version)
            if klen > self.max_key_len:
                self.max_key_len = klen
            node = self.root
            for i in range(klen):
                ch = key[i]
                child = <_TrieNode>node.children.get(ch)
                if child is None:
                    child = _TrieNode()
                    node.children[ch] = child
                node = child
            node.value = val
            node.key_len = klen

    cpdef str replace(self, str text):
        """Return *text* with all canton phrases replaced (longest match wins)."""
        cdef Py_ssize_t n = len(text)
        if n == 0:
            return text

        cdef list parts = []
        cdef Py_ssize_t i = 0
        cdef Py_ssize_t cursor = 0     # start of un-copied region
        cdef Py_ssize_t j, best_len
        cdef str best_val
        cdef _TrieNode node
        cdef Py_UCS4 ch

        while i < n:
            node = self.root
            ch = text[i]
            if ch not in node.children:
                i += 1
                continue

            # Try to match the longest key starting at position i
            best_len = 0
            best_val = None
            j = i
            while j < n:
                ch = text[j]
                if ch not in node.children:
                    break
                node = <_TrieNode>node.children[ch]
                j += 1
                if node.key_len > 0:  # terminal node
                    best_len = node.key_len
                    best_val = node.value

            if best_len > 0:
                # Emit text before the match
                if i > cursor:
                    parts.append(text[cursor:i])
                parts.append(best_val)
                i += best_len
                cursor = i
            else:
                i += 1

        if cursor == 0:
            return text
        if cursor < n:
            parts.append(text[cursor:])
        return ''.join(parts)
