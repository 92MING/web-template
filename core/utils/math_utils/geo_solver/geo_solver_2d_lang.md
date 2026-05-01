# 2D Geo Script: 2D空间约束表达语言

## 基本语法
- 注释：`# 注释内容`  
- 赋值：`变量名 = 表达式`  
- 几何对象通过函数创建，约束通过函数调用或等式表达。

## 几何对象
### 点 (Point)
通过坐标创建
```
A = point(0, 0)
B = point(3, 4)
```
通过几何构造
```
M = midpoint(A, B)           # 中点
I = intersection(l1, l2)     # 两线交点
P = point_on_line(l, t=0.5)  # 线上参数点（t 范围 0~1）
Q = point_on_circle(c, angle=45)  # 圆上点，角度单位：度
```

### 线 (Line)
通过两点
```
l = line(A, B)
```
通过点和方向向量（可选）
```
l2 = line(A, direction=(1, 2))
```

### 圆 (Circle)
圆心 + 半径
```
c = circle(O, 5)
```
圆心 + 圆上一点
```
c2 = circle(O, P)
```

### 线段 (Segment)
```
s = segment(A, B)   # 用于长度约束等
```

## 几何关系约束
使用函数形式声明几何约束关系，不返回值，仅表达约束。
```
parallel(l1, l2)                # l1 ∥ l2
perpendicular(l1, l2)           # l1 ⊥ l2
collinear(A, B, C)              # 三点共线
concyclic(A, B, C, D)           # 四点共圆
equal_length(seg1, seg2)        # 两条线段长度相等
equal_angle(angle1, angle2)     # 两个角相等，角用三点表示，如 ∠ABC = angle(A,B,C)
on_line(P, l)                   # 点在直线上
on_circle(P, c)                 # 点在圆上
```

## 数值约束
通过等式设定距离、角度、半径的具体数值。
```
distance(A, B) = 5.0                # AB 长度为 5
angle(A, B, C) = 60                 # ∠ABC = 60°
radius(c) = 3.0                     # 圆半径固定为 3
```

## 构造与交点
几何构造会自动创建新对象（如交点），可直接赋值给变量。
```
# 两线交点
P = intersection(line1, line2)
# 两圆交点（可能返回两个点，用元组解包）
I1, I2 = intersection(circle1, circle2)
# 线与圆的交点
I1, I2 = intersection(line, circle)
```

## 表达式与数值计算
支持 + - * / 及括号。常用数学函数：sqrt, sin, cos, tan, asin, acos, atan（角度制）。
变量可以参与表达式，例如：
```
d = distance(A, B)
x = d / 2
C = point(x, 0)
```