# cython: language_level=3, boundscheck=False, wraparound=False
"""Cython-accelerated nested-dict sort-key extraction for ORM storage routes."""


cpdef tuple nested_sort_value(dict document, str dotted_field):
    """Traverse *document* along a dot-separated field path and return
    ``(priority, value)`` suitable for use as a sort key.

    Returns ``(1, None)`` when the path cannot be resolved, and
    ``(0, value)`` otherwise.
    """
    cdef object current = document
    cdef str part
    cdef list parts = dotted_field.split('.') if dotted_field else []

    for part in parts:
        if not part:
            continue
        if isinstance(current, dict) and part in current:
            current = (<dict>current).get(part)
        else:
            return (1, None)

    if current is None:
        return (1, None)
    if isinstance(current, bool):
        return (0, <int>current)
    if isinstance(current, (int, float, str)):
        return (0, current)
    # Fallback: coerce to string for comparison stability
    return (0, str(current))
