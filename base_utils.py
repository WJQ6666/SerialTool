# -*- coding: utf-8 -*-
"""
Time    : 2025/5/10 11:30
Author  : jiaqi.wang
"""
import re
from datetime import datetime


def stamp(fmt: str = None, millisecond: bool = True):
    """根据fmt返回当前时间"""
    if fmt is None:
        fmt = "%Y%m%d_%H%M%S_%f" if millisecond else "%Y%m%d_%H%M%S"
    return datetime.now().strftime(fmt)


def byte2str(strings: bytes, encoding: str = "utf-8", errors: str = "ignore"):
    """将二进制字符串转换成str并去掉字符串中的颜色标记和\r"""
    return re.compile(br"\x1b\[[0-9;]*m").sub(b"", strings).decode(encoding, errors).replace("\r", "")
