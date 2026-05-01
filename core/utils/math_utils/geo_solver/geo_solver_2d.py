"""2D Geometry Constraint Solver, for defining and solving geometric problems."""
import io
import os
import re
import math
import logging
import warnings
import numpy as np
import matplotlib
import matplotlib.pyplot as plt

from functools import cached_property
from dataclasses import dataclass, field
from abc import abstractmethod, ABC
from collections import defaultdict
from scipy.optimize import OptimizeResult
from typing import TypeAlias, Union, Literal, Sequence, no_type_check, Any, overload, ClassVar
from pathlib import Path

from matplotlib.axes import Axes
from matplotlib.patches import Circle as pltCircle, Arc as pltArc

from ...build_utils import build_cython as _build_cython

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
_logger = logging.getLogger(__name__)

# ── Cython-accelerated kernels (optional, falls back to pure Python) ──
_geo_fast = _build_cython(Path(os.path.join(os.path.dirname(__file__), '_geo_fast.pyx')))
_c_p2p_dist_value = _geo_fast.p2p_dist_value
_c_p2p_dist_grad = _geo_fast.p2p_dist_grad
_c_point_on_line_value = _geo_fast.point_on_line_value
_c_point_on_line_grad = _geo_fast.point_on_line_grad
_c_segment_get_t = _geo_fast.segment_get_t
_c_segment_value = _geo_fast.segment_value
_c_segment_grad = _geo_fast.segment_grad
_c_perpendicular_value = _geo_fast.perpendicular_value
_c_perpendicular_grad = _geo_fast.perpendicular_grad
_logger.debug("geo_solver_2d: Cython kernels loaded.")

# region constraints
class Constraint:
    """
    Base class for all constraints.

    Design:
        - value(): the signed residual (0 when satisfied).
        - error(): ALWAYS value()**2 — provides smooth gradients everywhere.
        - weight: multiplier on error() for balancing heterogeneous constraints.
        - precondition(): analytic adjustment of free parameters to approximately
          satisfy this constraint. Called during Problem.precondition().
    """
    
    primitives: list["Primitive"]
    weight: float

    def __init__(self, primitives: Sequence["Primitive"], weight: float = 1.0):
        self.primitives = list(primitives)
        self.weight = weight

    def __str__(self):
        return f"{self.__class__.__name__}(current={self.value()}, error={self.error()})"

    def __repr__(self):
        return f"<{self.__class__.__name__}@{hex(id(self))}>"
    
    @property
    def points(self)->list["Point"]:
        """The points associated with the primitives associated with this constraint."""
        points = []
        for primitive in self.primitives:
            points.extend(primitive.points)
        return points

    @property
    def params(self)->set:
        """The parameters associated with the points within this constraint."""
        params = set()
        for point in self.points:
            params.update(point.params)
        return params

    @abstractmethod
    def value(self)->float:
        """The current value of the constrained parameter(s)."""
        raise NotImplementedError

    def grad(self, param: "FreeParam") -> float:
        """Analytical partial derivative ∂value/∂param.
        
        Subclasses should override this for each relevant parameter.
        The default implementation uses finite differences as a fallback.
        """
        step = 1e-7
        old = param.value
        param.value = old + step
        v_plus = self.value()
        param.value = old - step
        v_minus = self.value()
        param.value = old
        return (v_plus - v_minus) / (2 * step)

    def error(self)->float:
        """Squared residual — uniform across all constraint types."""
        v = self.value()
        return self.weight * v * v

    def precondition(self, problem: "Problem2D"):
        """
        Analytically adjust free parameters to approximately satisfy this constraint.
        Override in subclasses. `fixed_point_names` tells which points are pinned.
        Default: no-op.
        """
        pass

    def project(self, problem: "Problem2D"):
        """
        Fast manifold projection: snap constrained points back onto this
        constraint's manifold (e.g. circle, line) without full solving.
        
        Called inside the objective function during optimization so the
        optimizer effectively searches on the constraint manifold, reducing
        effective DOF and improving convergence.
        
        Override in subclasses where a cheap analytic projection exists.
        Default: no-op (constraint is handled purely by the optimizer).
        """
        pass

class PointToPointDistanceConstraint(Constraint):
    """Constrain the distance between two points to a target value."""
    
    distance: "float|FreeParam"

    def __init__(self, point_a: "Point", point_b: "Point", distance: "float|FreeParam", weight: float = 1.0):
        super().__init__([point_a, point_b], weight)
        self.distance = distance

    @property
    def point_a(self) -> "Point":
        return self.primitives[0]   # type: ignore

    @property
    def point_b(self) -> "Point":
        return self.primitives[1]   # type: ignore

    def value(self):
        ax_v = self.point_a.params[0].value
        ay_v = self.point_a.params[1].value
        bx_v = self.point_b.params[0].value
        by_v = self.point_b.params[1].value
        d = self.distance.value if isinstance(self.distance, FreeParam) else self.distance
        return _c_p2p_dist_value(ax_v, ay_v, bx_v, by_v, d)
        
    def grad(self, param: "FreeParam") -> float:
        ax, ay = self.point_a.params[0], self.point_a.params[1]
        bx, by = self.point_b.params[0], self.point_b.params[1]
        pid = param.id
        dist_is_free = isinstance(self.distance, FreeParam)
        return _c_p2p_dist_grad(
            ax.value, ay.value, bx.value, by.value,
            pid, ax.id, ay.id, bx.id, by.id,
            self.distance.id if dist_is_free else -1, dist_is_free, # type: ignore
        )
        
    def precondition(self, problem: "Problem2D"):
        """Project the free point onto the circle of radius=distance centered at the fixed point."""
        fixed = problem.fixed_point_names
        a_fixed = self.point_a.name in fixed
        b_fixed = self.point_b.name in fixed
        if a_fixed and b_fixed:
            return
        # Determine which point to move
        if a_fixed:
            moving, anchor = self.point_b, self.point_a
        elif b_fixed:
            moving, anchor = self.point_a, self.point_b
        else:
            # Both free — move point_a toward/away from point_b
            moving, anchor = self.point_a, self.point_b

        target_dist = self.distance.value if isinstance(self.distance, FreeParam) else self.distance
        dx = moving.x - anchor.x
        dy = moving.y - anchor.y
        cur_dist = np.sqrt(dx * dx + dy * dy)
        if cur_dist < 1e-12:
            angle = np.random.uniform(0, 2 * np.pi)
            moving.x = anchor.x + target_dist * np.cos(angle)
            moving.y = anchor.y + target_dist * np.sin(angle)
        else:
            scale = target_dist / cur_dist
            moving.x = anchor.x + dx * scale
            moving.y = anchor.y + dy * scale

    def project(self, problem: "Problem2D"):
        """Project moving point onto the circle/sphere defined by anchor + distance."""
        fixed = problem.fixed_point_names
        a_fixed = self.point_a.name in fixed
        b_fixed = self.point_b.name in fixed
        if a_fixed and b_fixed:
            return
        if b_fixed and not a_fixed:
            moving, anchor = self.point_a, self.point_b
        elif a_fixed and not b_fixed:
            moving, anchor = self.point_b, self.point_a
        else:
            return  # both free — don't project, let optimizer handle it
        r = self.distance.value if isinstance(self.distance, FreeParam) else self.distance
        dx = moving.x - anchor.x
        dy = moving.y - anchor.y
        dist = np.sqrt(dx * dx + dy * dy)
        if dist < 1e-12:
            angle = np.random.uniform(0, 2 * np.pi)
            moving.params[0].value = anchor.x + r * np.cos(angle)
            moving.params[1].value = anchor.y + r * np.sin(angle)
        else:
            scale = r / dist
            moving.params[0].value = anchor.x + dx * scale
            moving.params[1].value = anchor.y + dy * scale

class PointOnLineConstraint(Constraint):
    """
    Constrain a point to lie on an INFINITE line (not a segment).
    
    Uses the signed perpendicular distance from point to the line through
    line.start and line.end. This is smooth and differentiable everywhere
    (as long as the line has nonzero length).
    """

    def __init__(self, point: "Point", line: "Line", weight: float = 1.0):
        super().__init__([point, line], weight)

    @property
    def point(self) -> "Point":
        return self.primitives[0]   # type: ignore

    @property
    def line(self) -> "Line":
        return self.primitives[1]   # type: ignore

    def value(self):
        """Signed perpendicular distance from point to infinite line."""
        x0 = self.point.params[0].value
        y0 = self.point.params[1].value
        x1 = self.line.start.params[0].value
        y1 = self.line.start.params[1].value
        x2 = self.line.end.params[0].value
        y2 = self.line.end.params[1].value
        return _c_point_on_line_value(x0, y0, x1, y1, x2, y2)
        
    def grad(self, param: "FreeParam") -> float:
        """Analytical gradient of signed perpendicular distance."""
        p0x, p0y = self.point.params[0], self.point.params[1]
        p1x, p1y = self.line.start.params[0], self.line.start.params[1]
        p2x, p2y = self.line.end.params[0], self.line.end.params[1]
        pid = param.id
        return _c_point_on_line_grad(
            p0x.value, p0y.value, p1x.value, p1y.value, p2x.value, p2y.value,
            pid, p0x.id, p0y.id, p1x.id, p1y.id, p2x.id, p2y.id,
        )

    def precondition(self, problem: "Problem2D"):
        """Project point onto the infinite line."""
        fixed = problem.fixed_point_names
        pt_fixed = self.point.name in fixed
        
        x0, y0 = self.point.x, self.point.y
        x1, y1 = self.line.start.x, self.line.start.y
        x2, y2 = self.line.end.x, self.line.end.y
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy

        if length_sq < 1e-12:
            return

        if not pt_fixed:
            # Project point onto line
            t = ((x0 - x1) * dx + (y0 - y1) * dy) / length_sq
            self.point.x = x1 + t * dx
            self.point.y = y1 + t * dy

    def project(self, problem: "Problem2D"):
        """Project point onto the infinite line."""
        if self.point.name in problem.fixed_point_names:
            return
        x0, y0 = self.point.x, self.point.y
        x1, y1 = self.line.start.x, self.line.start.y
        x2, y2 = self.line.end.x, self.line.end.y
        dx, dy = x2 - x1, y2 - y1
        length_sq = dx * dx + dy * dy
        if length_sq < 1e-12:
            return
        t = ((x0 - x1) * dx + (y0 - y1) * dy) / length_sq
        self.point.x = x1 + t * dx
        self.point.y = y1 + t * dy

# ── Module-level helpers for topology-aware orientation selection ──

def _map_pi(angle: float) -> float:
    """Map an angle (radians) into the range (-π, π]."""
    return (angle + np.pi) % (2 * np.pi) - np.pi

def _check_within_line_global(line: "Line") -> bool:
    """Check within-line requirements on a single line (t ∈ [0, 1]).
    
    Returns True if every point registered in ``line._within_line_points``
    has a parametric projection t ∈ [-0.05, 1.05] (small tolerance for
    numerical imprecision during precondition).
    """
    within = getattr(line, '_within_line_points', set())
    if not within:
        return True
    x1 = line.start.params[0].value
    y1 = line.start.params[1].value
    x2 = line.end.params[0].value
    y2 = line.end.params[1].value
    dx, dy = x2 - x1, y2 - y1
    len_sq = dx * dx + dy * dy
    if len_sq < 1e-24:
        return False
    for prim in line.problem.primitives.values():
        if hasattr(prim, 'x') and prim.name in within:
            px = prim.params[0].value
            py = prim.params[1].value
            t = ((px - x1) * dx + (py - y1) * dy) / len_sq
            if t < -0.05 or t > 1.05:  # small tolerance
                return False
    return True

class PointOnLineSegmentConstraint(Constraint):
    """
    Constrain a point to lie WITHIN the line segment (between start and end).
    
    The projection parameter ``t`` of the point onto the line must satisfy
    ``0 ≤ t ≤ 1``.  The value function returns the *spatial distance*
    by which the point overshoots the segment, i.e. ``excess_t * length``.
    This makes the penalty scale-invariant and comparable to other spatial
    constraints (like ``PointOnLineConstraint``).
    
    This constraint should be used together with ``PointOnLineConstraint``
    (which constrains the point to the *infinite* line).  Together they
    constrain the point to the *segment*.
    """

    def __init__(self, point: "Point", line: "Line", weight: float = 1.0):
        super().__init__([point, line], weight)

    @property
    def point(self) -> "Point":
        return self.primitives[0]   # type: ignore

    @property
    def line(self) -> "Line":
        return self.primitives[1]   # type: ignore

    def _get_t(self) -> float:
        """Compute projection parameter t along the line direction."""
        px = self.point.params[0].value
        py = self.point.params[1].value
        x1 = self.line.start.params[0].value
        y1 = self.line.start.params[1].value
        x2 = self.line.end.params[0].value
        y2 = self.line.end.params[1].value
        return _c_segment_get_t(px, py, x1, y1, x2, y2)
        
    def value(self) -> float:
        """Returns 0 when t ∈ [0, 1], positive violation otherwise."""
        px = self.point.params[0].value
        py = self.point.params[1].value
        x1 = self.line.start.params[0].value
        y1 = self.line.start.params[1].value
        x2 = self.line.end.params[0].value
        y2 = self.line.end.params[1].value
        return _c_segment_value(px, py, x1, y1, x2, y2)
        
    def grad(self, param: "FreeParam") -> float:
        """Gradient of segment constraint."""
        p0x, p0y = self.point.params[0], self.point.params[1]
        p1x, p1y = self.line.start.params[0], self.line.start.params[1]
        p2x, p2y = self.line.end.params[0], self.line.end.params[1]
        pid = param.id
        return _c_segment_grad(
            p0x.value, p0y.value, p1x.value, p1y.value, p2x.value, p2y.value,
            pid, p0x.id, p0y.id, p1x.id, p1y.id, p2x.id, p2y.id,
        )
        
    def precondition(self, problem: "Problem2D"):
        """Clamp the point's projection parameter into [0, 1]."""
        if self.point.name in problem.fixed_point_names:
            return
        x1 = self.line.start.params[0].value
        y1 = self.line.start.params[1].value
        x2 = self.line.end.params[0].value
        y2 = self.line.end.params[1].value
        dx, dy = x2 - x1, y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq < 1e-24:
            return
        px = self.point.params[0].value
        py = self.point.params[1].value
        t = ((px - x1) * dx + (py - y1) * dy) / len_sq
        if t < 0:
            t = 0.0
        elif t > 1:
            t = 1.0
        else:
            return  # already inside
        self.point.x = x1 + t * dx
        self.point.y = y1 + t * dy

    def project(self, problem: "Problem2D"):
        """Same as precondition — clamp into segment."""
        self.precondition(problem)

class PerpendicularLineConstraint(Constraint):
    """Constrain two lines to be perpendicular (normalized dot product = 0).
    
    The constraint is direction-independent: it is satisfied when the lines
    are at 90° *or* -90° (which are geometrically identical for unoriented
    lines).  The precondition is topology-aware: when either line has
    ``_within_line_points``, both candidate perpendicular directions are
    tried and the one that keeps segment-constrained points inside their
    segments is preferred.
    """

    def __init__(self, line_a: "Line", line_b: "Line", weight: float = 1.0):
        super().__init__([line_a, line_b], weight)

    @property
    def line_a(self) -> "Line":
        return self.primitives[0]   # type: ignore

    @property
    def line_b(self) -> "Line":
        return self.primitives[1]   # type: ignore

    def value(self):
        """
        Normalized dot product of direction vectors (cos of angle between them).
        Should be zero for perpendicular lines. Range: [-1, 1].
        """
        ax1 = self.line_a.start.params[0].value; ay1 = self.line_a.start.params[1].value
        ax2 = self.line_a.end.params[0].value;   ay2 = self.line_a.end.params[1].value
        bx1 = self.line_b.start.params[0].value; by1 = self.line_b.start.params[1].value
        bx2 = self.line_b.end.params[0].value;   by2 = self.line_b.end.params[1].value
        return _c_perpendicular_value(ax1, ay1, ax2, ay2, bx1, by1, bx2, by2)
        
    def grad(self, param: "FreeParam") -> float:
        """Gradient of normalized dot product: cos(θ) = dot(a,b)/(|a|*|b|)"""
        a_params = [self.line_a.start.params[0], self.line_a.start.params[1],
                     self.line_a.end.params[0], self.line_a.end.params[1]]
        b_params = [self.line_b.start.params[0], self.line_b.start.params[1],
                     self.line_b.end.params[0], self.line_b.end.params[1]]
        pid = param.id
        return _c_perpendicular_grad(
            a_params[0].value, a_params[1].value, a_params[2].value, a_params[3].value,
            b_params[0].value, b_params[1].value, b_params[2].value, b_params[3].value,
            pid,
            a_params[0].id, a_params[1].id, a_params[2].id, a_params[3].id,
            b_params[0].id, b_params[1].id, b_params[2].id, b_params[3].id,
        )
        
    def precondition(self, problem: "Problem2D"):
        """Rotate line_b's free endpoint to satisfy the perpendicular constraint.
        
        When either line has ``_within_line_points``, both perpendicular
        directions (+90° and -90° from line_a) are tested and the one that
        keeps within-line points inside their segments is chosen.
        """
        fixed = problem.fixed_point_names
        # Determine which endpoints are free
        b_pts_fixed = all(p.name in fixed for p in self.line_b.points)
        if b_pts_fixed:
            return

        # Compute current angle of line_a
        angle_a_rad = np.arctan2(self.line_a.dy(), self.line_a.dx())

        # Two candidate perpendicular angles
        target_pos = angle_a_rad + np.pi / 2   # +90°
        target_neg = angle_a_rad - np.pi / 2   # -90°

        length_b = self.line_b.length()
        if length_b < 1e-12:
            return

        b_start_fixed = self.line_b.start.name in fixed
        b_end_fixed = self.line_b.end.name in fixed

        # Check if topology info exists
        la_within = getattr(self.line_a, '_within_line_points', set())
        lb_within = getattr(self.line_b, '_within_line_points', set())
        has_topology = la_within or lb_within

        if has_topology:
            target_rad = self._pick_topology_safe_perp(
                target_pos, target_neg,
                b_start_fixed, b_end_fixed, length_b, fixed
            )
        else:
            # Pick whichever is closer to the current direction of line_b
            curr_b = np.arctan2(self.line_b.dy(), self.line_b.dx())
            d_pos = abs(_map_pi(curr_b - target_pos))
            d_neg = abs(_map_pi(curr_b - target_neg))
            target_rad = target_neg if d_neg < d_pos else target_pos

        if b_start_fixed:
            self.line_b.end.x = self.line_b.start.x + length_b * np.cos(target_rad)
            self.line_b.end.y = self.line_b.start.y + length_b * np.sin(target_rad)
        elif b_end_fixed:
            self.line_b.start.x = self.line_b.end.x - length_b * np.cos(target_rad)
            self.line_b.start.y = self.line_b.end.y - length_b * np.sin(target_rad)
        else:
            # Both free — rotate around midpoint
            mx = (self.line_b.start.x + self.line_b.end.x) / 2
            my = (self.line_b.start.y + self.line_b.end.y) / 2
            half = length_b / 2
            self.line_b.start.x = mx - half * np.cos(target_rad)
            self.line_b.start.y = my - half * np.sin(target_rad)
            self.line_b.end.x = mx + half * np.cos(target_rad)
            self.line_b.end.y = my + half * np.sin(target_rad)

    def _pick_topology_safe_perp(
        self,
        target_pos: float,
        target_neg: float,
        b_start_fixed: bool,
        b_end_fixed: bool,
        length_b: float,
        fixed: set,
    ) -> float:
        """Choose between +90° and -90° based on within-line topology."""
        bsx, bsy = self.line_b.start.x, self.line_b.start.y
        bex, bey = self.line_b.end.x, self.line_b.end.y

        def _simulate(target_rad: float) -> bool:
            if b_start_fixed:
                self.line_b.end.x = self.line_b.start.x + length_b * np.cos(target_rad)
                self.line_b.end.y = self.line_b.start.y + length_b * np.sin(target_rad)
            elif b_end_fixed:
                self.line_b.start.x = self.line_b.end.x - length_b * np.cos(target_rad)
                self.line_b.start.y = self.line_b.end.y - length_b * np.sin(target_rad)
            else:
                mx = (bsx + bex) / 2
                my = (bsy + bey) / 2
                half = length_b / 2
                self.line_b.start.x = mx - half * np.cos(target_rad)
                self.line_b.start.y = my - half * np.sin(target_rad)
                self.line_b.end.x = mx + half * np.cos(target_rad)
                self.line_b.end.y = my + half * np.sin(target_rad)
            return _check_within_line_global(self.line_a) and _check_within_line_global(self.line_b)

        pos_ok = _simulate(target_pos)
        self.line_b.start.x, self.line_b.start.y = bsx, bsy
        self.line_b.end.x, self.line_b.end.y = bex, bey

        neg_ok = _simulate(target_neg)
        self.line_b.start.x, self.line_b.start.y = bsx, bsy
        self.line_b.end.x, self.line_b.end.y = bex, bey

        if pos_ok and not neg_ok:
            return target_pos
        if neg_ok and not pos_ok:
            return target_neg

        # Both ok or both bad — pick closer to current direction
        curr_b = np.arctan2(self.line_b.dy(), self.line_b.dx())
        d_pos = abs(_map_pi(curr_b - target_pos))
        d_neg = abs(_map_pi(curr_b - target_neg))
        return target_neg if d_neg < d_pos else target_pos

