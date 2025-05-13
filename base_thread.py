# -*- coding: utf-8 -*-
"""
Time    : 2025/5/10 11:26
Author  : jiaqi.wang
"""
import sys
from threading import Event, Thread, ThreadError
from typing import Any, Callable, Dict, List, Optional, Tuple, Type, Union

from base_decorators import func_timeout, wait_for


class ThreadEvent(Event):
    """增强型线程事件，支持数据类型检查和状态等待"""

    def __init__(self, data_type: Optional[Type] = None):
        super().__init__()
        self._data_type = data_type
        self._is_data_ready = False
        self._data = None

    @property
    def data(self) -> Any:
        """获取事件数据"""
        return self._data

    @data.setter
    def data(self, data):
        """设置事件数据（类型安全）"""
        if not self._is_data_ready:
            if not isinstance(data, self._data_type):
                raise TypeError(f"except {self._data_type}, got {type(data).__name__}")
            if self._data is None:
                self._data = data
            else:
                self._data += data

    def set(self, errors: str = False) -> None:
        """设置事件标志"""
        if self.is_set():
            if errors == 'strict':
                raise ThreadError(f"{self.__class__} is set, please set after clear.")
            return
        self._data = None
        self._is_data_ready = False
        super().set()

    def clear(self) -> None:
        """清除事件标志并标记数据就绪"""
        super().clear()
        self._is_data_ready = True

    def wait_for(
            self,
            target_state: str = "set", timeout: float = 1.0,
            interval: float = 0.2, error_type: str = None
    ):
        """
        等待事件达到指定状态
        :param target_state: 'set'/'clear'/'ready'
        :param timeout: 总超时时间
        :param interval: 检查间隔
        :param error_type: 超时是否抛出异常
        :return:
        """
        if not isinstance(timeout, (int, float)):
            timeout = float(timeout)

        if target_state == "set":
            wait_for(lambda: self.is_set(), timeout, interval, error_type)

        elif target_state == "clear":
            wait_for(lambda: not self.is_set(), timeout, interval, error_type)

        else:
            wait_for(lambda: self._is_data_ready, timeout, interval, error_type)


class ThreadCheckEvent(ThreadEvent):
    """带条件检查的线程事件"""

    def __init__(self, checks: Optional[List[str]] = None):
        super().__init__(data_type=list)
        self.checks = checks or []

    def check_conditions(self, data: str) -> bool:
        """检查数据是否满足所有条件"""
        return all(check in data for check in self.checks) if self.checks else False


class BaseThread(Thread):
    """增强型线程基类"""

    def __init__(
            self,
            target: Optional[Callable] = None,
            args: Tuple = (),
            kwargs: Optional[Dict[str, Any]] = None,
            *,
            daemon: Optional[bool] = None,
            name: Optional[str] = None
    ):
        """
        初始化线程
        :param target: 目标函数
        :param args: 位置参数（必须为元组）
        :param kwargs: 关键字参数
        :param daemon: 是否守护线程
        :param name: 线程名称
        """
        super().__init__(
            target=target,
            args=args,
            kwargs=kwargs if kwargs is not None else {},
            daemon=daemon,
            name=name
        )
        self._stop_event = Event()
        self._return_value = None
        self._exception = None
        self._exc_info = None

    def run(self) -> None:
        """重写run方法以捕获异常和返回值"""
        try:
            if self._target is not None:
                self._return_value = self._target(*self._args, **self._kwargs)
        except Exception:
            self._exception = sys.exc_info()[1]
            self._exc_info = sys.exc_info()
        finally:
            self._stop_event.set()

    def stop(self) -> None:
        """请求停止线程（非强制）"""
        self._stop_event.set()

    def join(self, timeout: Optional[float] = None) -> Any:
        """
        等待线程结束并返回结果
        :param timeout: 超时时间（秒）
        :return: 目标函数的返回值
        :raises: 如果线程抛出异常，会在此重新抛出
        """
        super().join(timeout)
        if self._exc_info:
            raise self._exc_info[1].with_traceback(self._exc_info[2])
        return self._return_value

    @property
    def should_stop(self) -> bool:
        """检查是否收到停止请求"""
        return self._stop_event.is_set()

    @property
    def result(self) -> Any:
        """获取线程返回值（必须在join后调用）"""
        if self.is_alive():
            raise RuntimeError("Thread is still running")
        return self._return_value
