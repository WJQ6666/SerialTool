# -*- coding: utf-8 -*-
"""
Time    : 2025/5/11 16:07
Author  : jiaqi.wang
"""
from base_serial import BaseSerial
serial_ = BaseSerial("COM83")
# 读取到的数据输出到终端
serial_.reader_output(True)

# 输入指定命令，并获取返回
print(serial_.write("ls", called=True, timeout=2).decode("utf-8"))

# 检查日志中是否有指定关键字
print(serial_.check_log(5, *["config1"]))

# 输入键值
serial_.key_event("KEYCODE_DPAD_UP")
serial_.key_event(19)