class LineHorizontalConstraint(Constraint):
    """Constrain a line to be horizontal (dy = 0)."""

    def __init__(self, line: "Line", weight: float = 1.0):
        super().__init__([line], weight)

    @property
    def line(self) -> "Line":
        return self.primitives[0]   # type: ignore

    def value(self):
        return self.line.end.y - self.line.start.y

    def grad(self, param: "FreeParam") -> float:
        if param.id == self.line.end.params[1].id:
            return 1.0
        elif param.id == self.line.start.params[1].id:
            return -1.0
        return 0.0

    def precondition(self, problem: "Problem2D"):
        fixed = problem.fixed_point_names
        s_fixed = self.line.start.name in fixed
        e_fixed = self.line.end.name in fixed
        if s_fixed and e_fixed:
            return
        if s_fixed:
            self.line.end.y = self.line.start.y
        elif e_fixed:
            self.line.start.y = self.line.end.y
        else:
            y = (self.line.start.y + self.line.end.y) / 2
            self.line.start.y = y
            self.line.end.y = y

class LineVerticalConstraint(Constraint):
    """Constrain a line to be vertical (dx = 0)."""

    def __init__(self, line: "Line", weight: float = 1.0):
        super().__init__([line], weight)

    @property
    def line(self) -> "Line":
        return self.primitives[0]   # type: ignore

    def value(self):
        return self.line.end.x - self.line.start.x

    def grad(self, param: "FreeParam") -> float:
        if param.id == self.line.end.params[0].id:
            return 1.0
        elif param.id == self.line.start.params[0].id:
            return -1.0
        return 0.0

    def precondition(self, problem: "Problem2D"):
        fixed = problem.fixed_point_names
        s_fixed = self.line.start.name in fixed
        e_fixed = self.line.end.name in fixed
        if s_fixed and e_fixed:
            return
        if s_fixed:
            self.line.end.x = self.line.start.x
        elif e_fixed:
            self.line.start.x = self.line.end.x
        else:
            x = (self.line.start.x + self.line.end.x) / 2
            self.line.start.x = x
            self.line.end.x = x

class LineAngleConstraint(Constraint):
    """
    Constrain the angle between two lines to a target value (degrees).
    
    Uses **direction-cosine** formulation (inspired by SolveSpace):
    
        value = cos(measured_angle) - cos(target_angle) = 0
    
    where ``cos(measured_angle) = (A·B) / (|A|·|B|)``.
    
    This is inherently **direction-independent**: reversing either line's
    direction vector negates both the dot product and nothing else in the
    cos formulation, so ``|cos θ|`` stays the same.  An internal ``other``
    flag selects between ``cos(target)`` (angle θ) and ``-cos(target)``
    (supplement 180°−θ), determined automatically at creation time by
    measuring the current geometry (like SolveSpace's ``ModifyToSatisfy``).
    
    value() range is [-2, 2], error() = value()² range [0, 4].
    """
    
    target_angle_deg: "float|FreeParam"

    def __init__(
        self, 
        line_a: "Line", 
        line_b: "Line", 
        angle: "float|FreeParam", 
        weight: float = 1.0,
    ):
        super().__init__([line_a, line_b], weight)
        # Normalize target to [0, 180] — the geometric angle range for
        # unoriented lines.
        if isinstance(angle, (float, int)):
            self.target_angle_deg = abs(_map_angle_about_zero(angle))
            if self.target_angle_deg > 180:
                self.target_angle_deg = 360 - self.target_angle_deg
            self._target_rad = math.radians(self.target_angle_deg)
        else:
            self.target_angle_deg = angle      # FreeParam — kept as-is
            self._target_rad = None
        # ``other`` selects the supplementary branch: when True the
        # constraint is  cos(measured) = -cos(target).
        # Determined lazily (first precondition or first value call).
        self._other: bool | None = None

    # ── helpers ──────────────────────────────────────────────────────

    @property
    def line_a(self) -> "Line":
        return self.primitives[0]   # type: ignore

    @property
    def line_b(self) -> "Line":
        return self.primitives[1]   # type: ignore

    def _get_dirs(self):
        """Return (dxa, dya, dxb, dyb) for line_a and line_b."""
        dxa = self.line_a.end.params[0].value - self.line_a.start.params[0].value
        dya = self.line_a.end.params[1].value - self.line_a.start.params[1].value
        dxb = self.line_b.end.params[0].value - self.line_b.start.params[0].value
        dyb = self.line_b.end.params[1].value - self.line_b.start.params[1].value
        return dxa, dya, dxb, dyb

    def _direction_cosine(self) -> float:
        """Return cos(measured_angle) = (A·B)/(|A|·|B|)."""
        dxa, dya, dxb, dyb = self._get_dirs()
        mag_a = math.sqrt(dxa * dxa + dya * dya)
        mag_b = math.sqrt(dxb * dxb + dyb * dyb)
        if mag_a < 1e-12 or mag_b < 1e-12:
            return 0.0
        return (dxa * dxb + dya * dyb) / (mag_a * mag_b)

    def _target_cos(self) -> float:
        """Return the target cosine value, accounting for ``other`` flag."""
        target_rad = self._target_rad if self._target_rad is not None else math.radians(
            abs(self.target_angle_deg.value) if isinstance(self.target_angle_deg, FreeParam) else abs(self.target_angle_deg)
        )
        c = math.cos(target_rad)
        if self._other:
            c = -c
        return c

    def _auto_detect_other(self):
        """Like SolveSpace's ModifyToSatisfy: measure current geometry
        and set ``_other`` so the constraint is already (approximately)
        satisfied.  This makes the solver converge from the nearest basin."""
        target_rad = self._target_rad if self._target_rad is not None else math.radians(
            abs(self.target_angle_deg.value) if isinstance(self.target_angle_deg, FreeParam) else abs(self.target_angle_deg)
        )
        cos_target = math.cos(target_rad)
        cos_meas = self._direction_cosine()
        # Pick the sign that minimizes |cos_meas - (±cos_target)|
        d_normal = abs(cos_meas - cos_target)
        d_other  = abs(cos_meas + cos_target)  # -cos_target
        self._other = (d_other < d_normal)

    # ── Constraint interface ─────────────────────────────────────────

    def value(self):
        """
        Direction-cosine residual:  cos(measured) − cos(target).
        
        Range: [−2, 2].  error() = value()² ∈ [0, 4].
        """
        la = self.line_a; lb = self.line_b
        dxa = la.end.params[0].value - la.start.params[0].value
        dya = la.end.params[1].value - la.start.params[1].value
        dxb = lb.end.params[0].value - lb.start.params[0].value
        dyb = lb.end.params[1].value - lb.start.params[1].value

        la_sq = dxa * dxa + dya * dya
        lb_sq = dxb * dxb + dyb * dyb
        if la_sq < 1e-24 or lb_sq < 1e-24:
            return 2.0  # degenerate — maximally wrong

        mag_a = math.sqrt(la_sq)
        mag_b = math.sqrt(lb_sq)
        cos_meas = (dxa * dxb + dya * dyb) / (mag_a * mag_b)

        # Target
        target_rad = self._target_rad if self._target_rad is not None else math.radians(
            abs(self.target_angle_deg.value) if isinstance(self.target_angle_deg, FreeParam) else abs(self.target_angle_deg)
        )
        cos_target = math.cos(target_rad)
        if self._other:
            cos_target = -cos_target

        # Gain-up near small angles (from SolveSpace) to help rank detection
        residual = cos_meas - cos_target
        arc = abs(cos_target)
        if arc > 0.99:
            residual *= 0.01 / (1.00001 - arc)

        return residual

    def value_degrees(self) -> float:
        """Angular difference in degrees (for display only)."""
        cos_meas = self._direction_cosine()
        cos_meas = max(-1.0, min(1.0, cos_meas))
        measured_deg = math.degrees(math.acos(cos_meas))
        target_deg = abs(self.target_angle_deg.value if isinstance(self.target_angle_deg, FreeParam) else self.target_angle_deg)
        return measured_deg - target_deg

    def grad(self, param: "FreeParam") -> float:
        """Gradient of cos-based angle constraint.
        
        value = cos_meas - cos_target
        cos_meas = dot_ab / (mag_a * mag_b)
        
        This is identical to PerpendicularLineConstraint.grad (which also
        differentiates cos θ), except we subtract a constant cos_target.
        """
        la = self.line_a; lb = self.line_b
        a_params = [la.start.params[0], la.start.params[1],
                     la.end.params[0], la.end.params[1]]
        b_params = [lb.start.params[0], lb.start.params[1],
                     lb.end.params[0], lb.end.params[1]]
        pid = param.id

        # FreeParam target
        if isinstance(self.target_angle_deg, FreeParam) and pid == self.target_angle_deg.id:
            target_rad = math.radians(abs(self.target_angle_deg.value))
            # d(cos_meas - cos(target_rad))/d(target_deg)
            # = sin(target_rad) * d(target_rad)/d(target_deg)
            # = sin(target_rad) * π/180
            sign = -1.0 if self._other else 1.0
            return sign * math.sin(target_rad) * math.radians(1.0)

        all_ids = set(p.id for p in a_params + b_params)
        if pid not in all_ids:
            return 0.0

        dxa = a_params[2].value - a_params[0].value
        dya = a_params[3].value - a_params[1].value
        dxb = b_params[2].value - b_params[0].value
        dyb = b_params[3].value - b_params[1].value

        la_sq = dxa*dxa + dya*dya
        lb_sq = dxb*dxb + dyb*dyb
        if la_sq < 1e-24 or lb_sq < 1e-24:
            return 0.0

        mag_a = math.sqrt(la_sq)
        mag_b = math.sqrt(lb_sq)
        lab = mag_a * mag_b
        dot_ab = dxa*dxb + dya*dyb

        # v = dot_ab / lab
        # dv/dp = (d(dot_ab)/dp * lab - dot_ab * d(lab)/dp) / lab²
        if pid == a_params[0].id:    # ax1: dxa changes by -1
            d_dot = -dxb; d_la = -dxa/mag_a; d_lb = 0.0
        elif pid == a_params[1].id:  # ay1: dya changes by -1
            d_dot = -dyb; d_la = -dya/mag_a; d_lb = 0.0
        elif pid == a_params[2].id:  # ax2: dxa changes by +1
            d_dot = dxb; d_la = dxa/mag_a; d_lb = 0.0
        elif pid == a_params[3].id:  # ay2: dya changes by +1
            d_dot = dyb; d_la = dya/mag_a; d_lb = 0.0
        elif pid == b_params[0].id:  # bx1: dxb changes by -1
            d_dot = -dxa; d_la = 0.0; d_lb = -dxb/mag_b
        elif pid == b_params[1].id:  # by1: dyb changes by -1
            d_dot = -dya; d_la = 0.0; d_lb = -dyb/mag_b
        elif pid == b_params[2].id:  # bx2: dxb changes by +1
            d_dot = dxa; d_la = 0.0; d_lb = dxb/mag_b
        elif pid == b_params[3].id:  # by2: dyb changes by +1
            d_dot = dya; d_la = 0.0; d_lb = dyb/mag_b
        else:
            return 0.0

        d_lab = d_la * mag_b + mag_a * d_lb
        d_cos = (d_dot * lab - dot_ab * d_lab) / (lab * lab)

        # Apply the same gain-up factor used in value()
        target_rad = self._target_rad if self._target_rad is not None else math.radians(
            abs(self.target_angle_deg.value) if isinstance(self.target_angle_deg, FreeParam) else abs(self.target_angle_deg)
        )
        cos_target = math.cos(target_rad)
        if self._other:
            cos_target = -cos_target
        arc = abs(cos_target)
        if arc > 0.99:
            d_cos *= 0.01 / (1.00001 - arc)

        return d_cos

    def precondition(self, problem: "Problem2D"):
        """Rotate line_b's free endpoint to satisfy the angle constraint.
        
        Because the constraint uses *unsigned* angle (direction-cosine),
        there are **four** candidate orientations for line_b:
        
            angle_a ± target,  angle_a ± target + π
        
        The selection heuristic is:
        
        1. If either line has ``_within_line_points``, simulate all four
           and pick the one that keeps those points inside their segment
           (topology-aware precondition).
        2. Otherwise pick the orientation closest to the current state.
        
        Finally, ``_other`` is set via ``_auto_detect_other()`` so that
        the cos-based residual starts near zero.
        """
        fixed = problem.fixed_point_names
        b_pts_fixed = all(p.name in fixed for p in self.line_b.points)
        if b_pts_fixed:
            self._auto_detect_other()
            return

        length_b = self.line_b.length()
        if length_b < 1e-12:
            self._auto_detect_other()
            return

        b_start_fixed = self.line_b.start.name in fixed
        b_end_fixed = self.line_b.end.name in fixed

        # Compute absolute angle of line_a
        angle_a_rad = np.arctan2(self.line_a.dy(), self.line_a.dx())

        # Target relative angle in radians (unsigned, [0, π])
        target_rel_rad = self._target_rad if self._target_rad is not None else np.radians(
            abs(self.target_angle_deg.value) if isinstance(self.target_angle_deg, FreeParam) else abs(self.target_angle_deg)
        )

        # Four candidate absolute angles for line_b
        candidates = [
            angle_a_rad + target_rel_rad,
            angle_a_rad - target_rel_rad,
            angle_a_rad + target_rel_rad + np.pi,
            angle_a_rad - target_rel_rad + np.pi,
        ]

        # Check if either line has within-line constraints
        la_within = getattr(self.line_a, '_within_line_points', set())
        lb_within = getattr(self.line_b, '_within_line_points', set())
        has_topology = la_within or lb_within

        if has_topology:
            abs_target_rad = self._pick_topology_safe_from_candidates(
                candidates, b_start_fixed, b_end_fixed, length_b,
            )
        else:
            # Pick the candidate closest to the current direction of line_b
            curr_b = np.arctan2(self.line_b.dy(), self.line_b.dx())
            best = candidates[0]
            best_d = abs(_map_pi(curr_b - candidates[0]))
            for c in candidates[1:]:
                d = abs(_map_pi(curr_b - c))
                if d < best_d:
                    best_d = d
                    best = c
            abs_target_rad = best

        # Apply rotation
        if b_start_fixed:
            self.line_b.end.x = self.line_b.start.x + length_b * np.cos(abs_target_rad)
            self.line_b.end.y = self.line_b.start.y + length_b * np.sin(abs_target_rad)
        elif b_end_fixed:
            self.line_b.start.x = self.line_b.end.x - length_b * np.cos(abs_target_rad)
            self.line_b.start.y = self.line_b.end.y - length_b * np.sin(abs_target_rad)
        else:
            mx = (self.line_b.start.x + self.line_b.end.x) / 2
            my = (self.line_b.start.y + self.line_b.end.y) / 2
            half = length_b / 2
            self.line_b.start.x = mx - half * np.cos(abs_target_rad)
            self.line_b.start.y = my - half * np.sin(abs_target_rad)
            self.line_b.end.x = mx + half * np.cos(abs_target_rad)
            self.line_b.end.y = my + half * np.sin(abs_target_rad)

        # Now auto-detect ``_other`` from the (preconditioned) geometry
        self._auto_detect_other()

    def _pick_topology_safe_from_candidates(
        self,
        candidates: list[float],
        b_start_fixed: bool,
        b_end_fixed: bool,
        length_b: float,
    ) -> float:
        """Choose among candidate orientations, preferring those that
        don't violate within-line constraints on line_a or line_b."""
        bsx, bsy = self.line_b.start.x, self.line_b.start.y
        bex, bey = self.line_b.end.x, self.line_b.end.y
        
        def _simulate_and_check(abs_target: float) -> bool:
            if b_start_fixed:
                self.line_b.end.x = self.line_b.start.x + length_b * np.cos(abs_target)
                self.line_b.end.y = self.line_b.start.y + length_b * np.sin(abs_target)
            elif b_end_fixed:
                self.line_b.start.x = self.line_b.end.x - length_b * np.cos(abs_target)
                self.line_b.start.y = self.line_b.end.y - length_b * np.sin(abs_target)
            else:
                mx = (bsx + bex) / 2
                my = (bsy + bey) / 2
                half = length_b / 2
                self.line_b.start.x = mx - half * np.cos(abs_target)
                self.line_b.start.y = my - half * np.sin(abs_target)
                self.line_b.end.x = mx + half * np.cos(abs_target)
                self.line_b.end.y = my + half * np.sin(abs_target)
            ok = _check_within_line_global(self.line_a) and _check_within_line_global(self.line_b)
            # Restore
            self.line_b.start.x, self.line_b.start.y = bsx, bsy
            self.line_b.end.x, self.line_b.end.y = bex, bey
            return ok
        
        ok_list = [(c, _simulate_and_check(c)) for c in candidates]
        ok_candidates = [c for c, ok in ok_list if ok]
        
        if not ok_candidates:
            # All bad — fall back to closest to current
            ok_candidates = candidates
        
        # Among the ok candidates, pick the closest to current direction
        curr_b = np.arctan2(self.line_b.dy(), self.line_b.dx())
        best = ok_candidates[0]
        best_d = abs(_map_pi(curr_b - ok_candidates[0]))
        for c in ok_candidates[1:]:
            d = abs(_map_pi(curr_b - c))
            if d < best_d:
                best_d = d
                best = c
        return best

class LineLengthConstraint(Constraint):
    """Constrain the length of a line."""
    
    target_length: "float|FreeParam"
    
    def __init__(self, line: "Line", length: "float|FreeParam", weight: float = 1.0):
        super().__init__([line], weight)
        if isinstance(length, (int, float)) and length < 0:
            raise ValueError("length must be >= 0")
        self.target_length = length

    @property
    def line(self) -> "Line":
        return self.primitives[0]   # type: ignore

    def value(self):
        dx = self.line.end.params[0].value - self.line.start.params[0].value
        dy = self.line.end.params[1].value - self.line.start.params[1].value
        return math.sqrt(dx * dx + dy * dy) - (self.target_length.value if isinstance(self.target_length, FreeParam) else self.target_length)

    def grad(self, param: "FreeParam") -> float:
        sx, sy = self.line.start.params[0], self.line.start.params[1]
        ex, ey = self.line.end.params[0], self.line.end.params[1]
        pid = param.id
        if pid not in (sx.id, sy.id, ex.id, ey.id):
            if isinstance(self.target_length, FreeParam) and pid == self.target_length.id:
                return -1.0
            return 0.0
        dx = ex.value - sx.value
        dy = ey.value - sy.value
        L = math.sqrt(dx*dx + dy*dy)
        if L < 1e-12:
            return 0.0
        if pid == ex.id:
            return dx / L
        elif pid == ey.id:
            return dy / L
        elif pid == sx.id:
            return -dx / L
        elif pid == sy.id:
            return -dy / L
        return 0.0

    def precondition(self, problem: "Problem2D"):
        """Scale line to target length, keeping fixed endpoint pinned."""
        fixed = problem.fixed_point_names
        s_fixed = self.line.start.name in fixed
        e_fixed = self.line.end.name in fixed
        current = self.line.length()
        if current < 1e-12 or (s_fixed and e_fixed):
            return
        target_length = self.target_length.value if isinstance(self.target_length, FreeParam) else self.target_length
        scale = target_length / current
        if s_fixed:
            dx = self.line.end.x - self.line.start.x
            dy = self.line.end.y - self.line.start.y
            self.line.end.params[0].update(self.line.start.x + dx * scale)
            self.line.end.params[1].update(self.line.start.y + dy * scale)
        elif e_fixed:
            dx = self.line.start.x - self.line.end.x
            dy = self.line.start.y - self.line.end.y
            self.line.start.params[0].update(self.line.end.x + dx * scale)
            self.line.start.params[1].update(self.line.end.y + dy * scale)
        else:
            cx = (self.line.start.x + self.line.end.x) / 2
            cy = (self.line.start.y + self.line.end.y) / 2
            dx = self.line.end.x - self.line.start.x
            dy = self.line.end.y - self.line.start.y
            self.line.start.params[0].update(cx - dx * scale / 2)
            self.line.start.params[1].update(cy - dy * scale / 2)
            self.line.end.params[0].update(cx + dx * scale / 2)
            self.line.end.params[1].update(cy + dy * scale / 2)

