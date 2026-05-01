# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated span packing / hard-split scoring loops for text splitting."""

from libc.stdlib cimport abs as c_abs
from libc.math cimport ceil


cpdef list pack_spans_balanced(
    list spans,
    list span_word_counts,
    int max_word_count,
):
    """Pack pre-scored spans into balanced chunks (greedy, O(n²) scoring).

    Returns a list of (start, end) tuples.
    """
    if not spans:
        return []

    cdef int n = len(spans)
    cdef int index = 0
    cdef int remaining_wc, remaining_cc, target_wc
    cdef int current_wc, best_end, best_wc
    cdef int cursor, next_wc, current_score, best_score
    result = []

    while index < n:
        remaining_wc = 0
        for cursor in range(index, n):
            remaining_wc += <int>span_word_counts[cursor]
        if remaining_wc <= 0:
            for cursor in range(index, n):
                result.append(spans[cursor])
            break

        remaining_cc = <int>ceil(<double>remaining_wc / <double>max_word_count)
        if remaining_cc < 1:
            remaining_cc = 1
        target_wc = <int>ceil(<double>remaining_wc / <double>remaining_cc)
        if target_wc > max_word_count:
            target_wc = max_word_count
        if target_wc < 1:
            target_wc = 1

        current_wc = 0
        best_end = index
        best_wc = <int>span_word_counts[index]
        best_score = best_wc - target_wc
        if best_score < 0:
            best_score = -best_score

        for cursor in range(index, n):
            next_wc = current_wc + <int>span_word_counts[cursor]
            if cursor > index and next_wc > max_word_count:
                break
            current_wc = next_wc
            current_score = current_wc - target_wc
            if current_score < 0:
                current_score = -current_score
            if current_score < best_score or (current_score == best_score and current_wc > best_wc):
                best_end = cursor
                best_wc = current_wc
                best_score = current_score
            if current_wc >= target_wc and current_score == 0:
                break

        # spans[index][0], spans[best_end][1]
        s0 = spans[index]
        s1 = spans[best_end]
        result.append((s0[0], s1[1]))
        index = best_end + 1

    return result


cpdef list hard_split_units(
    list unit_starts,
    list unit_ends,
    list unit_word_counts,
    int max_word_count,
    int total_word_count,
):
    """Score-based hard splitting over semantic units.

    Returns a list of (start_char, end_char) tuples.
    """
    cdef int n = len(unit_starts)
    if n == 0:
        return []
    cdef int chunk_count = <int>ceil(<double>total_word_count / <double>max_word_count)
    if chunk_count < 1:
        chunk_count = 1
    cdef int target_wc = <int>ceil(<double>total_word_count / <double>chunk_count)
    if target_wc > max_word_count:
        target_wc = max_word_count
    if target_wc < 1:
        target_wc = 1

    cdef int unit_index = 0
    cdef int remaining_wc, remaining_cc, dynamic_target
    cdef int current_wc, best_idx, best_wc, best_score
    cdef int cursor, next_wc, current_score
    result = []

    while unit_index < n:
        remaining_wc = 0
        for cursor in range(unit_index, n):
            remaining_wc += <int>unit_word_counts[cursor]
        remaining_cc = <int>ceil(<double>remaining_wc / <double>max_word_count)
        if remaining_cc < 1:
            remaining_cc = 1
        dynamic_target = <int>ceil(<double>remaining_wc / <double>remaining_cc)
        if dynamic_target < target_wc:
            dynamic_target = target_wc
        if dynamic_target > max_word_count:
            dynamic_target = max_word_count

        current_wc = 0
        best_idx = unit_index
        best_wc = <int>unit_word_counts[unit_index]
        best_score = best_wc - dynamic_target
        if best_score < 0:
            best_score = -best_score

        for cursor in range(unit_index, n):
            next_wc = current_wc + <int>unit_word_counts[cursor]
            if cursor > unit_index and next_wc > max_word_count:
                break
            current_wc = next_wc
            current_score = current_wc - dynamic_target
            if current_score < 0:
                current_score = -current_score
            if current_score < best_score or (current_score == best_score and current_wc > best_wc):
                best_idx = cursor
                best_wc = current_wc
                best_score = current_score

        result.append((<int>unit_starts[unit_index], <int>unit_ends[best_idx]))
        unit_index = best_idx + 1

    return result
