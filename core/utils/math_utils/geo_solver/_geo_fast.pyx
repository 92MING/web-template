# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True
"""Cython-accelerated constraint value/grad kernels for geo_solver_2d."""

from libc.math cimport sqrt

# ── PointToPointDistanceConstraint ──

cpdef double p2p_dist_value(
    double ax, double ay,
    double bx, double by,
    double target_dist,
) noexcept:
    cdef double dx = ax - bx
    cdef double dy = ay - by
    return sqrt(dx * dx + dy * dy) - target_dist


cpdef double p2p_dist_grad(
    double ax, double ay,
    double bx, double by,
    int pid,
    int ax_id, int ay_id, int bx_id, int by_id,
    int dist_id,
    bint dist_is_free,
) noexcept:
    if dist_is_free and pid == dist_id:
        return -1.0
    if pid != ax_id and pid != ay_id and pid != bx_id and pid != by_id:
        return 0.0
    cdef double dx = ax - bx
    cdef double dy = ay - by
    cdef double dist = sqrt(dx * dx + dy * dy)
    if dist < 1e-12:
        return 0.0
    if pid == ax_id:
        return dx / dist
    elif pid == ay_id:
        return dy / dist
    elif pid == bx_id:
        return -dx / dist
    elif pid == by_id:
        return -dy / dist
    return 0.0


# ── PointOnLineConstraint ──

cpdef double point_on_line_value(
    double x0, double y0,
    double x1, double y1,
    double x2, double y2,
) noexcept:
    cdef double dx = x2 - x1
    cdef double dy = y2 - y1
    cdef double length = sqrt(dx * dx + dy * dy)
    if length < 1e-12:
        return sqrt((x0 - x1) * (x0 - x1) + (y0 - y1) * (y0 - y1)) + 1.0
    return ((y2 - y1) * (x0 - x1) - (x2 - x1) * (y0 - y1)) / length


cpdef double point_on_line_grad(
    double x0, double y0,
    double x1, double y1,
    double x2, double y2,
    int pid,
    int p0x_id, int p0y_id,
    int p1x_id, int p1y_id,
    int p2x_id, int p2y_id,
) noexcept:
    if pid != p0x_id and pid != p0y_id and pid != p1x_id and pid != p1y_id and pid != p2x_id and pid != p2y_id:
        return 0.0
    cdef double dx = x2 - x1
    cdef double dy = y2 - y1
    cdef double L_sq = dx * dx + dy * dy
    cdef double L = sqrt(L_sq)
    if L < 1e-12:
        return 0.0
    cdef double N = dy * (x0 - x1) - dx * (y0 - y1)
    if pid == p0x_id:
        return dy / L
    elif pid == p0y_id:
        return -dx / L
    elif pid == p1x_id:
        return (-dy * L - N * (-dx / L)) / L_sq
    elif pid == p1y_id:
        return (dx * L - N * (-dy / L)) / L_sq
    elif pid == p2x_id:
        return (-(y0 - y1) * L - N * (dx / L)) / L_sq
    elif pid == p2y_id:
        return ((x0 - x1) * L - N * (dy / L)) / L_sq
    return 0.0


# ── PointOnLineSegmentConstraint ──

cpdef double segment_get_t(
    double px, double py,
    double x1, double y1,
    double x2, double y2,
) noexcept:
    cdef double dx = x2 - x1
    cdef double dy = y2 - y1
    cdef double len_sq = dx * dx + dy * dy
    if len_sq < 1e-24:
        return 0.5
    return ((px - x1) * dx + (py - y1) * dy) / len_sq


cpdef double segment_value(
    double px, double py,
    double x1, double y1,
    double x2, double y2,
) noexcept:
    cdef double t = segment_get_t(px, py, x1, y1, x2, y2)
    if t < 0.0:
        return -t
    if t > 1.0:
        return t - 1.0
    return 0.0