class LineParallelConstraint(Constraint):
    """Constrain two lines to be parallel (angle difference = 0)."""

    def __init__(self, line_a: "Line", line_b: "Line", weight: float = 1.0):
        super().__init__([line_a, line_b], weight)

    @property
    def line_a(self) -> "Line":
        return self.primitives[0]   # type: ignore

    @property
    def line_b(self) -> "Line":
        return self.primitives[1]   # type: ignore

    def value(self):
        """Angle difference in radians (0 when parallel)."""
        dxa = self.line_a.end.params[0].value - self.line_a.start.params[0].value
        dya = self.line_a.end.params[1].value - self.line_a.start.params[1].value
        dxb = self.line_b.end.params[0].value - self.line_b.start.params[0].value
        dyb = self.line_b.end.params[1].value - self.line_b.start.params[1].value
        if (dxa * dxa + dya * dya) < 1e-24 or (dxb * dxb + dyb * dyb) < 1e-24:
            return math.pi  # degenerate line — treat as maximally wrong
        return math.atan2(dya * dxb - dxa * dyb, dxa * dxb + dya * dyb)

    def grad(self, param: "FreeParam") -> float:
        """Gradient of atan2(det, dot) for parallel constraint (same as angle with target=0)."""
        la = self.line_a; lb = self.line_b
        a_params = [la.start.params[0], la.start.params[1],
                     la.end.params[0], la.end.params[1]]
        b_params = [lb.start.params[0], lb.start.params[1],
                     lb.end.params[0], lb.end.params[1]]
        all_ids = set(p.id for p in a_params + b_params)
        if param.id not in all_ids:
            return 0.0
        
        dxa = a_params[2].value - a_params[0].value
        dya = a_params[3].value - a_params[1].value
        dxb = b_params[2].value - b_params[0].value
        dyb = b_params[3].value - b_params[1].value
        
        if (dxa*dxa + dya*dya) < 1e-24 or (dxb*dxb + dyb*dyb) < 1e-24:
            return 0.0
        
        dot = dxa*dxb + dya*dyb
        det = dya*dxb - dxa*dyb
        r2 = dot*dot + det*det
        if r2 < 1e-24:
            return 0.0
        
        pid = param.id
        if pid == a_params[0].id:
            d_dot = -dxb; d_det = dyb
        elif pid == a_params[1].id:
            d_dot = -dyb; d_det = -dxb
        elif pid == a_params[2].id:
            d_dot = dxb; d_det = -dyb
        elif pid == a_params[3].id:
            d_dot = dyb; d_det = dxb
        elif pid == b_params[0].id:
            d_dot = -dxa; d_det = -dya
        elif pid == b_params[1].id:
            d_dot = -dya; d_det = dxa
        elif pid == b_params[2].id:
            d_dot = dxa; d_det = dya
        elif pid == b_params[3].id:
            d_dot = dya; d_det = -dxa
        else:
            return 0.0
        
        return (dot * d_det - det * d_dot) / r2
    
    def precondition(self, problem: "Problem2D"):
        """Rotate line_b's free endpoint to satisfy the parallel constraint."""
        fixed = problem.fixed_point_names
        # Determine which endpoints are free
        b_pts_fixed = all(p.name in fixed for p in self.line_b.points)
        if b_pts_fixed:
            return

        # Compute current angle of line_a
        angle_a = np.degrees(np.arctan2(self.line_a.dy(), self.line_a.dx()))
        # Target angle for line_b
        target_b = angle_a

        # Rotate line_b to target angle, keeping its start fixed (or midpoint)
        length_b = self.line_b.length()
        if length_b < 1e-12:
            return

        b_start_fixed = self.line_b.start.name in fixed
        b_end_fixed = self.line_b.end.name in fixed

        target_rad = np.radians(target_b)
        if b_start_fixed and not b_end_fixed:
            self.line_b.end.x = self.line_b.start.x + length_b * np.cos(target_rad)
            self.line_b.end.y = self.line_b.start.y + length_b * np.sin(target_rad)
        elif b_end_fixed and not b_start_fixed:
            self.line_b.start.x = self.line_b.end.x - length_b * np.cos(target_rad)
            self.line_b.start.y = self.line_b.end.y - length_b * np.sin(target_rad)
        else:
            # Both free — rotate around midpoint
            mx = (self.line_b.start.x + self.line_b.end.x) / 2
            my = (self.line_b.start.y + self.line_b.end.y) / 2
            half = length_b / 2
            self.line_b.start.x = mx - half * np.cos(target_rad)
            self.line_b.start.y = my - half * np.sin(target_rad)
            self.line_b.end.x = mx + half * np.cos(target_rad)
            self.line_b.end.y = my + half * np.sin(target_rad)

class ValueCompareConstraint(Constraint):
    def __init__(
        self, 
        param_a: "FreeParam", 
        param_b: "FreeParam|float", 
        mode: Literal['gt', 'ge', 'lt', 'le', 'eq', 'ne'] = 'eq',
        weight: float = 1.0
    ):
        super().__init__([], weight)
        self.param_a = param_a
        self.param_b = param_b
        self.mode = mode
        
    def value(self):
        a_val = self.param_a.value
        b_val = self.param_b.value if isinstance(self.param_b, FreeParam) else self.param_b
        if self.mode == 'gt':
            return min(0.0, a_val - b_val + 1e-6)
        elif self.mode == 'ge':
            return min(0.0, a_val - b_val)
        elif self.mode == 'lt':
            return min(0.0, b_val - a_val + 1e-6)
        elif self.mode == 'le':
            return min(0.0, b_val - a_val)
        elif self.mode == 'eq':
            return a_val - b_val
        elif self.mode == 'ne':
            diff = a_val - b_val
            return 0.0 if abs(diff) > 1e-6 else 1.0  # penalize being too close
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def grad(self, param: "FreeParam") -> float:
        pid = param.id
        a_val = self.param_a.value
        b_val = self.param_b.value if isinstance(self.param_b, FreeParam) else self.param_b
        is_a = pid == self.param_a.id
        is_b = isinstance(self.param_b, FreeParam) and pid == self.param_b.id
        if not is_a and not is_b:
            return 0.0
        sign = 1.0 if is_a else -1.0
        if self.mode in ('gt', 'ge'):
            if a_val - b_val + (1e-6 if self.mode == 'gt' else 0) < 0:
                return sign
            return 0.0
        elif self.mode in ('lt', 'le'):
            if b_val - a_val + (1e-6 if self.mode == 'lt' else 0) < 0:
                return -sign
            return 0.0
        elif self.mode == 'eq':
            return sign
        elif self.mode == 'ne':
            return 0.0  # non-differentiable
        return 0.0
    
    def precondition(self, problem: "Problem2D"):
        a_val = self.param_a.value
        b_val = self.param_b.value if isinstance(self.param_b, FreeParam) else self.param_b
        if self.param_a.fixed:
            return
        delta = min(1e-3, abs(a_val - b_val) * 0.1 + 1e-6)
        if self.mode == 'gt':
            if a_val <= b_val:
                self.param_a.update(b_val + delta)
        elif self.mode == 'ge':
            if a_val < b_val:
                self.param_a.update(b_val)
        elif self.mode == 'lt':
            if a_val >= b_val:
                self.param_a.update(b_val - delta)
        elif self.mode == 'le':
            if a_val > b_val:
                self.param_a.update(b_val)
        elif self.mode == 'eq':
            self.param_a.update(b_val)
        elif self.mode == 'ne':
            diff = a_val - b_val
            if abs(diff) <= 1e-6:
                self.param_a.update(b_val + 1e-3)  # nudge away
                
    def project(self, problem: "Problem2D"):
        if self.param_a.fixed:
            return
        a_val = self.param_a.value
        b_val = self.param_b.value if isinstance(self.param_b, FreeParam) else self.param_b
        if self.mode == 'gt':
            if a_val <= b_val:
                self.param_a.update(b_val + 1e-6)
        elif self.mode == 'ge':
            if a_val < b_val:
                self.param_a.update(b_val)
        elif self.mode == 'lt':
            if a_val >= b_val:
                self.param_a.update(b_val - 1e-6)
        elif self.mode == 'le':
            if a_val > b_val:
                self.param_a.update(b_val)
        elif self.mode == 'eq':
            self.param_a.update(b_val)
        elif self.mode == 'ne':
            diff = a_val - b_val
            if abs(diff) <= 1e-6:
                self.param_a.update(b_val + 1e-3)  # nudge away


__all__ = [
    'Constraint',
    'PointToPointDistanceConstraint',
    'PointOnLineConstraint',
    'PointOnLineSegmentConstraint',
    'PerpendicularLineConstraint',
    'LineHorizontalConstraint',
    'LineVerticalConstraint',
    'LineAngleConstraint',
    'LineLengthConstraint',
    'LineParallelConstraint',
    'ValueCompareConstraint',
]
# endregion

# region primitives
class _InvalidPrimitive:
    def __init__(self, primitive: "Primitive", reason: str):
        self.primitive = primitive
        self.reason = reason

    def __str__(self):
        return f"{self.primitive} ({self.reason})"
    
@dataclass
class _DrawingContext:
    
    max_x: float
    '''Maximum x-coordinate among all points.'''
    max_y: float
    '''Maximum y-coordinate among all points.'''
    min_x: float
    '''Minimum x-coordinate among all points.'''
    min_y: float
    '''Minimum y-coordinate among all points.'''
    drawn: set[str] = field(default_factory=set)
    '''Set of primitive names that have already been drawn.'''
    
    @property
    def max_abs_coord(self) -> float:
        return max(abs(self.max_x), abs(self.max_y), abs(self.min_x), abs(self.min_y))

@dataclass
class FreeParam:
    
    id: str
    value: float
    fixed: bool = False
    
    def __eq__(self, other: "FreeParam|str|float|int")->bool:
        if isinstance(other, FreeParam):
            return self.id == other.id
        elif isinstance(other, str):
            return self.id == other
        elif isinstance(other, (float, int)):
            return self.value == other
        return False

    def __hash__(self):
        return hash(self.id)
    
    def update(self, new: float):
        if not self.fixed:
            self.value = new
            
    def __add__(self, other: float):
        return self.value + other
    
    def __sub__(self, other: float):
        return self.value - other
    
    def __mul__(self, other: float):
        return self.value * other
    
    def __truediv__(self, other: float):
        return self.value / other
    
    def __repr__(self):
        return f"<FreeParam {self.id}={self.value} {'(fixed)' if self.fixed else ''}>"
    
    def __str__(self):
        return str(self.value)
    
    def __float__(self):
        return float(self.value)
    
    def __int__(self):
        return int(self.value)
    
    def __lt__(self, other: float):
        return self.value < other

class Primitive(ABC):
    
    __NameCounter__: ClassVar[int]
    
    name: str
    points: list["Point"]
    problem: "Problem2D"
    draw: bool = True
    params: list[FreeParam]

    def __init__(
        self, 
        name: str, 
        points: Sequence["Point|tuple[float, float]"], 
        problem: "Problem2D",
        draw: bool|None=None,
        params: Sequence[FreeParam]|None=None,
    ):
        self.name = name
        points = list(points)
        for i, point in enumerate(points):
            if not isinstance(point, Point):
                points[i] = Point(f"__{self.name}_p{i}__", *point)  # type: ignore
        assert len(set(p.name for p in points)) == len(points), f"Primitive {self.name} has duplicate point names."     # type: ignore
        self.points = points    # type: ignore
        self.problem = problem
        if draw is None:
            self.draw = (not self.name.startswith("__"))
        else:
            self.draw = draw
        self.params = list(params) if params is not None else []
            
    def __init_subclass__(cls, **kwargs):
        cls.__NameCounter__ = 0

    @abstractmethod
    def __str__(self):
        raise NotImplementedError

    def __repr__(self):
        return f"<{self.__class__.__name__}@{hex(id(self))}>"

    def validate(self)->bool|_InvalidPrimitive:
        return True
    
    def draw_ax(self, ax: Axes, context: _DrawingContext):
        def shift_pt(x, y, max_coord):
            s = 0.02 * max_coord
            dir_x = 1 if x >= 0 else -1
            dir_y = 1 if y >= 0 else -1
            return (x + 3*s * dir_x, y + 3*s * dir_y)
        
        for point in self.points:
            if (point.name in context.drawn) or (not point.draw):
                continue
            ax.plot(point.x, point.y, marker="o", color="black", markersize=3)
            ax.text(*shift_pt(point.x, point.y, context.max_abs_coord), point.name, fontsize=11)
            context.drawn.add(point.name)

class Point(Primitive):

    def __init__(self, name: str, x: float, y: float, problem: "Problem2D", draw: bool|None=None):
        xp, yp = FreeParam(f"{name}_x", x), FreeParam(f"{name}_y", y)
        super().__init__(name, points=[self], problem=problem, draw=draw, params=[xp, yp])

    @property
    def x(self)->float:
        return self.params[0].value

    @x.setter
    def x(self, value: float):
        self.params[0].update(value)

    @property
    def y(self)->float:
        return self.params[1].value
    
    @y.setter
    def y(self, value: float):
        self.params[1].update(value)

    def norm(self):
        x, y = self.x, self.y
        return math.sqrt(x * x + y * y)

    def __add__(self, other):
        return self.__class__(self._op_name("+", other), self.x + other.x, self.y + other.y, self.problem)

    def __sub__(self, other):
        return self.__class__(self._op_name("-", other), self.x - other.x, self.y - other.y, self.problem)

    def __str__(self):
        return f"{self.__class__.__name__}({self.name}, ({self.x}, {self.y}))"

    def _op_name(self, op, other):
        return f"{self}{op}{other}"
    
    def fix(self):
        """Fix this point's position in the problem."""
        for param in self.params:
            param.fixed = True

def _map_angle_about_zero(angle):
    return (angle + 180) % (360) - 180

class Line(Primitive):
    
    _within_line_points: set[str]
    
    def __init__(self, name: str, start: "Point", end: "Point", problem: "Problem2D", draw: bool|None=None):
        super().__init__(name, [start, end], problem, draw=draw,
                         params=start.params + end.params)
        self._within_line_points = set()
        
    def draw_ax(self, ax: Axes, context: _DrawingContext):
        ax.plot([self.start.x, self.end.x], [self.start.y, self.end.y], color="blue", linewidth=1)
        super().draw_ax(ax, context)
        
    @property
    def start(self)->"Point":
        return self.points[0]

    @property
    def end(self)->"Point":
        return self.points[1]

    def dx(self)->float:
        """The difference between the end and start x-coordinates."""
        return self.end.x - self.start.x

    def dy(self)->float:
        """The difference between the end and start y-coordinates."""
        return self.end.y - self.start.y

    def length(self)->float:
        """The line length."""
        dx = self.end.params[0].value - self.start.params[0].value
        dy = self.end.params[1].value - self.start.params[1].value
        return math.sqrt(dx * dx + dy * dy)

    def angle(self)->float:
        """The angle of the vector formed by this line translated to the origin.

        Returns
        -------
        :class:`float`
            The angle, in degrees, in the range (-180, 180].
        """
        angle = np.degrees(np.arctan2(self.dx(), self.dy()))
        return _map_angle_about_zero(angle)

    def angle_to(self, other: "Line")->float:
        """The angle to other line with respect to this one.

        The angle is defined as the clockwise rotation from the direction of `self` to
        get to the direction of `other`.
        """
        dot = self.dx() * other.dx() + self.dy() * other.dy()
        det = self.dy() * other.dx() - self.dx() * other.dy()
        angle = np.degrees(np.arctan2(det, dot))

        return _map_angle_about_zero(angle)

    def validate(self)->bool|_InvalidPrimitive:
        zerolength = np.isclose(self.length(), 0)
        if zerolength:
            return _InvalidPrimitive(self, "zero length")
        return True

    def __str__(self):
        points = ", ".join(str(point) for point in self.points)
        return (
            f"{self.__class__.__name__}({self.name}, [{points}], "
            f"length={self.length()}, angle={self.angle()})"
        )

    def constrain_length(self, length: float)->LineLengthConstraint:
        """Constrain this line's length."""
        c = LineLengthConstraint(self, length)
        self.problem.add_constraint(c)
        return c

    def constrain_angle_with(self, other_line: "Line", angle: float|FreeParam) -> LineAngleConstraint:
        """Constrain the angle between this line and another line (degrees).
        
        The angle is direction-independent: ``add_line(A, B)`` and
        ``add_line(B, A)`` produce identical constraints.  This matches
        the behaviour of professional CAD constraint solvers (SolveSpace,
        GeoGebra, FreeCAD Sketcher) where the angle between two geometric
        lines is always in [0°, 180°].
        
        Internally uses a direction-cosine formulation:
            cos(measured_angle) = cos(target_angle)
        which is symmetric under direction reversal.
        """
        self.problem._log(f'Adding LineAngleConstraint between line {self.name} and line {other_line.name} with target angle {angle}', 'info')
        c = LineAngleConstraint(self, other_line, angle)
        self.problem.add_constraint(c)
        return c

    def constrain_perpendicular_to(self, other_line: "Line")->PerpendicularLineConstraint:
        """Constrain this line to be perpendicular to another."""
        c = PerpendicularLineConstraint(self, other_line)
        self.problem.add_constraint(c)
        return c

    def constrain_parallel_to(self, other_line: "Line")->LineParallelConstraint:
        """Constrain this line to be parallel to another."""
        c = LineParallelConstraint(self, other_line)
        self.problem.add_constraint(c)
        return c

    def constrain_horizontal(self)->LineHorizontalConstraint:
        """Constrain this line to be horizontal."""
        c = LineHorizontalConstraint(self)
        self.problem.add_constraint(c)
        return c

    def constrain_vertical(self)->LineVerticalConstraint:
        """Constrain this line to be vertical."""
        c = LineVerticalConstraint(self)
        self.problem.add_constraint(c)
        return c

    def constrain_point(self, point: "Point", within_line: bool = False) -> PointOnLineConstraint:
        """Constrain a point to lie on this line.
        
        Parameters
        ----------
        point : Point
            The point to constrain.
        within_line : bool
            If False (default), the point is constrained to the **infinite**
            line through start and end.
            If True, the point is additionally constrained to lie **within
            the segment** [start, end].  This is done by adding a
            ``PointOnLineSegmentConstraint`` and registering the point in
            the line's ``_within_line_points`` set, which the solver uses
            for topology validation.
            
            Multiple points can independently be constrained with
            ``within_line=True`` without implying any ordering between them.
        """
        if point == self.start or point == self.end:
            raise ValueError("Cannot constrain a line's endpoint to lie on the line.")
        need_add_pt_on_line_constrain = True
        pt_on_line_constrain = None
        for c in self.problem.constraints:
            if isinstance(c, PointOnLineConstraint) and c.primitives[0] == point and c.primitives[1] == self:
                need_add_pt_on_line_constrain = False
                pt_on_line_constrain = c
                break
        if need_add_pt_on_line_constrain:
            self.problem._log(f'Adding PointOnLineConstraint for point {point.name} on line {self.name}', 'info')
            pt_on_line_constrain = PointOnLineConstraint(point, self)
            self.problem.add_constraint(pt_on_line_constrain)
        if within_line:
            need_add_pt_on_segment_constrain = True
            for c in self.problem.constraints:
                if isinstance(c, PointOnLineSegmentConstraint) and c.primitives[0] == point and c.primitives[1] == self:
                    need_add_pt_on_segment_constrain = False
                    break
            if need_add_pt_on_segment_constrain:
                seg_c = PointOnLineSegmentConstraint(point, self)
                self.problem._log(f'Adding PointOnLineSegmentConstraint for point {point.name} on line {self.name}', 'info')
                self.problem.add_constraint(seg_c)
                self._within_line_points.add(point.name)
        return pt_on_line_constrain     # type: ignore

