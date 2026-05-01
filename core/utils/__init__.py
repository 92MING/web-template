from typing import TYPE_CHECKING

if not TYPE_CHECKING:
    from .log_utils import Logger # 初始化log_utils.py, 注册自定义Logger类