cpdef double segment_grad(
    double px, double py,
    double x1, double y1,
    double x2, double y2,
    int pid,
    int p0x_id, int p0y_id,
    int p1x_id, int p1y_id,
    int p2x_id, int p2y_id,
) noexcept:
    cdef double dx = x2 - x1
    cdef double dy = y2 - y1
    cdef double len_sq = dx * dx + dy * dy
    if len_sq < 1e-24:
        return 0.0
    cdef double num = (px - x1) * dx + (py - y1) * dy
    cdef double t = num / len_sq
    if -1e-10 <= t <= 1.0 + 1e-10:
        return 0.0
    if pid != p0x_id and pid != p0y_id and pid != p1x_id and pid != p1y_id and pid != p2x_id and pid != p2y_id:
        return 0.0
    cdef double dt, dnum, dlen_sq
    if pid == p0x_id:
        dt = dx / len_sq
    elif pid == p0y_id:
        dt = dy / len_sq
    elif pid == p1x_id:
        dnum = -dx + (px - x1) * (-1.0)
        dlen_sq = -2.0 * dx
        dt = (dnum * len_sq - num * dlen_sq) / (len_sq * len_sq)
    elif pid == p1y_id:
        dnum = -dy + (py - y1) * (-1.0)
        dlen_sq = -2.0 * dy
        dt = (dnum * len_sq - num * dlen_sq) / (len_sq * len_sq)
    elif pid == p2x_id:
        dnum = (px - x1) * 1.0
        dlen_sq = 2.0 * dx
        dt = (dnum * len_sq - num * dlen_sq) / (len_sq * len_sq)
    elif pid == p2y_id:
        dnum = (py - y1) * 1.0
        dlen_sq = 2.0 * dy
        dt = (dnum * len_sq - num * dlen_sq) / (len_sq * len_sq)
    else:
        return 0.0
    if t < 0.0:
        return -dt
    else:
        return dt


# ── PerpendicularLineConstraint ──

cpdef double perpendicular_value(
    double ax1, double ay1, double ax2, double ay2,
    double bx1, double by1, double bx2, double by2,
) noexcept:
    cdef double dxa = ax2 - ax1
    cdef double dya = ay2 - ay1
    cdef double dxb = bx2 - bx1
    cdef double dyb = by2 - by1
    cdef double len_a = sqrt(dxa * dxa + dya * dya)
    cdef double len_b = sqrt(dxb * dxb + dyb * dyb)
    if len_a < 1e-12 or len_b < 1e-12:
        return 1.0
    return (dxa * dxb + dya * dyb) / (len_a * len_b)


cpdef double perpendicular_grad(
    double ax1, double ay1, double ax2, double ay2,
    double bx1, double by1, double bx2, double by2,
    int pid,
    int ax1_id, int ay1_id, int ax2_id, int ay2_id,
    int bx1_id, int by1_id, int bx2_id, int by2_id,
) noexcept:
    if (pid != ax1_id and pid != ay1_id and pid != ax2_id and pid != ay2_id
            and pid != bx1_id and pid != by1_id and pid != bx2_id and pid != by2_id):
        return 0.0
    cdef double dxa = ax2 - ax1
    cdef double dya = ay2 - ay1
    cdef double dxb = bx2 - bx1
    cdef double dyb = by2 - by1
    cdef double la = sqrt(dxa * dxa + dya * dya)
    cdef double lb = sqrt(dxb * dxb + dyb * dyb)
    if la < 1e-12 or lb < 1e-12:
        return 0.0
    cdef double dot_ab = dxa * dxb + dya * dyb
    cdef double lab = la * lb
    cdef double d_dot, d_la, d_lb, d_lab
    if pid == ax1_id:
        d_dot = -dxb; d_la = -dxa / la; d_lb = 0.0
    elif pid == ay1_id:
        d_dot = -dyb; d_la = -dya / la; d_lb = 0.0
    elif pid == ax2_id:
        d_dot = dxb; d_la = dxa / la; d_lb = 0.0
    elif pid == ay2_id:
        d_dot = dyb; d_la = dya / la; d_lb = 0.0
    elif pid == bx1_id:
        d_dot = -dxa; d_la = 0.0; d_lb = -dxb / lb
    elif pid == by1_id:
        d_dot = -dya; d_la = 0.0; d_lb = -dyb / lb
    elif pid == bx2_id:
        d_dot = dxa; d_la = 0.0; d_lb = dxb / lb
    elif pid == by2_id:
        d_dot = dya; d_la = 0.0; d_lb = dyb / lb
    else:
        return 0.0
    d_lab = d_la * lb + la * d_lb
    return (d_dot * lab - dot_ab * d_lab) / (lab * lab)