class Circle(Primitive):
    
    def __str__(self):
        return f"{self.__class__.__name__}({self.name}, center=({self.center.x}, {self.center.y}), radius={self.radius})"
    
    def __init__(self, name: str, center: "Point", radius: float, problem: "Problem2D", draw: bool|None=None):
        r = FreeParam(f"{name}_r", radius)
        super().__init__(name, points=[center], problem=problem, draw=draw, params=center.params + [r])
        self._constraint_pts: set[str] = set()
        self.problem.add_constraint(ValueCompareConstraint(r, 0.0, mode='gt', weight=10.0))  # radius > 0
    
    @property
    def center(self) -> "Point":
        return self.points[0]
    
    @property
    def radius(self)->float:
        return self.params[-1].value
        
    @property
    def constrained_points(self)->list["Point"]:
        '''Get the list of points constrained to lie on this circle.'''
        return [self.problem.primitives[pt_name] for pt_name in self._constraint_pts if pt_name in self.problem.primitives] # type: ignore
    
    def _random_pt(self)->tuple[float, float]:
        curr_points = self.constrained_points
        # calculate average angle of constrained points, avoid clustering
        if curr_points:
            angles = []
            for pt in curr_points:
                angle = np.arctan2(pt.y - self.center.y, pt.x - self.center.x)
                angles.append(angle)
            avg_angle = np.mean(angles)
            angle = (avg_angle + np.pi) % (2 * np.pi)  # 反方向
        else:
            angle = np.random.uniform(0, 2 * np.pi)
        return (self.center.x + self.radius * np.cos(angle), self.center.y + self.radius * np.sin(angle))
    
    def fix_center(self):
        """Fix this circle's center point in the problem."""
        self.center.fix()
        
    def fix_radius(self, new_r: float|None=None):
        """Fix this circle's radius in the problem."""
        if new_r is not None:
            self.params[-1].value = new_r
        self.params[-1].fixed = True

    def constrain_point(self, point: Point)->PointToPointDistanceConstraint:
        """Constrain a point to lie on this circle (with analytic pre-conditioning)."""
        if point.name in self._constraint_pts:
            for c in self.problem.constraints:
                if (isinstance(c, PointToPointDistanceConstraint) and
                    ((c.primitives[0] == point and c.primitives[1] == self.center)
                     or (c.primitives[1] == point and c.primitives[0] == self.center))):
                    return c
                
        c = PointToPointDistanceConstraint(point, self.center, self.params[-1]) # higher weight for circle constraints
        self.problem.add_constraint(c)
        self._constraint_pts.add(point.name)
        return c

    def draw_ax(self, ax: Axes, context: _DrawingContext):
        arc = pltCircle(
            (self.center.x, self.center.y), self.radius,
            fill=False, color='green', linestyle='--'
        )
        ax.add_patch(arc)
        super().draw_ax(ax, context)
        
    def create_diameter(self, name: str|None=None)->Line:
        '''create a new line which constrains to be the diameter of this circle.'''
        fp = self._random_pt()
        tp = (2 * self.center.x - fp[0], 2 * self.center.y - fp[1])
        if not name:
            count = 0
            name = f'{self.name}_diameter'
            while name in self.problem.primitives:
                count += 1
                name = f'{self.name}_diameter_{count}'
        if len(name) == 2 and name.isalpha():
            # try if each character can be used as point name
            pn1, pn2 = name[0], name[1]
            if pn1 in self.problem.primitives or pn2 in self.problem.primitives:
                pn1 = f'{name}_start'
                pn2 = f'{name}_end'
        else:
            pn1 = f'{name}_start'
            pn2 = f'{name}_end'
        count = 0
        while pn1 in self.problem.primitives or pn2 in self.problem.primitives:
            count += 1
            pn1 = f'{name}_start_{count}'
            pn2 = f'{name}_end_{count}'
        
        fp = self.problem.add_point(*fp, pn1)
        tp = self.problem.add_point(*tp, pn2)
        diameter = self.problem.add_line(fp, tp, name)
        diameter.constrain_point(self.center)
        self.constrain_point(fp)
        self.constrain_point(tp)
        return diameter
        
    def create_tangent(
        self, 
        touching_pt: Point|None=None, 
        tangent_name: str|None=None,
        touching_pt_within_line: bool=True,
        tangent_line: Line|tuple[Point, Point]|None=None
    )->tuple[Line, Point]:
        '''
        Create a new line which is tangent to this circle at the given point.
        If point is None, a random tangent point on the circle is created.
        Returns:
            (tangent_line, tangent_point)
        '''
        if not tangent_name:
            if tangent_line and isinstance(tangent_line, Line):
                tangent_name = tangent_line.name
            else:
                count = 0
                tangent_name = f'{self.name}_tangent'
                while tangent_name in self.problem.primitives:
                    count += 1
                    tangent_name = f'{self.name}_tangent_{count}'
        
        if touching_pt is None:
            px, py = self._random_pt()
            touching_pt = self.problem.add_point(px, py, f"{self.name}_tangent_point")
        self.constrain_point(touching_pt)
        
        if not tangent_line:
            # create a line perpendicular to radius at the point
            dx = touching_pt.x - self.center.x
            dy = touching_pt.y - self.center.y
            length = np.sqrt(dx * dx + dy * dy)
            if length < 1e-12:
                raise ValueError("Cannot create tangent line at circle center.")
            # unit vector along radius
            ux, uy = dx / length, dy / length
            # perpendicular unit vector
            vx, vy = -uy, ux
            # create two points along the tangent line
            t1x = touching_pt.x + vx
            t1y = touching_pt.y + vy
            t2x = touching_pt.x - vx
            t2y = touching_pt.y - vy
            
            if len(tangent_name) == 2 and tangent_name.isalpha():
                # try if each character can be used as point name
                pn1, pn2 = tangent_name[0], tangent_name[1]
                if pn1 in self.problem.primitives or pn2 in self.problem.primitives:
                    pn1 = f'{tangent_name}_pt1'
                    pn2 = f'{tangent_name}_pt2'
            else:
                pn1 = f'{tangent_name}_pt1'
                pn2 = f'{tangent_name}_pt2'
            count = 0
            while pn1 in self.problem.primitives or pn2 in self.problem.primitives:
                count += 1
                pn1 = f'{tangent_name}_pt1_{count}'
                pn2 = f'{tangent_name}_pt2_{count}'
            
            p1 = self.problem.add_point(t1x, t1y, pn1)
            p2 = self.problem.add_point(t2x, t2y, pn2)
            tangent_line = self.problem.add_line(p1, p2, tangent_name)
        elif isinstance(tangent_line, (list, tuple)) and len(tangent_line) == 2 and all(isinstance(p, Point) for p in tangent_line):
            tangent_line = self.problem.add_line(tangent_line[0], tangent_line[1], tangent_name)
        elif isinstance(tangent_line, Line):
            # use the given line, just add the perpendicular constraint
            pass
        else:
            raise ValueError("Invalid tangent_line argument. Must be None, Line, or tuple of two Points.")
        
        radius_line_name = f"{self.name}_radius_for_{tangent_name}"
        count = 0
        while radius_line_name in self.problem.primitives:
            count += 1
            radius_line_name = f"{self.name}_radius_for_{tangent_name}_{count}"
        tangent_line.constrain_perpendicular_to(
            self.problem.add_line(self.center, touching_pt, radius_line_name, draw=False)
        )
        tangent_line.constrain_point(touching_pt, within_line=touching_pt_within_line)
        return tangent_line, touching_pt
        
    def create_point(self, name: str|None=None, angle_deg: float|None=None)->Point:
        '''create a new point on the circle at the given angle (degrees).'''
        if angle_deg is not None:
            angle_rad = np.radians(_map_angle_about_zero(angle_deg))
            px = self.center.x + self.radius * np.cos(angle_rad)
            py = self.center.y + self.radius * np.sin(angle_rad)
        else:
            px, py = self._random_pt()
        if not name:
            count = 0
            name = f'{self.name}_point'
            while name in self.problem.primitives:
                count += 1
                name = f'{self.name}_point_{count}'
        point = self.problem.add_point(px, py, name)
        self.constrain_point(point)
        return point
        
__all__ += [
    'FreeParam',
    'Primitive',
    'Point',
    'Line',
    'Circle',
]
# endregion

# region problem solver
WantedInfoType: TypeAlias = Union[
    Point,  # 显示坐标 
    Line,   # 显示长度
    tuple[Point, Point, Point],  # 显示角度
    tuple[Line, Line],  # 显示两直线夹角
    str,        # 可以是∠ABC(角), ABC(角), AB(线段长度), A(点坐标)
]
'''
Type for specifying what info to show on the drawing.
Can be:
- Point: show coordinate
- Line: show length
- tuple(Point, Point, Point): show angle at middle point
- tuple(Line, Line): show angle between two lines
- str: can be `∠ABC` (angle), `ABC` (angle), `AB` (line length), `A` (point coordinate)
'''

@dataclass
class _DrawnInfo:
    type: Literal['angle', 'length', 'coordinate']
    origin_wanted_input: WantedInfoType
    final_value: Any
    
    # angle info
    angle_pos: tuple[float, float] | None = None
    angle_direction: tuple[float, float] | None = None  # unit vector
    
    # length info
    line_from_pos: tuple[float, float] | None = None
    line_to_pos: tuple[float, float] | None = None
    
    # coordinate info
    coordinate_pos: tuple[float, float] | None = None
    
    def __str__(self):
        if self.type in ('angle', 'length'):
            fv = abs(self.final_value)
        else:
            fv = self.final_value
        return f'{self.type} {self.origin_wanted_input} = {fv}'
        
    def __repr__(self):
        if self.type == 'angle':
            return f"DrawnInfo(angle at {self.angle_pos}, value={self.final_value}, dir={self.angle_direction})"
        elif self.type == 'length':
            return f"DrawnInfo(length within ({self.line_from_pos} -- {self.line_to_pos}), value={self.final_value})"
        elif self.type == 'coordinate':
            return f"DrawnInfo(coord={self.coordinate_pos}, value={self.final_value})"
        return super().__repr__()
    
    @no_type_check
    def __eq__(self, other: "_DrawnInfo") -> bool:
        if isinstance(other, _DrawnInfo):
            if self.type != other.type:
                return False
            if self.type == 'angle':
                dist_sq = (self.angle_pos[0] - other.angle_pos[0])**2 + (self.angle_pos[1] - other.angle_pos[1])**2
                if dist_sq < 1e-4:
                    dir_dot = (self.angle_direction[0] * other.angle_direction[0] + self.angle_direction[1] * other.angle_direction[1])
                    return abs(dir_dot - 1.0) < 0.05  and dir_dot > 0     # check direction sign for angle
            elif self.type == 'length':
                if abs(self.final_value - other.final_value) < 1e-4:
                    self_dir = (self.line_to_pos[0] - self.line_from_pos[0], self.line_to_pos[1] - self.line_from_pos[1])
                    other_dir = (other.line_to_pos[0] - other.line_from_pos[0], other.line_to_pos[1] - other.line_from_pos[1])
                    dir_dot = (self_dir[0] * other_dir[0] + self_dir[1] * other_dir[1])
                    return abs(dir_dot - 1.0) < 1e-4 # no need to check direction sign for length
            elif self.type == 'coordinate':
                dist_sq = (self.coordinate_pos[0] - other.coordinate_pos[0])**2 + (self.coordinate_pos[1] - other.coordinate_pos[1])**2
                return dist_sq < 1e-4
        return False
    
    @classmethod
    def CreateAngle(
        cls,
        ax, ay,
        bx, by,
        mx, my, # point on the angle bisector
        origin_wanted_input,
        final_value,
    )->"_DrawnInfo":
        dir_a = (ax-mx, ay-my)
        dir_b = (bx-mx, by-my)
        angle_dir = (dir_a[0]+dir_b[0], dir_a[1]+dir_b[1])
        length = np.sqrt(angle_dir[0]**2 + angle_dir[1]**2)
        if length < 1e-12:
            direction = (1.0, 0.0)
        else:
            direction = (angle_dir[0]/length, angle_dir[1]/length)
        return cls(
            type='angle',
            angle_pos=(mx, my),
            angle_direction=direction,
            origin_wanted_input=origin_wanted_input,
            final_value=final_value,
        )
        
    @classmethod
    def CreateLength(
        cls,
        from_x, from_y,
        to_x, to_y,
        origin_wanted_input,
        final_value,
    )->"_DrawnInfo":
        return cls(
            type='length',
            line_from_pos=(from_x, from_y),
            line_to_pos=(to_x, to_y),
            origin_wanted_input=origin_wanted_input,
            final_value=final_value,
        )
    
    @classmethod
    def CreateCoordinate(
        cls,
        x, y,
        origin_wanted_input,
        final_value,
    )->"_DrawnInfo":
        return cls(
            type='coordinate',
            coordinate_pos=(x, y),
            origin_wanted_input=origin_wanted_input,
            final_value=final_value,
        )
    
class Problem2D:
    """
    A 2D geometry constraint problem.

    Solver strategy (three stages):
        1. **Analytic pre-conditioning**: Iteratively apply each constraint's
           precondition() to project parameters toward feasibility. Multiple
           passes reduce conflict between constraints.
        2. **Local minimization**: Use scipy.optimize.minimize (default SLSQP)
           for fast, gradient-aware convergence from the pre-conditioned state.
        3. **Global fallback**: If local minimization fails, use basinhopping
           with warm restarts from perturbed initial guesses.
    """
    
    class _PrimitivesDict(dict[str, Primitive]):
        problem: "Problem2D"
        
        def __init__(self, problem: "Problem2D"):
            super().__init__()
            self.problem = problem
        
        def __setitem__(self, key: str, value: Primitive):
            if key in self:
                raise ValueError(f"Primitive with name {repr(key)} already exists in problem")
            old = self.get(key, None)
            if old != value:
                self.problem._modified = True
            super().__setitem__(key, value)

        def __delitem__(self, key: str):
            if key in self:
                self.problem._modified = True
            super().__delitem__(key)
            
        def clear(self):
            if self:
                self.problem._modified = True
            super().clear()
        
        def pop(self, key: str, default=None):
            if key in self:
                self.problem._modified = True
            return super().pop(key, default)
        
        def popitem(self):
            self.problem._modified = True
            return super().popitem()
        
        def update(self, *args, **kwargs):
            modified = False
            for k, v in dict(*args, **kwargs).items():
                if k not in self or self[k] != v:
                    modified = True
                    super().__setitem__(k, v)
            if modified:
                self.problem._modified = True

    def __init__(self, enable_log: bool=True):
        self.__modified__: bool = False
        self._x_axis: Line | None = None
        self._y_axis: Line | None = None
        self.primitives = self._PrimitivesDict(self)
        self.constraints: list[Constraint] = []
        self.enable_log = enable_log
        
    def __str__(self):
        primitivestrs = []
        for primitive in self.primitives.values():
            primitivestrs.append(str(primitive))

        constraintstrs = []
        for constraint in self.constraints:
            constraintstrs.append(str(constraint))
        INDENT = " " * 4
        chunks = (
            f"Problem with {len(self.free_params)} free parameter(s):",
            f"\n{INDENT}" + f"\n{INDENT}".join(primitivestrs),
            "\n",
            f"and {len(self.constraints)} constraint(s):",
            f"\n{INDENT}" + f"\n{INDENT}".join(constraintstrs),
            "\n",
            f"\n{INDENT}Total error: {self.error()}"
        )
        return "".join(chunks)
    
    def __getitem__(self, item)->"Primitive":
        try:
            return self.primitives[item]
        except KeyError:
            raise ValueError(f"{repr(item)} is not part of this problem")
    
    def _log(self, message, level):
        if not self.enable_log:
            return
        level = level.lower().strip()
        if level == 'warn':
            level = 'warning'
        getattr(_logger, level)(message)
    
    # region script import
    def load_script(self, code: str):
        '''
        Load primitives and constraints from a GeoGebra-liked script.
        Style settings will be ignored, e.g. `SetColor(A, "red")`/`Text(...), ...
        NOTE: 此script并非真正的GeoGebra脚本，是一种简化的类GeoGebra脚本格式，
            专门针对使AI更容易理解而设计，用于提供给LLM用来构造图像约束问题暴力求解.
        
        Supported commands:
            - ``Name = Point(Circle(...), ...)`` — point on a circle
            - ``Name = Line(A, B)`` — line through points A and B
            - ``Name = Point((x, y))`` or ``Name = (x, y)`` — free point
            - ``Name = Circle((cx, cy), r)`` — circle
            - ``Segment(A, B)`` or ``Name = Segment(A, B)`` — line segment
            - ``Name = Tangent(P, Circle)`` — tangent to circle at P
            - ``Name = Intersect(A, B)`` — intersection of two primitives
            - ``Name = Ray(A, B)`` — ray from A through B
            - ``SetAngle(A, B, C, deg°)`` — angle constraint at vertex B
            - ``SetFixed(Name, true/false)`` — fix a point
        '''
        lines = code.splitlines()
        unwanted_prefixes = [
            'SetColor', 'SetLineThickness', 'SetFilling', 'SetPointStyle', 'SetPointSize', 'Text',
            'Label', 'Hide', 'Show', 'SetVisible', 'SetCaption', 'SetFontSize', 'SetFontStyle', 'SetBold', 'SetItalic',
            'SetPointCaption', 'SetLineCaption', 'SetCircleCaption', 'SetEllipseCaption', 'SetArcCaption', 
            'SetTextCaption', 'SetSegmentCaption', 'SetRayCaption', 'SetVectorCaption'
        ]
        unwanted_rhs_patterns = [rf'^.*=\s*{p}\s*\(.*\)$' for p in unwanted_prefixes]
        
        # Symbol table: maps GeoGebra names → Problem2D primitives
        symbols: dict[str, Primitive] = {}
        # Cache for anonymous circles keyed by (cx, cy, r)
        _anon_circles: dict[tuple[float, float, float], Circle] = {}
        
        def _resolve(name: str) -> "Primitive|None":
            """Resolve a name to an existing primitive."""
            name = name.strip()
            if name in symbols:
                return symbols[name]
            if name in self.primitives:
                return self.primitives[name]
            if '(' in name and name.endswith(')') and not name.startswith('('):
                return _handle_rhs(name, lhs=None)
            return None
        
        def _parse_tuple(s: str) -> tuple[float, ...]|None:
            """Try to parse ``(a, b)`` into a tuple of floats."""
            s = s.strip()
            if s.startswith('(') and s.endswith(')'):
                inner = s[1:-1]
                parts = [p.strip() for p in inner.split(',')]
                try:
                    return tuple(float(p) for p in parts)
                except ValueError:
                    return None
            return None
        
        def _parse_args(s: str) -> list[str]:
            """Split top-level arguments respecting parentheses."""
            args: list[str] = []
            depth = 0
            current: list[str] = []
            for ch in s:
                if ch == '(':
                    depth += 1
                    current.append(ch)
                elif ch == ')':
                    depth -= 1
                    current.append(ch)
                elif ch == ',' and depth == 0:
                    args.append(''.join(current).strip())
                    current = []
                else:
                    current.append(ch)
            if current:
                args.append(''.join(current).strip())
            return args
        
        def _parse_call(s: str) -> tuple[str, list[str]]|None:
            """Parse ``FuncName(arg1, arg2, ...)`` → (FuncName, [arg1, arg2, ...])."""
            s = s.strip()
            idx = s.find('(')
            if idx < 0 or not s.endswith(')'):
                return None
            func = s[:idx].strip()
            inner = s[idx+1:-1]
            return func, _parse_args(inner)
        
        def _parse_angle_deg(s: str) -> float|None:
            """Parse ``34°`` or ``34`` into a float degree value."""
            s = s.strip().rstrip('°').strip()
            try:
                return float(s)
            except ValueError:
                return None
        
        def _ensure_point(name: str) -> "Point":
            """Get or create a free point by name."""
            prim = _resolve(name)
            if prim is not None and isinstance(prim, Point):
                return prim
            pt = self.add_point(name=name)
            symbols[name] = pt
            return pt
        
        def _handle_rhs(rhs: str, lhs: str|None = None):
            """Process the right-hand side expression, optionally assigning to *lhs*."""
            rhs = rhs.strip()
            
            # Bare tuple ``(x, y)`` → point
            tup = _parse_tuple(rhs)
            if tup is not None and len(tup) == 2 and lhs:
                pt = self.add_point(tup[0], tup[1], name=lhs)
                symbols[lhs] = pt
                return pt
            
            call = _parse_call(rhs)
            if call is None:
                return None
            func, args = call
            
            # ── Point ──
            if func == 'Point':
                # Point(Circle((cx,cy), r)) — point on a circle
                if len(args) >= 1:
                    inner_call = _parse_call(args[0])
                    if inner_call and inner_call[0] == 'Circle':
                        # First ensure the circle exists
                        circ = _handle_circle_expr(args[0], lhs=None)
                        if circ is not None and isinstance(circ, Circle):
                            name = lhs or None
                            pt = circ.create_point(name=name)
                            if lhs:
                                symbols[lhs] = pt
                            return pt
                    # Point((x, y)) — free point at coordinates
                    tup = _parse_tuple(args[0])
                    if tup is not None and len(tup) == 2:
                        name = lhs or None
                        pt = self.add_point(tup[0], tup[1], name=name)
                        if lhs:
                            symbols[lhs] = pt
                        return pt
                    # Point(existing_primitive) — e.g. Point on an existing object
                    prim = _resolve(args[0])
                    if prim is not None and isinstance(prim, Circle):
                        name = lhs or None
                        pt = prim.create_point(name=name)
                        if lhs:
                            symbols[lhs] = pt
                        return pt
                # Bare Point() — free point
                name = lhs or None
                pt = self.add_point(name=name)
                if lhs:
                    symbols[lhs] = pt
                return pt
            
            # ── Line ──
            if func == 'Line':
                if len(args) >= 2:
                    p1 = _ensure_point(args[0])
                    p2 = _ensure_point(args[1])
                    self._log(f'Creating line through points {p1.name} and {p2.name}', 'info')
                    ln = self.add_line(p1, p2, name=lhs)
                    if lhs:
                        symbols[lhs] = ln
                    return ln
            
            # ── Circle ──
            if func == 'Circle':
                return _handle_circle_expr(rhs, lhs)
            
            # ── Segment ──
            if func == 'Segment':
                if len(args) >= 2:
                    p1 = _ensure_point(args[0])
                    p2 = _ensure_point(args[1])
                    self._log(f'Creating segment between points {p1.name} and {p2.name}', 'info')
                    ln = self.add_line(p1, p2, name=lhs)
                    if lhs:
                        symbols[lhs] = ln
                    return ln
            
            # ── Ray ──
            if func == 'Ray':
                if len(args) >= 2:
                    p_origin = _ensure_point(args[0])
                    p_through = _ensure_point(args[1])
                    # Model ray as a long segment from origin through the through-point
                    dx = p_through.x - p_origin.x
                    dy = p_through.y - p_origin.y
                    length = math.sqrt(dx*dx + dy*dy)
                    if length < 1e-12:
                        length = 1.0
                        dx, dy = 1.0, 0.0
                    scale = 100.0 / length
                    far_name = f"__{lhs or 'ray'}_far__"
                    far_pt = self.add_point(
                        p_origin.x + dx * scale,
                        p_origin.y + dy * scale,
                        name=far_name, draw=False
                    )
                    ray_name = lhs or None
                    ray_line = self.add_line(p_origin, far_pt, name=ray_name)
                    # The ray must pass through the through-point
                    ray_line.constrain_point(p_through)
                    if lhs:
                        symbols[lhs] = ray_line
                    return ray_line
            
            # ── Tangent ──
            if func == 'Tangent':
                if len(args) >= 2:
                    pt_prim = _resolve(args[0])
                    circ_prim = _resolve(args[1])
                    if pt_prim is None:
                        pt_prim = _ensure_point(args[0])
                    if circ_prim is not None and isinstance(circ_prim, Circle) and isinstance(pt_prim, Point):
                        tangent_name = lhs or None
                        self._log(f'Creating tangent `{tangent_name}` at point {pt_prim.name} for circle {circ_prim.name}', 'info')
                        if tangent_name and tangent_name in self.primitives:
                            existing = self.primitives[tangent_name]    # type: ignore
                            if isinstance(existing, Line):
                                tline = existing
                            else:
                                raise ValueError(f"Cannot assign tangent to {repr(tangent_name)} since it is not a line")
                        elif tangent_name and len(tangent_name) == 2 and tangent_name.isalpha():
                            p1n, p2n = tangent_name[0], tangent_name[1]
                            p1, p2 = self.primitives.get(p1n, None), self.primitives.get(p2n, None)
                            if isinstance(p1, Point) and isinstance(p2, Point):
                                existing = (p1, p2)
                            elif isinstance(p1, Point) and p2 is None:
                                p2 = self.add_point(name=p2n)
                                existing = (p1, p2)
                            elif p1 is None and isinstance(p2, Point):
                                p1 = self.add_point(name=p1n)
                                existing = (p1, p2)
                            else:
                                existing = None
                        else:
                            existing = None
                        tline, _ = circ_prim.create_tangent(
                            touching_pt=pt_prim,
                            tangent_name=tangent_name,
                            touching_pt_within_line=True,
                            tangent_line=existing
                        )
                        if lhs:
                            symbols[lhs] = tline
                        return tline
            
            # ── Intersect ──
            if func == 'Intersect':
                if len(args) >= 2:
                    prim_a = _resolve(args[0])
                    prim_b = _resolve(args[1])
                    if prim_a is not None and prim_b is not None:
                        name = lhs or None
                        if name and name in self.primitives:
                            pt = self.primitives[name]
                            if not isinstance(pt, Point):
                                raise ValueError(f"Cannot assign intersection to {repr(name)} since it is not a point")
                        else:
                            pt = self.add_point(name=name)
                        self._log(f'Creating intersection between {prim_a.name} and {prim_b.name} at point {pt.name}', 'info')
                        if isinstance(prim_a, Line):
                            if not (pt == prim_a.start or pt == prim_a.end):
                                prim_a.constrain_point(pt)
                        if isinstance(prim_b, Line):
                            if not (pt == prim_b.start or pt == prim_b.end):
                                prim_b.constrain_point(pt)
                        if lhs:
                            symbols[lhs] = pt
                        return pt
                    else:
                        self._log(f"Failed to create intersection: could not resolve {args[0]} or {args[1]}", 'warning')
            
            # ── SetAngle ──
            if func == 'SetAngle':
                # SetAngle(ABC, deg°)
                if len(args) == 2 and len(args[0]) == 3 and len(args[1]) >= 1:  
                    p1n, p2n, p3n = args[0][0], args[0][1], args[0][2]
                    p1, p2, p3 = self.primitives.get(p1n, None), self.primitives.get(p2n, None), self.primitives.get(p3n, None)
                    all_pt_or_None = True
                    for p in (p1, p2, p3):
                        if not (p is None or isinstance(p, Point)):
                            all_pt_or_None = False
                            break
                    if all_pt_or_None:
                        points = []
                        for p, n in zip((p1, p2, p3), (p1n, p2n, p3n)):
                            if p is None:
                                p = self.add_point(name=n)
                                symbols[n] = p
                            points.append(n)
                        args = points + [args[1]]
                
                # SetAngle(A, B, C, deg°) — angle ∠ABC at vertex B
                if len(args) >= 4:
                    pA = _resolve(args[0])
                    pB = _resolve(args[1])  # vertex
                    pC = _resolve(args[2])
                    deg = _parse_angle_deg(args[3])
                    if (isinstance(pA, Point) and isinstance(pB, Point) and isinstance(pC, Point) and deg is not None):
                        self._log(f'Creating angle constraint ∠{pA.name if isinstance(pA, Point) else args[0]}{pB.name if isinstance(pB, Point) else args[1]}{pC.name if isinstance(pC, Point) else args[2]} = {deg}°', "info")
                        # Create (or reuse) lines BA and BC, then constrain angle
                        line_ba = self.add_line(pB, pA)
                        line_bc = self.add_line(pB, pC)
                        line_ba.constrain_angle_with(line_bc, deg)
                        return None
            
            # ── SetFixed ──
            if func == 'SetFixed':
                if len(args) >= 2:
                    prim = _resolve(args[0])
                    if prim is not None and isinstance(prim, Point):
                        val = args[1].strip().lower()
                        if val == 'true':
                            prim.fix()
                    return None
            
            return None
        
        def _handle_circle_expr(expr: str, lhs: str|None) -> "Circle|None":
            """Parse and create a Circle from ``Circle((cx,cy), r)``.
            
            Deduplicates: if an anonymous or named circle with the same
            (center_x, center_y, radius) already exists, reuse it.
            """
            call = _parse_call(expr)
            if call is None or call[0] != 'Circle':
                return None
            _, args = call
            if len(args) >= 2:
                center_tup = _parse_tuple(args[0])
                try:
                    radius = float(args[1].strip())
                except ValueError:
                    return None
                if center_tup is not None and len(center_tup) == 2:
                    cx, cy = center_tup
                    key = (cx, cy, radius)
                    
                    # Reuse existing circle with same name
                    if lhs and lhs in symbols and isinstance(symbols[lhs], Circle):
                        return symbols[lhs]  # type: ignore
                    if lhs and lhs in self.primitives and isinstance(self.primitives[lhs], Circle):
                        return self.primitives[lhs]  # type: ignore
                    
                    # Reuse anonymous circle with identical geometry
                    if key in _anon_circles:
                        circ = _anon_circles[key]
                        if lhs:
                            symbols[lhs] = circ
                        return circ
                    
                    # Create new circle
                    center_name = f"__{lhs or 'circle'}_center__"
                    # Reuse center point if one already exists at (cx, cy)
                    existing_center = _resolve(center_name)
                    if existing_center is not None and isinstance(existing_center, Point):
                        center_pt = existing_center
                    else:
                        center_pt = self.add_point(cx, cy, name=center_name, draw=False)
                        center_pt.fix()
                    circ = self.add_circle(center_pt, radius=radius, name=lhs)
                    circ.fix_center()
                    circ.fix_radius()
                    _anon_circles[key] = circ
                    if lhs:
                        symbols[lhs] = circ
                    return circ
            return None
        
        # ── Main parse loop ──
        for l in lines:
            l = l.strip()
            if l.startswith('#') or not l:
                continue
            ignore = False
            for prefix in unwanted_prefixes:
                if l.startswith(prefix + '('):
                    ignore = True
                    break
            if ignore:
                continue
            for p in unwanted_rhs_patterns:
                if re.match(p, l):
                    ignore = True
                    break
            if ignore:
                continue
            # Remove inline comments
            comment_idx = l.find('#')
            if comment_idx >= 0:
                l = l[:comment_idx].strip()
            if not l:
                continue
            
            # Assignment: ``Name = Expr``
            eq_idx = l.find('=')
            if eq_idx > 0:
                lhs_raw = l[:eq_idx].strip()
                rhs_raw = l[eq_idx+1:].strip()
                # Guard: skip if '=' is inside parentheses or is '==' etc.
                if l[eq_idx-1:eq_idx] not in ('!', '<', '>') and (eq_idx + 1 >= len(l) or l[eq_idx+1] != '='):
                    _handle_rhs(rhs_raw, lhs=lhs_raw)
                    continue
            
            # Bare call: ``Segment(P, Q)`` or ``SetAngle(...)``
            _handle_rhs(l, lhs=None)
    # endregion
    
    @property
    def _modified(self)->bool:
        return self.__modified__
    
    @_modified.setter
    def _modified(self, value: bool):
        self.__modified__ = value
        self._cached_points = None
        self._cached_fixed_point_names = None
        self._cached_free_params = None
    
    @property
    def points(self)->set["Point"]:
        '''All points in this problem.'''
        curr = getattr(self, '_cached_points', None)
        if curr is None:
            pts = set()
            for primitive in self.primitives.values():
                for point in primitive.points:
                    pts.add(point)
            self._cached_points = pts
            return pts
        return curr
    
    @property
    def fixed_point_names(self)->set[str]:
        '''Names of all fixed points in this problem.'''
        curr = getattr(self, '_cached_fixed_point_names', None)
        if curr is None:
            fixed = set()
            for primitive in self.primitives.values():
                for point in primitive.points:
                    if all(param.fixed for param in point.params):
                        fixed.add(point.name)
            self._cached_fixed_point_names = fixed
            return fixed
        return curr
    
    @property
    def free_params(self)->list[FreeParam]:
        """Free parameters in this problem (cached, stable order)."""
        curr = getattr(self, '_cached_free_params', None)
        if curr is None:
            seen = set()
            free_params = []
            for primitive in self.primitives.values():
                for param in primitive.params:
                    if not param.fixed and param.id not in seen:
                        seen.add(param.id)
                        free_params.append(param)
            self._cached_free_params = free_params
            return free_params
        return curr
    
    @property
    def free_values(self)->list[float]:
        return [p.value for p in self.free_params]
    
    def validate(self):
        """
        Validate the problem.
        This checks that primitives in the problem are valid, e.g. that lines have
        nonzero length.
        """
        status = [primitive.validate() for primitive in self.primitives.values()]
        invalid = list(filter(lambda s: isinstance(s, _InvalidPrimitive), status))

        if invalid:
            invalid_str = ", ".join(str(s) for s in invalid)
            raise ValueError(f"The following primitives are invalid: {invalid_str}")

    def _update(self, values: Sequence[float]):
        """Update current free parameter values."""
        for param, value in zip(self.free_params, values):
            param.value = value  # direct attribute set, skip .update() check since free_params are already filtered

    def error(self)->float:
        """Total weighted squared error across all constraints."""
        total = 0.0
        for c in self.constraints:
            v = c.value()
            total += c.weight * v * v
        return total
    
    @property
    def x_axis(self) -> Line:
        if self._x_axis is None:
            p1 = self.add_point(-1000, 0, name="__x_axis_start__")
            p2 = self.add_point(1000, 0, name="__x_axis_end__")
            self._x_axis = self.add_line(p1, p2, name="__x_axis__")
            p1.fix()
            p2.fix()
        return self._x_axis

    @property
    def y_axis(self) -> Line:
        if self._y_axis is None:
            p1 = self.add_point(0, -1000, name="__y_axis_start__")
            p2 = self.add_point(0, 1000, name="__y_axis_end__")
            self._y_axis = self.add_line(p1, p2, name="__y_axis__")
            p1.fix()
            p2.fix()
        return self._y_axis
    
    @cached_property
    def origin(self) -> Point:
        o = self.add_point(0, 0, name="__origin__", draw=False)
        o.fix()
        return o
    
    # region add primitives & constraints
    def clear(self):
        """Clear all primitives and constraints from this problem."""
        self.primitives.clear()
        self.constraints.clear()
        self._modified = True
        self._x_axis = None
        self._y_axis = None
        if hasattr(self, '_cached_points'):
            del self._cached_points
        if hasattr(self, '_cached_fixed_point_names'):
            del self._cached_fixed_point_names
        if hasattr(self, '_cached_free_params'):
            del self._cached_free_params
        for p_cls in Primitive.__subclasses__():
            p_cls.__NameCounter__ = 0
    
    def _add_primitive(self, primitive: Primitive):
        if primitive.name in self.primitives:
            raise ValueError(f"{repr(primitive.name)} already in problem")
        self.primitives[primitive.name] = primitive

    def add_point(self, x: float = 0, y: float = 0, name: str | None = None, **kwargs) -> Point:
        if not name:
            name = f"p{Point.__NameCounter__}"
            Point.__NameCounter__ += 1
        pt = Point(name, x, y, problem=self, **kwargs)
        pt.problem = self   # type: ignore
        self._add_primitive(pt)
        return pt   # type: ignore

    def add_line(self, start: Point, end: Point, name: str | None = None, **kwargs) -> Line:
        assert start != end, "Start and end points of a line cannot be the same."
        if not name:
            if not (start.name.startswith("__") or end.name.startswith("__")):
                join_pattern = re.compile(r'^[a-zA-Z](\d+)?$')
                if join_pattern.match(start.name) and join_pattern.match(end.name):
                    name = f"{start.name}{end.name}"
                else:
                    name = f'{start.name}_{end.name}'
            else:
                name = f"l{Line.__NameCounter__}"
                Line.__NameCounter__ += 1
        if curr := self.primitives.get(name, None):
            if not isinstance(curr, Line):
                raise ValueError(f"Primitive '{name}' already exists and is not a Line.")
            return curr     # type: ignore
        ln = Line(name, start=start, end=end, problem=self, **kwargs)
        ln.problem = self   # type: ignore
        self._add_primitive(ln)
        return ln   # type: ignore

    def add_circle(self, center: Point|None=None, radius: float = 1, name: str | None = None, **kwargs) -> Circle:
        if center is None:
            center = self.origin
        if name is None:
            name = f"c{Circle.__NameCounter__}"
            Circle.__NameCounter__ += 1
        circle = Circle(name=name, center=center, radius=radius, problem=self, **kwargs)
        self._add_primitive(circle)
        return circle

    def add_constraint(self, constraint: Constraint):
        """Add a constraint with safe pre-conditioning.
        
        If there are already constraints in the system with a good solution,
        we save state before precondition and restore if it makes things worse.
        This prevents a single new constraint's precondition from destroying
        an already-converged solution.
        """
        self._modified = True
        
        # Check current error BEFORE adding the new constraint
        err_before = self.error() if self.constraints else float('inf')
        x_before = list(self.free_values) if self.constraints else None
        
        self.constraints.append(constraint)
        self._modified = True
        
        # Run precondition for the new constraint
        constraint.precondition(self)
        if x_before is not None and err_before < 1.0:
            old_err_after = sum(c.error() for c in self.constraints[:-1])
            if old_err_after > err_before:  # precondition badly damaged existing solution
                # Restore previous state — the optimizer will handle it
                self._update(x_before)
                self._modified = True
    # endregion
    
    # region solver
    def _constraint_jacobian(self, step: float = 1e-7) -> np.ndarray:
        """
        Compute the constraint Jacobian matrix numerically.
        
        J[i, j] = ∂(constraint_i.value) / ∂(param_j)
        
        Shape: (n_constraints, n_free_params)
        """
        params = list(self.free_params)
        n_params = len(params)
        n_constraints = len(self.constraints)
        if n_params == 0 or n_constraints == 0:
            return np.zeros((n_constraints, n_params))
        
        J = np.zeros((n_constraints, n_params))
        
        # Evaluate base constraint values
        base_vals = np.array([c.value() for c in self.constraints], dtype=float)
        
        for j, param in enumerate(params):
            old_val = param.value
            param.value = old_val + step
            perturbed_vals = np.array([c.value() for c in self.constraints], dtype=float)
            J[:, j] = (perturbed_vals - base_vals) / step
            param.value = old_val  # restore
        
        return J
    
    @property
    def dof(self) -> int:
        """
        Accurate degrees of freedom via Jacobian rank.
        
        DOF = n_free_params - rank(J)
        
        where rank(J) counts the number of independent constraints that 
        actually reduce degrees of freedom. Redundant constraints (linearly
        dependent rows) are automatically excluded.
        """
        n_free = len(self.free_params)
        n_constraints = len(self.constraints)
        if n_free == 0:
            return 0
        if n_constraints == 0:
            return n_free
        J = self._constraint_jacobian()
        rank = int(np.linalg.matrix_rank(J, tol=1e-5))
        return max(0, n_free - rank)

    @property
    def dof_naive(self) -> int:
        """Simple DOF estimate: free params - constraint count (fast, no Jacobian)."""
        return max(0, len(self.free_params) - len(self.constraints))
    
    def _auto_precondition_passes(self) -> int:
        """
        Auto-select precondition passes based on constraint coupling.
        
        Coupling density = average number of constraints sharing parameters
        with each other. Higher coupling → more passes needed for iterative
        projection to converge.
        """
        n_constraints = len(self.constraints)
        n_free = len(self.free_params)
        if n_constraints == 0 or n_free == 0:
            return 5
        
        # Compute coupling: how many constraint pairs share parameters
        constraint_params = [c.params for c in self.constraints]
        total_overlap = 0
        for i in range(n_constraints):
            for j in range(i + 1, n_constraints):
                if constraint_params[i] & constraint_params[j]:  # shared params
                    total_overlap += 1
        
        max_pairs = n_constraints * (n_constraints - 1) / 2 if n_constraints > 1 else 1
        coupling_density = total_overlap / max_pairs  # 0.0 ~ 1.0
        
        # Base passes + scaling by coupling and constraint count
        base = 8
        passes = int(base + coupling_density * 15 + np.sqrt(n_constraints) * 2)
        return min(passes, 60)  # cap to avoid excessive iteration

    def precondition(self, passes: int|None = None):
        """
        Iteratively apply analytic pre-conditioning for all constraints.

        Multiple passes help resolve conflicts between interdependent constraints.
        The order is reversed on alternate passes for better convergence.
        
        When within-line (segment) constraints exist, a **phased** approach is
        used within each pass:
        
        1. First, apply all non-angle constraints (point-on-line, segment,
           perpendicular, length, horizontal, etc.) so points are correctly
           positioned on their segments.
        2. Then, apply angle constraints which use topology-aware orientation
           selection.  Because points are already clamped to segments, the
           ``_pick_topology_safe_orientation`` check sees meaningful geometry.
        3. Finally, re-clamp segment constraints that may have been disrupted
           by the angle rotations.
        """
        if passes is None:
            passes = self._auto_precondition_passes()
        
        # Classify constraints for phased precondition
        seg_constraints = [c for c in self.constraints
                          if isinstance(c, PointOnLineSegmentConstraint)]
        has_segments = len(seg_constraints) > 0
        
        if has_segments:
            # Rotation-based constraints (angle + perpendicular) that are
            # topology-aware go into Phase 2.  Everything else into Phase 1.
            rotation_types = (LineAngleConstraint, PerpendicularLineConstraint)
            angle_constraints = [c for c in self.constraints
                                if isinstance(c, rotation_types)]
            other_constraints = [c for c in self.constraints
                                if not isinstance(c, rotation_types)]
            
            for i in range(passes):
                # Phase 1: non-angle constraints (project points onto lines, clamp segments)
                order_other = other_constraints if i % 2 == 0 else list(reversed(other_constraints))
                for constraint in order_other:
                    constraint.precondition(self)
                # Phase 2: angle constraints (topology-aware)
                order_angle = angle_constraints if i % 2 == 0 else list(reversed(angle_constraints))
                for constraint in order_angle:
                    constraint.precondition(self)
                # Phase 3: re-clamp segments
                for sc in seg_constraints:
                    sc.precondition(self)
                err = self.error()
                if err < 1e-10:
                    break
        else:
            for i in range(passes):
                order = self.constraints if i % 2 == 0 else reversed(self.constraints)
                for constraint in order:
                    constraint.precondition(self)
                err = self.error()
                if err < 1e-10:
                    break

    def _find_circle_groups(self) -> list[tuple["Circle", list["Point"]]]:
        """Find circles with multiple free constrained points.
        
        Returns list of (circle, [free_points_on_circle]).
        Used for intelligent initialization — spreading points around circles
        to avoid degenerate collapse.
        """
        groups = []
        for prim in self.primitives.values():
            if isinstance(prim, Circle):
                free_pts = []
                for pt_name in prim._constraint_pts:
                    pt = self.primitives.get(pt_name)
                    if pt is not None and isinstance(pt, Point):
                        if pt.name not in self.fixed_point_names:
                            free_pts.append(pt)
                if len(free_pts) >= 2:
                    groups.append((prim, free_pts))
        return groups

    def _spread_circle_points(self, circle_groups: list[tuple["Circle", list["Point"]]], 
                               offset_angle: float = 0.0,
                               shuffle: bool = False):
        """Spread free points evenly around their circles.
        
        For each circle with N free points, place them at evenly spaced 
        angles (2π/N apart), starting from offset_angle.
        Fixed points on the circle influence the placement to avoid overlap.
        """
        for circle, free_pts in circle_groups:
            if shuffle and len(free_pts) > 1:
                free_pts = free_pts[:]
                np.random.shuffle(free_pts) # type: ignore
            cx, cy = circle.center.x, circle.center.y
            r = circle.radius
            
            # Collect angles of fixed points on this circle
            fixed_angles = []
            for pt_name in circle._constraint_pts:
                pt = self.primitives.get(pt_name)
                if pt is not None and isinstance(pt, Point):
                    if pt.name in self.fixed_point_names:
                        a = math.atan2(pt.y - cy, pt.x - cx)
                        fixed_angles.append(a)
            
            n_free = len(free_pts)
            n_total = n_free + len(fixed_angles)
            
            if n_total <= 1:
                continue
            
            # Compute evenly-spaced angles avoiding fixed points
            spacing = 2 * math.pi / n_total
            
            # Start from offset_angle, skip positions near fixed angles
            candidate_angles = []
            for i in range(n_total):
                a = offset_angle + i * spacing
                candidate_angles.append(a)
            
            # Remove candidates too close to fixed angles
            if fixed_angles:
                available = []
                for ca in candidate_angles:
                    too_close = False
                    for fa in fixed_angles:
                        diff = abs(((ca - fa + math.pi) % (2 * math.pi)) - math.pi)
                        if diff < spacing * 0.3:
                            too_close = True
                            break
                    if not too_close:
                        available.append(ca)
            else:
                available = candidate_angles
            
            # Assign angles to free points
            for i, pt in enumerate(free_pts):
                if i < len(available):
                    angle = available[i]
                else:
                    angle = offset_angle + (i + len(fixed_angles)) * spacing
                pt.x = cx + r * math.cos(angle)
                pt.y = cy + r * math.sin(angle)

    def solve(
        self,
        accept_error: float = 1e-11,
        update_when_failed: bool = True,
        precondition_passes: int|None = None,
        local_restarts: int = 10,
        random_perturbations: int = 5,
    ):
        """
        Solve the constraint problem using Levenberg-Marquardt.

        Strategy:
            1. Circle-aware initialization (spread points around circles).
            2. Pre-conditioning: analytic projection (multiple passes).
            3. Levenberg-Marquardt (LM) to solve F(x)=0 as a root-finding problem.
            4. Multi-start with circle rotations and topology flipping.

        Parameters
        ----------
        accept_error : float
            Error threshold below which the solution is considered successful.
        update_when_failed : bool
            If True, keep the best-found solution even if above accept_error.
        precondition_passes : int
            Number of analytic pre-conditioning iterations.
        """
        self._modified = True
        
        def _finish(error, success):
            return self._make_result(error, success)
        
        n_params = len(self.free_params)
        n_constraints = len(self.constraints)
        
        if n_params == 0 or n_constraints == 0:
            return _finish(self.error(), self.error() < accept_error)
        
        # Collect within-line topology info
        _within_checks: list[tuple[Line, set[str]]] = []
        for prim in self.primitives.values():
            if isinstance(prim, Line):
                within = getattr(prim, '_within_line_points', set())
                if within:
                    _within_checks.append((prim, within))
        has_order = len(_within_checks) > 0
        
        def _topology_ok() -> bool:
            for line, pt_names in _within_checks:
                x1 = line.start.params[0].value
                y1 = line.start.params[1].value
                x2 = line.end.params[0].value
                y2 = line.end.params[1].value
                dx, dy = x2 - x1, y2 - y1
                len_sq = dx * dx + dy * dy
                if len_sq < 1e-24:
                    return False
                for pt_name in pt_names:
                    prim_pt = self.primitives.get(pt_name)
                    if prim_pt is None:
                        continue
                    px = prim_pt.params[0].value
                    py = prim_pt.params[1].value
                    t = ((px - x1) * dx + (py - y1) * dy) / len_sq
                    if t < -0.01 or t > 1.01:
                        return False
            return True

        if precondition_passes is None:
            precondition_passes = self._auto_precondition_passes()
        
        # Save original state
        xpre = list(self.free_values)
        
        # Build param index map for fast Jacobian construction
        params = self.free_params
        param_id_to_idx = {p.id: i for i, p in enumerate(params)}
        
        # Identify which constraints are "segment" (inequality) vs equality
        seg_indices = set()
        for i, c in enumerate(self.constraints):
            if isinstance(c, PointOnLineSegmentConstraint):
                seg_indices.add(i)

        # Find circle groups for intelligent initialization
        circle_groups = self._find_circle_groups()
        
        # Soft separation regularization for points on the same circle
        # (prevents collapse into degenerate local minima)
        sep_pairs: list[tuple[Point, Point, float]] = []
        sep_weight = 0.08
        for circle, pts in circle_groups:
            if len(pts) < 2:
                continue
            min_sep = max(1e-3, 0.12 * circle.radius)
            for i in range(len(pts)):
                for j in range(i + 1, len(pts)):
                    sep_pairs.append((pts[i], pts[j], min_sep))
        n_sep = len(sep_pairs)
        n_total_constraints = n_constraints + n_sep
        
        # Identify which free params belong to circle-constrained points
        # so we can jitter non-circle params independently during restarts
        circle_param_ids: set = set()
        if circle_groups:
            for _, pts in circle_groups:
                for pt in pts:
                    for p in pt.params:
                        circle_param_ids.add(p.id)
        non_circle_indices = [i for i, p in enumerate(params) 
                              if p.id not in circle_param_ids]

        # ── Residual & Jacobian builder (finite-difference) ──
        
        def _build_residual_and_jacobian():
            """Build the residual vector F and Jacobian matrix J using finite differences."""
            F = np.zeros(n_total_constraints, dtype=float)
            
            # Compute residuals
            for i, c in enumerate(self.constraints):
                v = c.value()
                if i in seg_indices and abs(v) < 1e-12:
                    F[i] = 0.0
                    continue
                w_sqrt = math.sqrt(c.weight) if c.weight != 1.0 else 1.0
                F[i] = v * w_sqrt
            
            # Circle separation residuals (soft regularization)
            if n_sep:
                base = n_constraints
                for k, (p1, p2, min_sep) in enumerate(sep_pairs):
                    dx = p1.x - p2.x
                    dy = p1.y - p2.y
                    dist = math.sqrt(dx * dx + dy * dy)
                    if dist >= min_sep:
                        F[base + k] = 0.0
                    else:
                        F[base + k] = (min_sep - dist) * sep_weight

            # Build Jacobian via central finite differences
            step = 1e-7
            J = np.zeros((n_total_constraints, n_params), dtype=float)
            for j, p in enumerate(params):
                old = p.value
                
                # Forward
                p.value = old + step
                Fp = np.zeros(n_total_constraints, dtype=float)
                for i, c in enumerate(self.constraints):
                    v = c.value()
                    if i in seg_indices and abs(v) < 1e-12:
                        continue
                    w_sqrt = math.sqrt(c.weight) if c.weight != 1.0 else 1.0
                    Fp[i] = v * w_sqrt
                if n_sep:
                    base = n_constraints
                    for k, (p1, p2, min_sep) in enumerate(sep_pairs):
                        dx = p1.x - p2.x
                        dy = p1.y - p2.y
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist >= min_sep:
                            Fp[base + k] = 0.0
                        else:
                            Fp[base + k] = (min_sep - dist) * sep_weight
                
                # Backward
                p.value = old - step
                Fm = np.zeros(n_total_constraints, dtype=float)
                for i, c in enumerate(self.constraints):
                    v = c.value()
                    if i in seg_indices and abs(v) < 1e-12:
                        continue
                    w_sqrt = math.sqrt(c.weight) if c.weight != 1.0 else 1.0
                    Fm[i] = v * w_sqrt
                if n_sep:
                    base = n_constraints
                    for k, (p1, p2, min_sep) in enumerate(sep_pairs):
                        dx = p1.x - p2.x
                        dy = p1.y - p2.y
                        dist = math.sqrt(dx * dx + dy * dy)
                        if dist >= min_sep:
                            Fm[base + k] = 0.0
                        else:
                            Fm[base + k] = (min_sep - dist) * sep_weight
                
                p.value = old
                J[:, j] = (Fp - Fm) / (2 * step)
            
            return F, J
        
        def _lm_solve(max_iter: int = 200, tol: float = 1e-12) -> tuple[float, bool]:
            """Run Levenberg-Marquardt solver.
            
            Solves min ||F(x)||^2 where F is the vector of weighted constraint residuals.
            Uses (J^T J + λ diag(J^T J)) dx = -J^T F with adaptive damping.
            
            Enhanced stall detection: tracks relative improvement over sliding
            windows to abandon hopeless starting points quickly.
            """
            F, J = _build_residual_and_jacobian()
            err = float(F @ F)
            
            # Initial lambda: Marquardt's recommendation
            JtJ = J.T @ J
            lam = 1e-3 * max(np.diag(JtJ).max(), 1e-6)
            nu = 2.0
            
            stall_count = 0
            prev_err = err
            # Track error at checkpoints for relative progress detection
            checkpoint_err = err
            checkpoint_iter = 0
            accepted_steps = 0
            
            for iteration in range(max_iter):
                if err < tol:
                    return err, True
                
                # Relative progress check every 10 accepted steps:
                # If error hasn't dropped by at least 30% in the last window,
                # and we're still far from the target, give up on this start.
                # But if we're close to converging (err < 1.0), be more patient.
                if accepted_steps > 0 and accepted_steps - checkpoint_iter >= 10:
                    if err > 1.0:
                        # Far from solution — require 30% drop
                        relative_drop = (checkpoint_err - err) / max(checkpoint_err, 1e-30)
                        if relative_drop < 0.3:
                            return err, False
                    elif err > accept_error * 100:
                        # Getting close — require only 10% drop (more patient)
                        relative_drop = (checkpoint_err - err) / max(checkpoint_err, 1e-30)
                        if relative_drop < 0.1:
                            return err, False
                    checkpoint_err = err
                    checkpoint_iter = accepted_steps
                
                JtF = J.T @ F
                
                # Check gradient norm for convergence
                g_norm = np.max(np.abs(JtF))
                if g_norm < 1e-14:
                    return err, err < tol
                
                # Solve (JtJ + lam * diag(JtJ)) * dx = -JtF
                diag = np.diag(JtJ).copy()
                diag[diag < 1e-10] = 1e-10  # prevent zero diagonal
                A = JtJ + lam * np.diag(diag)
                
                try:
                    dx = np.linalg.solve(A, -JtF)
                except np.linalg.LinAlgError:
                    lam *= 4.0
                    nu = 2.0
                    continue
                
                # Check step size
                dx_norm = np.linalg.norm(dx)
                x_norm = np.linalg.norm([p.value for p in params])
                if dx_norm < 1e-14 * (x_norm + 1e-14):
                    return err, err < tol
                
                # Trial step
                x_old = [p.value for p in params]
                for k, p in enumerate(params):
                    p.value = x_old[k] + dx[k]
                
                F_new, J_new = _build_residual_and_jacobian()
                err_new = float(F_new @ F_new)
                
                # Gain ratio
                predicted = float(dx @ (lam * diag * dx - JtF))
                if predicted > 0:
                    rho = (err - err_new) / predicted
                else:
                    rho = -1.0
                
                if rho > 0.0001:
                    # Accept step
                    F, J = F_new, J_new
                    JtJ = J.T @ J
                    err = err_new
                    lam *= max(1.0/3.0, 1.0 - (2.0 * rho - 1.0)**3)
                    nu = 2.0
                    accepted_steps += 1
                    
                    # Absolute stall detection
                    if abs(prev_err - err) < 1e-15 * max(1.0, err):
                        stall_count += 1
                        if stall_count > 12:
                            return err, err < tol
                    else:
                        stall_count = 0
                    prev_err = err
                else:
                    # Reject step — restore
                    for k, p in enumerate(params):
                        p.value = x_old[k]
                    lam *= nu
                    nu *= 2.0
                    if lam > 1e16:
                        lam = 1e-3
                        nu = 2.0
            
            return err, err < tol
        
        def _ensure_angle_other_flags():
            """Re-detect _other flag for all LineAngleConstraint instances
            based on current geometry (SolveSpace's ModifyToSatisfy pattern).
            Called before each LM solve to ensure the cos-residual sign
            matches the current geometric configuration."""
            for c in self.constraints:
                if isinstance(c, LineAngleConstraint):
                    c._auto_detect_other()

        def _try_solve_from_current(skip_precondition: bool = False) -> tuple[float, list[float], bool]:
            """Precondition + LM from current state. Returns (err, x, topo_ok).
            
            **Precondition-skip heuristic**: if precondition increases
            error by more than 50%, also try LM from the pre-precondition
            state and keep whichever result is better.  This prevents the
            precondition from pushing the state into a worse basin.
            """
            _ensure_angle_other_flags()

            if not skip_precondition:
                x_before = list(self.free_values)
                err_before = self.error()
                
                self.precondition(passes=precondition_passes)
                err_after = self.error()
                
                if err_after < accept_error:
                    x = list(self.free_values)
                    return err_after, x, (not has_order or _topology_ok())
                
                # If precondition made things worse, try both paths
                precondition_helped = err_after <= err_before * 1.5
                
                if not precondition_helped:
                    # Try LM from preconditioned state first
                    _ensure_angle_other_flags()
                    err_lm1, _ = _lm_solve()
                    err1 = self.error()
                    x1 = list(self.free_values)
                    topo1 = not has_order or _topology_ok()
                    
                    # Also try LM from the pre-precondition state
                    self._update(x_before)
                    _ensure_angle_other_flags()
                    err_lm2, _ = _lm_solve()
                    err2 = self.error()
                    x2 = list(self.free_values)
                    topo2 = not has_order or _topology_ok()
                    
                    # Return the better result
                    if err1 <= err2:
                        return err1, x1, topo1
                    else:
                        return err2, x2, topo2
                
                # Precondition helped — proceed normally
                _ensure_angle_other_flags()
                err_lm, converged = _lm_solve()
                final_err = self.error()
                x = list(self.free_values)
                topo = not has_order or _topology_ok()
                return final_err, x, topo
            else:
                _ensure_angle_other_flags()
                err_pre = self.error()
                if err_pre < accept_error:
                    x = list(self.free_values)
                    return err_pre, x, (not has_order or _topology_ok())
                
                # Run LM solver
                err_lm, converged = _lm_solve()
                final_err = self.error()
                x = list(self.free_values)
                topo = not has_order or _topology_ok()
                return final_err, x, topo
        
        # ═══════════ Main solve strategy ═══════════
        
        best_x = list(self.free_values)
        best_err = self.error()
        topo_best_x: list[float] = []
        topo_best_err: float = float('inf')
        
        def _record(err: float, x: list[float], topo: bool):
            nonlocal best_err, best_x, topo_best_err, topo_best_x
            if err < best_err:
                best_err = err
                best_x = x[:]
            if topo and err < topo_best_err:
                topo_best_err = err
                topo_best_x = x[:]
        
        def _is_done() -> bool:
            if not has_order:
                return best_err <= accept_error
            return topo_best_err <= accept_error
        
        # ── Attempt 1: From initial state with circle spreading (no precondition) ──
        if circle_groups:
            self._spread_circle_points(circle_groups, offset_angle=0.0)
            err, x, topo = _try_solve_from_current(skip_precondition=True)
        else:
            err, x, topo = _try_solve_from_current()
        _record(err, x, topo)
        if _is_done():
            self._update(topo_best_x if has_order else best_x)
            final = topo_best_err if has_order else best_err
            return _finish(final, True)
        
        # ── Attempt 2: From original pre-solve state with precondition ──
        self._update(xpre)
        err, x, topo = _try_solve_from_current()
        _record(err, x, topo)
        if _is_done():
            self._update(topo_best_x if has_order else best_x)
            final = topo_best_err if has_order else best_err
            return _finish(final, True)
        
        # Characteristic scale for jittering
        x0_base = np.array(xpre, dtype=float)
        char_scale = max(3.0, np.max(np.abs(x0_base)) * 0.2) if n_params > 0 else 3.0
        
        # ── Attempt 3: Circle-rotation restarts (main strategy for circle problems) ──
        # Use many evenly-spaced offsets for thorough coverage.
        # Skip precondition — it collapses circle points together.
        # Also jitter non-circle points to explore different basins.
        n_circle_restarts = 36 if circle_groups else 0
        for i in range(n_circle_restarts):
            self._update(xpre)
            # Jitter non-circle free params to avoid all restarts landing in same basin
            if non_circle_indices and i >= 1:
                jitter_scale = char_scale * (0.05 + 0.4 * (i / n_circle_restarts))
                x_cur = list(self.free_values)
                for idx in non_circle_indices:
                    x_cur[idx] += np.random.randn() * jitter_scale
                self._update(x_cur)
            # Use golden-ratio spacing for optimal angular coverage
            offset = 2 * math.pi * (i + 1) * 0.6180339887  # golden ratio
            self._spread_circle_points(circle_groups, offset_angle=offset)
            err, x, topo = _try_solve_from_current(skip_precondition=True)
            _record(err, x, topo)
            if _is_done():
                self._update(topo_best_x if has_order else best_x)
                final = topo_best_err if has_order else best_err
                return _finish(final, True)
        
        # ── Attempt 4: Jittered restarts with circle spreading ──
        # Jitter non-circle points while using circle-spread for circle points
        
        for i in range(local_restarts):
            noise_scale = char_scale * (0.15 + 1.0 * i / max(local_restarts, 1))
            x_jittered = x0_base + np.random.randn(n_params) * noise_scale
            self._update(x_jittered.tolist())
            # Spread circle points and skip precondition
            if circle_groups:
                self._spread_circle_points(circle_groups, offset_angle=np.random.uniform(0, 2 * math.pi))
                err, x, topo = _try_solve_from_current(skip_precondition=True)
            else:
                err, x, topo = _try_solve_from_current()
            _record(err, x, topo)
            if _is_done():
                self._update(topo_best_x if has_order else best_x)
                final = topo_best_err if has_order else best_err
                return _finish(final, True)
        
        # ── Attempt 5: Topology-flipping restarts ──
        if has_order and not _is_done():
            lines_with_within = [line for line, _ in _within_checks]
            n_lines = len(lines_with_within)
            if n_lines <= 4:
                combos = range(1, 1 << n_lines)
            else:
                combos = [np.random.randint(1, 1 << n_lines) for _ in range(15)]
            
            for combo in combos:
                self._update(xpre)
                if circle_groups:
                    self._spread_circle_points(circle_groups, offset_angle=np.random.uniform(0, 2 * math.pi))
                for bit in range(n_lines):
                    if combo & (1 << bit):
                        line = lines_with_within[bit]
                        sx, sy = line.start.x, line.start.y
                        ex, ey = line.end.x, line.end.y
                        line.start.x, line.start.y = ex, ey
                        line.end.x, line.end.y = sx, sy
                err, x, topo = _try_solve_from_current(skip_precondition=bool(circle_groups))
                _record(err, x, topo)
                if _is_done():
                    self._update(topo_best_x if has_order else best_x)
                    final = topo_best_err if has_order else best_err
                    return _finish(final, True)
        
        # ── Attempt 6: Larger random perturbations ──
        for _ in range(random_perturbations):
            x_rand = x0_base + np.random.randn(n_params) * char_scale * 3.0
            self._update(x_rand.tolist())
            if circle_groups:
                self._spread_circle_points(circle_groups, offset_angle=np.random.uniform(0, 2 * math.pi))
                err, x, topo = _try_solve_from_current(skip_precondition=True)
            else:
                err, x, topo = _try_solve_from_current()
            _record(err, x, topo)
            if _is_done():
                self._update(topo_best_x if has_order else best_x)
                final = topo_best_err if has_order else best_err
                return _finish(final, True)

        # ── Attempt 7: Best-so-far perturbation restarts ──
        # Perturb the best solution found so far with small noise and
        # re-solve.  Much more effective than random restarts because we
        # start near a known near-solution basin.
        if not _is_done() and best_err < float('inf'):
            best_base = np.array(best_x, dtype=float)
            n_best_perturb = 30
            for i in range(n_best_perturb):
                # Geometrically increasing noise: from very small (0.1% of
                # values) to moderate (30% of char_scale)
                scale = char_scale * (0.001 + 0.3 * (i / max(n_best_perturb - 1, 1)))
                x_perturbed = best_base + np.random.randn(n_params) * scale
                self._update(x_perturbed.tolist())
                if circle_groups:
                    # Re-project circle points onto their circles
                    for circle, pts in circle_groups:
                        cx, cy = circle.center.x, circle.center.y
                        r = circle.radius
                        for pt in pts:
                            dx = pt.x - cx
                            dy = pt.y - cy
                            dist = math.sqrt(dx * dx + dy * dy)
                            if dist > 1e-12:
                                pt.x = cx + r * dx / dist
                                pt.y = cy + r * dy / dist
                err, x, topo = _try_solve_from_current(skip_precondition=True)
                _record(err, x, topo)
                if _is_done():
                    self._update(topo_best_x if has_order else best_x)
                    final = topo_best_err if has_order else best_err
                    return _finish(final, True)

        # ── Phase 2: Strengthened circle separation + shuffled spreads ──
        if circle_groups and not _is_done():
            # Increase separation weight to repel collapsed solutions
            sep_weight = 0.2
            n_circle_restarts2 = 48
            for i in range(n_circle_restarts2):
                self._update(xpre)
                if non_circle_indices:
                    jitter_scale = char_scale * (0.1 + 0.6 * (i / n_circle_restarts2))
                    x_cur = list(self.free_values)
                    for idx in non_circle_indices:
                        x_cur[idx] += np.random.randn() * jitter_scale
                    self._update(x_cur)
                offset = 2 * math.pi * (i + 1) / n_circle_restarts2
                self._spread_circle_points(circle_groups, offset_angle=offset, shuffle=True)
                err, x, topo = _try_solve_from_current(skip_precondition=True)
                _record(err, x, topo)
                if _is_done():
                    self._update(topo_best_x if has_order else best_x)
                    final = topo_best_err if has_order else best_err
                    return _finish(final, True)

        # ── Phase 3: Final best-so-far refinement ──
        # If we're still close but not converged, try fine perturbations
        # from the best solution found across all previous attempts.
        if not _is_done() and best_err < 1.0:
            best_base = np.array(best_x, dtype=float)
            for i in range(20):
                scale = max(0.001, best_err) * (0.5 + 2.0 * i / 19.0)
                x_perturbed = best_base + np.random.randn(n_params) * scale
                self._update(x_perturbed.tolist())
                if circle_groups:
                    for circle, pts in circle_groups:
                        cx, cy = circle.center.x, circle.center.y
                        r = circle.radius
                        for pt in pts:
                            dx = pt.x - cx
                            dy = pt.y - cy
                            dist = math.sqrt(dx * dx + dy * dy)
                            if dist > 1e-12:
                                pt.x = cx + r * dx / dist
                                pt.y = cy + r * dy / dist
                err, x, topo = _try_solve_from_current(skip_precondition=True)
                _record(err, x, topo)
                if _is_done():
                    self._update(topo_best_x if has_order else best_x)
                    final = topo_best_err if has_order else best_err
                    return _finish(final, True)
        
        # ── Finalize ──
        final_err = best_err
        final_x = best_x
        if has_order and topo_best_x and topo_best_err < best_err * 10:
            final_err = topo_best_err
            final_x = topo_best_x
        
        success = final_err <= accept_error
        if not success:
            warnings.warn(
                f"Solver did not reach target error. "
                f"Final error: {final_err:.2e} (target: {accept_error:.2e})",
                RuntimeWarning
            )
        
        if success or update_when_failed:
            self._update(final_x)
        else:
            self._update(xpre)
        
        return _finish(final_err, success)

    @staticmethod
    def _make_result(error: float, success: bool)->OptimizeResult:
        """Create a simple result object."""
        res = OptimizeResult()
        res.fun = error
        res.success = success
        return res
    # endregion
    
    # region plot & info extraction
    @dataclass
    class _ProblemInfo:
        infos: list[_DrawnInfo]
        image: bytes | None = None
    
    def get_info(self, wanted_info: Sequence[WantedInfoType], draw_image: bool=False)-> _ProblemInfo:
        '''Get the requested info (angle values, lengths, coordinates) and optionally an image.'''
        drawn_infos: list[_DrawnInfo] = []
        image_bytes = self.plot(
            mode='image',
            show_important_angles=False,
            show_axes=False,
            wanted_info=wanted_info,
            _drawn_infos=drawn_infos,
            _no_draw=not draw_image,  
        )   # type: ignore
        return self._ProblemInfo(
            infos=drawn_infos,
            image=image_bytes,
        )
        
    @overload
    def plot(self, mode: Literal['show']='show', show_important_angles: bool=False, show_axes: bool=False, wanted_info: Sequence[WantedInfoType]|None = None)->None:
        ...
        
    @overload
    def plot(self, mode: Literal['image']='image', show_important_angles: bool=False, show_axes: bool=False, wanted_info: Sequence[WantedInfoType]|None = None)->bytes:
        ...

    def plot(
        self, 
        mode: Literal['show', 'image'] = 'show', 
        show_important_angles: bool=False,
        show_axes: bool=False,
        wanted_info: Sequence[WantedInfoType]|None = None,
        # private use
        _drawn_infos: list[_DrawnInfo]|None = None,
        _no_draw: bool = False,
    ):
        '''Draw the problem.'''
        if mode == 'image':
            matplotlib.use('Agg')
        else:
            matplotlib.use('TkAgg')
            
        fig = plt.figure()
        ax = fig.gca()
        ax.set_aspect("equal", "datalim")

        if not show_axes:
            ax.set_axis_off()

        max_x, max_y, min_x, min_y = None, None, None, None
        for primitive in self.primitives.values():
            if primitive.name.startswith("__"):
                continue
            for point in primitive.points:
                if max_x is None or point.x > max_x:
                    max_x = point.x
                if min_x is None or point.x < min_x:
                    min_x = point.x
                if max_y is None or point.y > max_y:
                    max_y = point.y
                if min_y is None or point.y < min_y:
                    min_y = point.y

        ctx = _DrawingContext(
            max_x=max_x if max_x is not None else 1.0,
            max_y=max_y if max_y is not None else 1.0,
            min_x=min_x if min_x is not None else -1.0,
            min_y=min_y if min_y is not None else -1.0,
            drawn=set(),
        )
        for primitive in self.primitives.values():
            if primitive.draw:
                primitive.draw_ax(ax, ctx)
            ctx.drawn.add(primitive.name)
            
        drawn = _drawn_infos or []
        vertex_angle_counter: dict[tuple[float, float], int] = {}
        # Angle annotation
        if wanted_info:
            self._draw_wanted_info(
                ax, ctx.max_abs_coord, list(wanted_info), 
                drawn=drawn, no_draw=_no_draw, vertex_angle_counter=vertex_angle_counter
            )

        # Angle annotation
        if show_important_angles:
            self._auto_detect_and_draw_important_angles(
                ax, ctx.max_abs_coord, color='black', drawn=drawn, no_draw=_no_draw, 
                vertex_angle_counter=vertex_angle_counter
            )
        if mode == 'show':
            plt.show()
        else:
            io_buf = io.BytesIO()
            plt.savefig(io_buf, format='png', bbox_inches='tight')
            return io_buf.getvalue()

    def _resolve_wanted_info(self, info: "WantedInfoType") -> list[dict]:
        """
        Resolve a single WantedInfoType into a list of drawable info dicts.
        
        Each dict has:
            'type': 'point_coord' | 'line_length' | 'angle_3pt' | 'angle_2line'
            + relevant data fields
        """
        results = []

        # String shorthand
        if isinstance(info, str):
            s = info.strip()
            # Remove leading ∠ if present
            if s.startswith('∠'):
                s = s[1:]
                # Must be 3 single-char point names → angle
                if len(s) == 3:
                    names = list(s)
                    pts = [self._find_point(n) for n in names]
                    if all(p is not None for p in pts):
                        results.append({
                            'type': 'angle_3pt',
                            'points': pts,  # [A, B(vertex), C]
                        })
                return results

            # 3 uppercase chars without ∠ → also angle (ABC means ∠ABC)
            if len(s) == 3 and all(c.isupper() or c.isdigit() for c in s):
                pts = [self._find_point(c) for c in s]
                if all(p is not None for p in pts):
                    results.append({
                        'type': 'angle_3pt',
                        'points': pts,
                    })
                    return results

            # 2 uppercase chars → line segment length (e.g., "AB")
            if len(s) == 2 and all(c.isupper() or c.isdigit() for c in s):
                p1 = self._find_point(s[0])
                p2 = self._find_point(s[1])
                if p1 is not None and p2 is not None:
                    results.append({
                        'type': 'line_length',
                        'p1': p1, 'p2': p2,
                    })
                    return results

            # 1 uppercase char → point coordinate
            if len(s) == 1:
                pt = self._find_point(s)
                if pt is not None:
                    results.append({'type': 'point_coord', 'point': pt})
                    return results

            # Try as a line name in primitives
            if s in self.primitives and isinstance(self.primitives[s], Line):
                line = self.primitives[s]
                results.append({
                    'type': 'line_length',
                    'p1': line.points[0], 'p2': line.points[-1],
                })
                return results

            return results

        # Point object → show coordinates
        if isinstance(info, Point):
            results.append({'type': 'point_coord', 'point': info})
            return results

        # Line object → show length
        if isinstance(info, Line):
            results.append({
                'type': 'line_length',
                'p1': info.points[0], 'p2': info.points[-1],
            })
            return results

        # Tuple
        if isinstance(info, (tuple, list)):
            if len(info) == 3 and all(isinstance(p, Point) for p in info):
                # (Point, Point, Point) → angle, middle is vertex
                results.append({'type': 'angle_3pt', 'points': list(info)})
            elif len(info) == 2 and all(isinstance(l, Line) for l in info):
                # (Line, Line) → angle between two lines
                results.append({'type': 'angle_2line', 'lines': list(info)})
            return results

        return results

    def _find_point(self, name: str) -> "Point | None":
        """Find a point by name across all primitives."""
        for prim in self.primitives.values():
            for pt in prim.points:
                if pt.name == name:
                    return pt  # type: ignore
        return None

    def _draw_wanted_info(self, ax: Axes, max_coord: float, wanted_info: list["WantedInfoType"], drawn: list[_DrawnInfo], no_draw=False, vertex_angle_counter: dict[tuple[float, float], int] | None = None):
        """Draw all requested info annotations on the plot."""
        arc_radius = 0.06 * max_coord
        color = 'black'
        if vertex_angle_counter is None:
            vertex_angle_counter = {}

        for info in wanted_info:
            for item in self._resolve_wanted_info(info):
                if item['type'] == 'point_coord':
                    self._draw_point_coord(ax, max_coord, item['point'], color, info=info, drawn=drawn, no_draw=no_draw)
                elif item['type'] == 'line_length':
                    self._draw_line_length(ax, max_coord, item['p1'], item['p2'], color, info=info, drawn=drawn)
                elif item['type'] == 'angle_3pt':
                    self._draw_angle_3pt(ax, arc_radius, item['points'], color, info=info, drawn=drawn, no_draw=no_draw, vertex_angle_counter=vertex_angle_counter)
                elif item['type'] == 'angle_2line':
                    self._draw_angle_2line(ax, arc_radius, item['lines'], color, info=info, drawn=drawn, no_draw=no_draw, vertex_angle_counter=vertex_angle_counter)

    def _draw_point_coord(self, ax: Axes, max_coord: float, point: "Point", color: str, info, drawn: list[_DrawnInfo], no_draw=False):
        """Annotate a point with its coordinates."""
        point_info = _DrawnInfo.CreateCoordinate(point.x, point.y, origin_wanted_input=info, final_value=(point.x, point.y))
        if point_info in drawn:
            return
        drawn.append(point_info)
        if no_draw:
            return
        
        s = 0.02 * max_coord
        label = f"({point.x:.1f}, {point.y:.1f})"
        ax.text(point.x + s, point.y - 3 * s, label,
                fontsize=9, color=color, ha='left', va='top')

    def _draw_line_length(self, ax: Axes, max_coord: float, p1: "Point", p2: "Point", color: str, info, drawn: list[_DrawnInfo], no_draw=False):
        """Annotate a line segment with its length at the midpoint."""
        line_info = _DrawnInfo.CreateLength(
            p1.x, p1.y, p2.x, p2.y, 
            origin_wanted_input=info, 
            final_value=None
        )
        if line_info in drawn:
            return
        drawn.append(line_info)
        if no_draw:
            return
        mx = (p1.x + p2.x) / 2
        my = (p1.y + p2.y) / 2
        length = np.sqrt((p2.x - p1.x) ** 2 + (p2.y - p1.y) ** 2)

        # Offset label perpendicular to the line direction
        dx, dy = p2.x - p1.x, p2.y - p1.y
        norm = np.sqrt(dx * dx + dy * dy)
        if norm > 1e-12:
            # Perpendicular unit vector (rotated 90° CCW)
            nx, ny = -dy / norm, dx / norm
        else:
            nx, ny = 0, 1
        offset = 0.03 * max_coord
        lx = mx + offset * nx
        ly = my + offset * ny
        line_info.final_value = length
        
        label = f"{length:.1f}"
        ax.text(lx, ly, label, fontsize=10, color=color, ha='center', va='center')

    def _draw_angle_3pt(self, ax: Axes, arc_radius: float, points: list["Point"], color: str, info, drawn: list[_DrawnInfo], no_draw=False, vertex_angle_counter: dict[tuple[float, float], int] | None = None):
        """
        Draw angle ∠ABC where points = [A, B, C], B is the vertex.
        """
        A, B, C = points[0], points[1], points[2]
        vx, vy = B.x, B.y
        point_info = _DrawnInfo.CreateAngle(
            A.x, A.y, C.x, C.y, B.x, B.y, info, None
        )
        if point_info in drawn:
            return
        
        drawn.append(point_info)

        # Scale arc_radius by vertex counter to separate overlapping angles
        if vertex_angle_counter is not None:
            vkey = (round(vx, 4), round(vy, 4))
            idx = vertex_angle_counter.get(vkey, 0)
            vertex_angle_counter[vkey] = idx + 1
            arc_radius = arc_radius * (1.0 + 0.2 * idx)
        
        # check if any visible lines in AB & BC, if not, draw dotted lines
        ab_visible = False
        bc_visible = False
        
        def _point_on_segment(px, py, sx, sy, ex, ey, tol=0.05):
            """Check if point (px, py) lies on segment (sx, sy)-(ex, ey).
            
            Uses a relative tolerance: the perpendicular distance must be small
            compared to the segment length, and the projection parameter t must
            be within [0, 1].
            """
            dx, dy = ex - sx, ey - sy
            seg_len_sq = dx * dx + dy * dy
            if seg_len_sq < 1e-24:
                return np.hypot(px - sx, py - sy) < tol
            seg_len = np.sqrt(seg_len_sq)
            # Project point onto the line: t = dot(AP, AB) / |AB|^2
            t = ((px - sx) * dx + (py - sy) * dy) / seg_len_sq
            # Perpendicular distance from point to line
            perp_dist = abs((px - sx) * dy - (py - sy) * dx) / seg_len
            # Use relative tolerance: perp distance < tol fraction of segment length
            dist_ok = perp_dist < max(tol * seg_len, 0.01)
            return dist_ok and -tol <= t <= 1.0 + tol

        def is_sub_line(
            line_a_start: tuple[float, float], 
            line_a_end: tuple[float, float],
            line_b: Line  
        ):
            """Check if segment line_a is contained within any segment of line_b."""
            Ax1, Ay1 = line_a_start
            Ax2, Ay2 = line_a_end
            for i in range(len(line_b.points) - 1):
                Bx1, By1 = line_b.points[i].x, line_b.points[i].y
                Bx2, By2 = line_b.points[i+1].x, line_b.points[i+1].y
                # Both endpoints of A must lie on segment B
                if _point_on_segment(Ax1, Ay1, Bx1, By1, Bx2, By2) and \
                   _point_on_segment(Ax2, Ay2, Bx1, By1, Bx2, By2):
                    return True
            return False
        
        for prim in self.primitives.values():
            if isinstance(prim, Line):
                if is_sub_line((A.x, A.y), (B.x, B.y), prim):
                    ab_visible = True
                if is_sub_line((B.x, B.y), (C.x, C.y), prim):
                    bc_visible = True
                
        if not ab_visible:
            ax.plot([A.x, B.x], [A.y, B.y], color='gray', linewidth=0.9, linestyle='dotted')
        if not bc_visible:
            ax.plot([B.x, C.x], [B.y, C.y], color='gray', linewidth=0.9, linestyle='dotted')
        
        # Direction angles from vertex B to A and C
        angle_a = np.degrees(np.arctan2(A.y - B.y, A.x - B.x)) % 360
        angle_c = np.degrees(np.arctan2(C.y - B.y, C.x - B.x)) % 360

        # Always draw the smaller sweep
        sweep = (angle_c - angle_a) % 360
        if sweep > 180:
            sweep = 360 - sweep
            start_angle = angle_c
        else:
            start_angle = angle_a
        point_info.final_value = sweep
        if sweep < 1e-1 or no_draw:
            return

        is_right = 89.5 <= sweep <= 90.5
        
        if is_right:
            r = arc_radius * 0.5
            a1 = np.radians(start_angle)
            a2 = np.radians(start_angle + sweep)
            p1x, p1y = vx + r * np.cos(a1), vy + r * np.sin(a1)
            p2x, p2y = vx + r * np.cos(a2), vy + r * np.sin(a2)
            cx = p1x + r * np.cos(a2)
            cy = p1y + r * np.sin(a2)
            ax.plot([p1x, cx, p2x], [p1y, cy, p2y], color=color, linewidth=0.8)
        else:
            arc = pltArc(
                (vx, vy), 2 * arc_radius, 2 * arc_radius,
                angle=0, theta1=start_angle, theta2=start_angle + sweep,
                color=color, linewidth=1.0,
            )
            ax.add_patch(arc)
            mid_rad = np.radians(start_angle + sweep / 2)
            label_r = arc_radius * (2.5 if not is_right else 2.2)
            lx = vx + label_r * np.cos(mid_rad)
            ly = vy + label_r * np.sin(mid_rad)
            label = f"{sweep:.1f}°"
            if label.endswith('.0°'):
                label = label.replace('.0°', '°')
            ax.text(lx, ly, label, fontsize=10, color=color, ha='center', va='center')

    def _draw_angle_2line(self, ax: Axes, arc_radius: float, lines: list["Line"], color: str, info, drawn: list[_DrawnInfo], no_draw=False, vertex_angle_counter: dict[tuple[float, float], int] | None = None):
        """
        Draw the acute angle between two lines at their intersection point.
        """
        la, lb = lines[0], lines[1]

        # Find intersection
        pts_a, pts_b = la.points, lb.points
        ax1, ay1 = pts_a[0].x, pts_a[0].y
        ax2, ay2 = pts_a[-1].x, pts_a[-1].y
        bx1, by1 = pts_b[0].x, pts_b[0].y
        bx2, by2 = pts_b[-1].x, pts_b[-1].y
        
        # Check if they share an endpoint (vertex)
        shared_pt = None
        for pa in pts_a:
            for pb in pts_b:
                if pa.name == pb.name:
                    shared_pt = pa
                    break
            if shared_pt:
                break

        if shared_pt is not None:
            vx, vy = shared_pt.x, shared_pt.y
            # Direction away from shared point for each line
            if pts_a[0].name == shared_pt.name:
                da = (pts_a[-1].x - vx, pts_a[-1].y - vy)
            else:
                da = (pts_a[0].x - vx, pts_a[0].y - vy)
            if pts_b[0].name == shared_pt.name:
                db = (pts_b[-1].x - vx, pts_b[-1].y - vy)
            else:
                db = (pts_b[0].x - vx, pts_b[0].y - vy)
        else:
            # Compute geometric intersection
            d1x, d1y = ax2 - ax1, ay2 - ay1
            d2x, d2y = bx2 - bx1, by2 - by1
            denom = d1x * d2y - d1y * d2x
            if abs(denom) < 1e-12:
                return 0.0  # Parallel lines, no angle to draw
            t = ((bx1 - ax1) * d2y - (by1 - ay1) * d2x) / denom
            vx = ax1 + t * d1x
            vy = ay1 + t * d1y
            da = (d1x, d1y)
            db = (d2x, d2y)

        angle_a = np.degrees(np.arctan2(da[1], da[0])) % 360
        angle_b = np.degrees(np.arctan2(db[1], db[0])) % 360

        sweep = (angle_b - angle_a) % 360
        if sweep > 180:
            sweep = 360 - sweep
            start_angle = angle_b
        else:
            start_angle = angle_a
        
        drawn_info = _DrawnInfo.CreateAngle(
            vx + da[0], vy + da[1],
            vx + db[0], vy + db[1],
            vx, vy,
            origin_wanted_input=info,
            final_value=sweep,
        )
        if drawn_info in drawn:
            return
        drawn.append(drawn_info)

        # Scale arc_radius by vertex counter to separate overlapping angles
        if vertex_angle_counter is not None:
            vkey = (round(vx, 4), round(vy, 4))
            idx = vertex_angle_counter.get(vkey, 0)
            vertex_angle_counter[vkey] = idx + 1
            arc_radius = arc_radius * (1.0 + 0.2 * idx)
        
        if no_draw or sweep < 1e-1:
            return

        is_right = 89.5 <= sweep <= 90.5

        if is_right:
            r = arc_radius * 0.6
            a1r = np.radians(start_angle)
            a2r = np.radians(start_angle + sweep)
            p1x, p1y = vx + r * np.cos(a1r), vy + r * np.sin(a1r)
            p2x, p2y = vx + r * np.cos(a2r), vy + r * np.sin(a2r)
            cx = p1x + r * np.cos(a2r)
            cy = p1y + r * np.sin(a2r)
            ax.plot([p1x, cx, p2x], [p1y, cy, p2y], color=color, linewidth=0.8)
        else:
            arc_patch = pltArc(
                (vx, vy), 2 * arc_radius, 2 * arc_radius,
                angle=0, theta1=start_angle, theta2=start_angle + sweep,
                color=color, linewidth=1.0,
            )
            ax.add_patch(arc_patch)

        mid_rad = np.radians(start_angle + sweep / 2)
        label_r = arc_radius * (2.2 if not is_right else 1.9)
        lx = vx + label_r * np.cos(mid_rad)
        ly = vy + label_r * np.sin(mid_rad)
        label = f"{sweep:.1f}°"
        if label.endswith('.0°'):
            label = label.replace('.0°', '°')
        ax.text(lx, ly, label, fontsize=11, color=color, ha='center', va='center')
    
    def _auto_detect_and_draw_important_angles(self, ax: Axes, max_coord: float, color, drawn: list[_DrawnInfo], no_draw=False, vertex_angle_counter: dict[tuple[float, float], int] | None = None):
        """
        Detect and draw only KEY angles formed by intersecting lines.

        Filtering strategy to reduce clutter:
            1. Skip internal lines (names starting with '__').
            2. At each vertex, collect ALL lines that meet there, sort their
               direction angles, and only draw ADJACENT (consecutive) angles.
               This avoids drawing O(n²) overlapping arcs at a busy vertex.
            3. For geometric (non-endpoint) intersections, only draw the
               acute angle (≤90°).
            4. Skip angles that are too small (<3°) or too flat (>177°).
            5. At vertices with many lines (≥4), skip drawing to avoid clutter.
            6. Right angles (85°-95°) are drawn with a small square instead of arc.
        """
        # Gather visible lines
        visible_lines: list[Line] = []
        for prim in self.primitives.values():
            if prim.name.startswith("__"):
                continue
            if isinstance(prim, Line):
                visible_lines.append(prim)  # type: ignore

        if len(visible_lines) < 2:
            return

        arc_radius = 0.05 * max_coord
        MIN_ANGLE = 2.0    # ignore angles smaller than this
        MAX_ANGLE = 178.0   # ignore angles larger than this
        if vertex_angle_counter is None:
            vertex_angle_counter = {}

        def _angle_deg(dx: float, dy: float) -> float:
            """Angle of vector (dx, dy) in degrees, range [0, 360)."""
            return np.degrees(np.arctan2(dy, dx)) % 360

        def _draw_right_angle_mark(ax, vx, vy, angle1_deg, angle2_deg, size):
            """Draw a small square mark for ~90° angles."""
            r = size * 0.55
            a1 = np.radians(angle1_deg)
            a2 = np.radians(angle2_deg)
            p1x, p1y = vx + r * np.cos(a1), vy + r * np.sin(a1)
            p2x, p2y = vx + r * np.cos(a2), vy + r * np.sin(a2)
            cx = p1x + r * np.cos(a2)
            cy = p1y + r * np.sin(a2)
            ax.plot([p1x, cx, p2x], [p1y, cy, p2y], color=color, linewidth=0.8)

        def _draw_angle_arc(ax: Axes, vx, vy, angle_start_deg, sweep_deg, arc_r, label_text):
            """Draw an arc and label. angle_start_deg and sweep_deg define the arc."""
            if no_draw:
                return
            if sweep_deg < MIN_ANGLE or sweep_deg > MAX_ANGLE:
                return

            # Scale arc_r by vertex counter to separate overlapping angles
            vkey = (round(vx, 4), round(vy, 4))
            idx = vertex_angle_counter.get(vkey, 0)
            vertex_angle_counter[vkey] = idx + 1
            arc_r = arc_r * (1.0 + 0.2 * idx)

            is_right = 89.95 <= sweep_deg <= 90.05

            if is_right:
                _draw_right_angle_mark(ax, vx, vy, angle_start_deg,
                                       angle_start_deg + sweep_deg, arc_r)
            else:
                arc = pltArc(
                    (vx, vy), 2 * arc_r, 2 * arc_r,
                    angle=0, theta1=angle_start_deg,
                    theta2=angle_start_deg + sweep_deg,
                    color=color, linewidth=1.0
                )
                ax.add_patch(arc)
                mid_rad = np.radians(angle_start_deg + sweep_deg / 2)
                label_r = arc_r * (2.2 if not is_right else 1.9)
                lx = vx + label_r * np.cos(mid_rad)
                ly = vy + label_r * np.sin(mid_rad)
                if '.' in label_text and label_text.endswith('.0°'):
                    label_text = label_text.replace('.0°', '°')
                ax.text(lx, ly, label_text, fontsize=7, color=color, ha='center', va='center')

        # ── Build point-on-line map from PointOnLineConstraint ──
        # Maps point_name -> list of Lines that the point is constrained onto
        point_on_lines: dict[str, list[Line]] = defaultdict(list)
        for c in self.constraints:
            if isinstance(c, PointOnLineConstraint):
                pt_name = c.point.name
                line = c.line
                if not pt_name.startswith("__") and not line.name.startswith("__"):
                    point_on_lines[pt_name].append(line)  # type: ignore

        # ── Collect all visible point coordinates ──
        point_coords: dict[str, tuple[float, float]] = {}
        for prim in self.primitives.values():
            if prim.name.startswith("__"):
                continue
            for pt in prim.points:
                if not pt.name.startswith("__"):
                    point_coords[pt.name] = (pt.x, pt.y)

        # ── Build vertex_rays: at each vertex, collect outgoing ray directions ──
        vertex_rays: dict[str, list[tuple[float, Line]]] = defaultdict(list)

        for line in visible_lines:
            pts = line.points
            if len(pts) < 2:
                continue
            start, end = pts[0], pts[-1]
            # Ray from start toward end
            vertex_rays[start.name].append((_angle_deg(end.x - start.x, end.y - start.y), line))
            # Ray from end toward start
            vertex_rays[end.name].append((_angle_deg(start.x - end.x, start.y - end.y), line))

        # ── Add rays from PointOnLine constraints ──
        for pt_name, lines in point_on_lines.items():
            if pt_name not in point_coords:
                continue
            px, py = point_coords[pt_name]
            for line in lines:
                pts = line.points
                if len(pts) < 2:
                    continue
                sx, sy = pts[0].x, pts[0].y
                ex, ey = pts[-1].x, pts[-1].y
                # Two rays along the line direction from this point
                dx, dy = ex - sx, ey - sy
                length = np.sqrt(dx * dx + dy * dy)
                if length < 1e-12:
                    continue
                # Ray in the direction start->end
                vertex_rays[pt_name].append((_angle_deg(dx, dy), line))
                # Ray in the direction end->start
                vertex_rays[pt_name].append((_angle_deg(-dx, -dy), line))

        # ── Deduplicate rays at each vertex (same line, same direction) ──
        for vname in vertex_rays:
            seen = set()
            deduped = []
            for angle, line in vertex_rays[vname]:
                # Round angle to avoid floating point duplicates
                key = (line.name, round(angle, 1))
                if key not in seen:
                    seen.add(key)
                    deduped.append((angle, line))
            vertex_rays[vname] = deduped

        drawn_vertex_angles: set[tuple] = set()

        for vertex_name, rays in vertex_rays.items():
            if len(rays) < 2:
                continue
            # Skip vertices with too many lines — too cluttered
            if len(rays) >= 7:
                continue

            # Get vertex coordinates
            if vertex_name not in point_coords:
                continue
            vx, vy = point_coords[vertex_name]

            # Sort rays by angle
            rays_sorted = sorted(rays, key=lambda r: r[0])
            n = len(rays_sorted)

            for j in range(n):
                a1, l1 = rays_sorted[j]
                a2, l2 = rays_sorted[(j + 1) % n]

                # Same line — skip (e.g., two rays of the same line at a PointOnLine vertex)
                if l1.name == l2.name:
                    continue

                # Compute the sweep from a1 to a2 going counter-clockwise
                sweep = (a2 - a1) % 360
                if sweep > 180:
                    continue

                if sweep < MIN_ANGLE or sweep > MAX_ANGLE:
                    continue

                # Deduplicate: use sorted line pair + vertex
                pair_key = (vertex_name, tuple(sorted([l1.name, l2.name])))
                if pair_key in drawn_vertex_angles:
                    continue
                drawn_vertex_angles.add(pair_key)
                
                drawn_info = _DrawnInfo.CreateAngle(
                    vx + np.cos(np.radians(a1)), vy + np.sin(np.radians(a1)),
                    vx + np.cos(np.radians(a2)), vy + np.sin(np.radians(a2)),
                    vx, vy,
                    origin_wanted_input=None,
                    final_value=sweep,
                )
                if drawn_info in drawn:
                    continue
                            
                label = f"{sweep:.1f}°"
                _draw_angle_arc(ax, vx, vy, a1, sweep, arc_radius, label)

        def _seg_intersect(p1x, p1y, p2x, p2y, p3x, p3y, p4x, p4y):
            """Find intersection of segment (p1-p2) and (p3-p4), or None."""
            d1x, d1y = p2x - p1x, p2y - p1y
            d2x, d2y = p4x - p3x, p4y - p3y
            denom = d1x * d2y - d1y * d2x
            if abs(denom) < 1e-12:
                return None
            t = ((p3x - p1x) * d2y - (p3y - p1y) * d2x) / denom
            u = ((p3x - p1x) * d1y - (p3y - p1y) * d1x) / denom
            tol = 0.02
            if -tol <= t <= 1 + tol and -tol <= u <= 1 + tol:
                return (p1x + t * d1x, p1y + t * d1y)
            return None

        def _shares_endpoint(la, lb):
            """Check if two lines share any endpoint."""
            for pa in la.points:
                for pb in lb.points:
                    if pa.name == pb.name:
                        return True
            return False

        for i, la in enumerate(visible_lines):
            for lb in visible_lines[i + 1:]:
                if _shares_endpoint(la, lb):
                    continue  # already handled above

                pts_a, pts_b = la.points, lb.points
                result = _seg_intersect(
                    pts_a[0].x, pts_a[0].y, pts_a[-1].x, pts_a[-1].y,
                    pts_b[0].x, pts_b[0].y, pts_b[-1].x, pts_b[-1].y,
                )
                if result is None:
                    continue

                ix, iy = result

                # Skip if near an existing vertex (already handled by vertex logic)
                is_near_vertex = False
                for pt_name, (ptx, pty) in point_coords.items():
                    if np.hypot(ptx - ix, pty - iy) < 0.5:
                        is_near_vertex = True
                        break
                if is_near_vertex:
                    continue

                da = (pts_a[-1].x - pts_a[0].x, pts_a[-1].y - pts_a[0].y)
                db = (pts_b[-1].x - pts_b[0].x, pts_b[-1].y - pts_b[0].y)
                angle_a = _angle_deg(*da)
                angle_b = _angle_deg(*db)

                sweep = (angle_b - angle_a) % 360
                if sweep > 180:
                    sweep = 360 - sweep
                    start_angle = angle_b
                else:
                    start_angle = angle_a

                if sweep > 95:
                    continue
            
                drawn_info = _DrawnInfo.CreateAngle(
                    ix + da[0], iy + da[1],
                    ix + db[0], iy + db[1],
                    ix, iy,
                    origin_wanted_input=None,
                    final_value=sweep,
                )
                if drawn_info in drawn:
                    continue
                
                label = f"{sweep:.1f}°"
                _draw_angle_arc(ax, ix, iy, start_angle, sweep, arc_radius, label)
    # endregion
    
__all__ += [
    'Problem2D',
    'WantedInfoType',
]
# endregion

if __name__ == "__main__":
    import tqdm
    
    def get_test1_problem(inverse_pq=False):
        prob = Problem2D()
        # 1. Circle center O and Radius
        O = prob.add_point(0, 0, "O")
        radius = 10
        circle = prob.add_circle(O, radius=radius-2, name="Circle")
        
        # 2. Points on Circle: P, Q, R
        P = prob.add_point(0, -radius-3, "P")
        Q = prob.add_point(radius-5, 0, "Q")
        R = prob.add_point(-6, 18, "R")
        V = prob.add_point(40, -radius+3.1, "V")
        S = prob.add_point(-30, radius+2.5, "S")
        U = prob.add_point(radius+4, radius+7, "U")
        T = prob.add_point(radius+2.1, -radius-1, "T")
        
        circle.constrain_point(P)
        circle.constrain_point(Q)
        circle.constrain_point(R)
        
        SV = prob.add_line(S, V)
        SV.constrain_point(P, within_line=True)
        SV.constrain_point(T, within_line=True)
        SV.constrain_horizontal()
        RV = prob.add_line(R, V)
        RV.constrain_point(Q)
        
        # 3. Tangents
        OP = prob.add_line(O, P)
        SV.constrain_perpendicular_to(OP)
        
        SU = prob.add_line(S, U)
        SU.constrain_point(R, within_line=True)
        OR = prob.add_line(O, R)
        SU.constrain_perpendicular_to(OR)
        
        UT = prob.add_line(U, T)
        UT.constrain_point(Q, within_line=True)
        OQ = prob.add_line(O, Q)
        UT.constrain_perpendicular_to(OQ)
        
        SU.constrain_angle_with(SV, 34)
        if not inverse_pq:
            PQ = prob.add_line(P, Q)
        else:
            PQ = prob.add_line(Q, P)    # 假设写错顺序
        PQ.constrain_angle_with(SV, 46)
        return prob
    
    def get_test2_problem():
        prob = Problem2D()
        O = prob.add_point(name="O")
        circle = prob.add_circle(O)
        
        AC = circle.create_diameter('AC')
        D = circle.create_point('D')
        FE, D = circle.create_tangent(D, tangent_name='FE')
        
        B = circle.create_point('B')
        EC = prob.add_line(FE.end, AC.end)
        AB = prob.add_line(AC.start, B)
        EC.constrain_parallel_to(AB)
        DC = prob.add_line(D, AC.end)
        DC.constrain_angle_with(FE, 49)
        CE = prob.add_line(AC.end, EC.start)
        CE.constrain_angle_with(FE, 31)
        return prob
    
    def test1(inverse_pq=False):
        prob = get_test1_problem(inverse_pq=inverse_pq)    
        prob.solve(update_when_failed=True)
        prob.plot(
            mode='show',
            wanted_info=[
                "∠PSR",
                "∠PRQ",
                "∠RPQ",
                "∠SQV"
            ],
        )
        print(f'Final error: {prob.error()}')
        
    def test2():
        prob = get_test2_problem()
        print(f'dof: {prob.dof}')
        prob.solve(update_when_failed=True)
        prob.plot(
            mode='show',
            wanted_info=["∠ACB", '∠CDF', '∠CED'],
        )
        print(f'Final error: {prob.error()}')
        
    def test_geogebra():
        script = '''
        # 定义圆
        c = Circle((0, 0), 2)

        # 在圆上定义点P, Q, R
        P = Point(c)
        Q = Point(c)
        R = Point(c)

        # 定义切线ST, TU, SU
        ST = Tangent(P, c)
        TU = Tangent(Q, c)
        SU = Tangent(R, c)

        # 定义点T和U
        T = Intersect(ST, TU)
        U = Intersect(TU, SU)

        # 定义直线RQ和ST的交点V
        V = Intersect(Line(R, Q), ST)

        # 定义角度约束
        SetAngle(PSR, 34°)
        SetAngle(QPT, 46°)
        # SetAngle(TPQ, 46°)
        '''
        prob = Problem2D()
        prob.load_script(script)
        prob.solve(update_when_failed=True)
        prob.plot(wanted_info=["∠PSR", "∠QPT", '∠PVQ'], mode='show')
        
    def massive_test(n=20):
        t1_normal_succ = 0
        t1_inverse_succ = 0
        t2_succ = 0
        
        for _ in tqdm.tqdm(range(n)):
            prob1 = get_test1_problem(inverse_pq=False)
            res1 = prob1.solve(update_when_failed=True)
            if res1 and prob1.error() < 1e-11:
                t1_normal_succ += 1
            
            prob1_inv = get_test1_problem(inverse_pq=True)
            res1_inv = prob1_inv.solve(update_when_failed=True)
            if res1_inv and prob1_inv.error() < 1e-11:
                t1_inverse_succ += 1
            
            prob2 = get_test2_problem()
            res2 = prob2.solve(update_when_failed=True)
            if res2 and prob2.error() < 1e-11:
                t2_succ += 1
                
        print(f"Test1 normal success: {t1_normal_succ}/{n}")
        print(f"Test1 inverse success: {t1_inverse_succ}/{n}")
        print(f"Test2 success: {t2_succ}/{n}") 
        
    # test1(inverse_pq=True)
    # test2()
    test_geogebra()
    # massive_test(20)