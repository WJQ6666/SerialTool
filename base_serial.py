

from serial import Serial, SerialException
from serial.tools import list_ports_windows
from typing import Union, Optional, Callable, IO, Dict, Tuple, List, Any
from time import sleep
import re
import ctypes
from base_thread import BaseThread, ThreadCheckEvent, ThreadEvent
from base_utils import byte2str, stamp
from base_decorators import ctrl_c_decorator


class BaseSerial(Serial):
    # 类常量
    BAUDRATES = Serial.BAUDRATES

    def __init__(
            self,
            port: str,
            baud_rate: int = 115200,
            sink: Optional[Union[Callable, IO]] = None,
            buffer_size: int = 1024 * 1000 * 10,  # 约10MB
            encoding: str = "ascii",
            output_reader: bool = True,
            log_fmt: Optional[str] = None,
            pre_prompt: str = "console",
            **kwargs
    ):
        super().__init__(port=str(port).upper(), baudrate=baud_rate, **kwargs)

        # 配置属性
        self.encoding = encoding
        self.log_fmt = log_fmt
        self.pre_prompt = pre_prompt
        self.buffer_size = buffer_size

        # 内部状态
        self._sink = sink
        self._buffer = ""
        self._prompt = ""
        self._event_map = None

        # 线程事件
        self.write_event = ThreadEvent(bytes)  # 写
        self.read_event = ThreadEvent()  # 读
        self.pause_event = ThreadEvent()  # 暂停读
        self.exit_event = ThreadEvent()  # 退出读
        self.check_event = ThreadCheckEvent()  # 模式匹配
        self.prompt_event = ThreadEvent(str)

        # self._reader_thread = BaseThread(
        #         target=self._run_reader_loop,
        #         args=(output_reader,),
        #         daemon=True
        #     )
        self._reader_thread = None

    # region 核心功能
    def write(
            self,
            cmd: Union[str, bytes, bytearray],
            flag: bool = False,
            called: bool = False,
            timeout: int = 1,
            prompt: bool = True
    ) -> bytes:
        """写入命令到串口"""
        if isinstance(cmd, str):
            cmd = cmd.encode(self.encoding)
        cmd = cmd if flag else cmd + b"\n"

        self._wait_until_ready()

        if prompt:
            self.prompt_event.set()

        if called:
            self.write_event.set()
            super().write(cmd)
            if prompt:
                self.prompt_event.wait_for("clear", timeout=timeout)
            else:
                self.sleep(timeout)
            return self.write_event.data or b""

        super().write(cmd)
        if prompt:
            self.prompt_event.wait_for("clear", timeout=timeout)
        return b""

    def read(self, size: Optional[int] = None, timeout: float = 10.0) -> bytes:
        """从串口读取数据"""
        try:
            self.read_event.set()
            self._wait_until_ready()
            data = self._raw_read(size or self.in_waiting)
            self._process_received_data(data)
            return data
        finally:
            self.read_event.clear()

    def _raw_read(self, size: int) -> bytes:
        """底层读取实现"""
        return re.sub(rb"\x00", b"", super().read(size))

    def _process_received_data(self, data: bytes) -> None:
        """处理接收到的数据"""
        text = byte2str(data, self.encoding)
        # if not text:
        #     return

        # 处理命令回调
        if self.write_event.is_set():
            self.write_event.data = data

        # 写入输出流
        if self._sink and text:
            self._write_to_sink(text)

        # 更新缓冲区
        self._update_buffer(text)

        # 检查提示符
        if self.prompt_event.is_set():
            self._check_for_prompt(text)

        # 检查模式匹配
        if self.check_event.is_set():
            self._check_for_patterns(self.buffer)

    def reader_output(self, output: bool = False) -> None:
        """是否在终端打印reader的输出"""
        if not self._reader_thread or not self._reader_thread.is_alive():
            self._reader_thread = BaseThread(
                target=self._run_reader_loop,
                args=(output,),
                daemon=True
            )
            self._reader_thread.start()

    def stop_reader(self) -> None:
        """停止读取线程"""
        if self._reader_thread and self._reader_thread.is_alive():
            thread_id = self._reader_thread.ident
            if thread_id:
                ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_long(thread_id),
                    ctypes.py_object(SystemExit)
                )
        self._reader_thread = None

    def _run_reader_loop(self, output: bool) -> None:
        """读取线程的主循环"""
        try:
            for data in self._read_generator():
                if output and data:
                    print(data, end="", flush=True)
        except (SystemExit, KeyboardInterrupt):
            pass

    def _read_generator(self) -> str:
        """生成器模式读取数据"""
        while not self.exit_event.is_set():
            if not self.pause_event.is_set():
                data = self.read()
                if data:
                    yield data.decode(self.encoding, errors="ignore")
            self.sleep(0.2)

    def key_event(self, key: Union[int, str],
                  count: int = 1, interval: Optional[float] = None) -> None:
        """发送按键事件"""
        for _ in range(count):
            self.write(f"input keyevent {key}")
            self.sleep(interval)

    def long_press(self, event: int, code: int, interval: float = 1.0) -> None:
        """
        模拟长按事件
        """
        try:
            # Note：event事件根据实际情况替换
            self.write(
                f"sendevent /dev/input/event{event} 1 {code} 1;"
                f"sendevent /dev/input/event{event} 0 0 0",
                timeout=1
            )
            self.sleep(interval)
        finally:
            self.write(
                f"sendevent /dev/input/event{event} 1 {code} 0;"
                f"sendevent /dev/input/event{event} 0 0 0",
                timeout=1
            )

    def get_rc_event(self) -> str:
        """获取蓝牙遥控器的Event"""
        if self._event_map is None:
            self._event_map = self._parse_event_devices(self.get_event())

        for name in ("RC", "XXX"):
            if name in self._event_map:
                return self._event_map[name]
        return "0"

    @classmethod
    def _parse_event_devices(cls, event_str: str) -> Dict[str, str]:
        """解析输入设备信息"""
        events = re.findall(r"/dev/input/event(\d+)", event_str)
        names = re.findall(r'name:\s+"(.*)"', event_str)
        return dict(zip(names, events)) if len(names) == len(events) else {}

    def reconnect(self, retries: int = 1, delay: float = 1.0) -> None:
        """重新连接串口"""
        for _ in range(retries):
            try:
                super().open()
                self.pause_event.clear()
                return
            except SerialException:
                self.sleep(delay)
        self.close()
        raise SerialException("Reconnect failed")

    def close(self, timeout: int = 10) -> None:
        """关闭串口连接"""
        try:
            self.exit_event.set()
            self.read_event.wait_for("clear", timeout=timeout, error_type="strict")
        finally:
            super().close()

    def pause(self, timeout: int = 10) -> None:
        """暂停读取"""
        self.pause_event.set()
        self.read_event.wait_for("clear", timeout=timeout, error_type="strict")
        super().close()

    @property
    def buffer(self) -> str:
        """串口数据缓冲区"""
        return self._buffer

    @buffer.setter
    def buffer(self, data: str) -> None:
        """自动控制缓冲区大小"""
        if len(self._buffer) + len(data) >= self.buffer_size:
            self._buffer = self._buffer[len(data):] + data
        else:
            self._buffer += data

    @property
    def prompt(self) -> str:
        """当前提示符"""
        return self._prompt

    @prompt.setter
    def prompt(self, value: str) -> None:
        """带验证的提示符设置"""
        if value and not isinstance(value, str):
            raise TypeError("Prompt must be string")
        self._prompt = value

    @property
    def sink(self) -> Optional[Union[Callable, IO]]:
        """输出目标"""
        return self._sink

    @sink.setter
    def sink(self, value: Optional[Union[Callable, IO]]) -> None:
        """设置输出目标（必须实现write方法）"""
        if value is not None and not hasattr(value, 'write'):
            raise AttributeError("Sink must implement write()")
        self._sink = value

    @staticmethod
    def sleep(seconds: Optional[float] = None) -> None:
        """线程休眠"""
        if seconds is not None:
            sleep(seconds)

    def _wait_until_ready(self) -> None:
        """等待设备就绪"""
        while self.pause_event.is_set() or self.exit_event.is_set():
            self.sleep(0.1)

    def _update_buffer(self, text: str) -> None:
        """更新缓冲区内容"""
        self.buffer = text

    def _check_for_prompt(self, text: str) -> None:
        """检查提示符"""
        match = re.search(
            rf"(\d+\|{self.pre_prompt}|{self.pre_prompt}):.* [#\$] ",
            text
        )
        if match:
            self.prompt = match.group(0)
            self.prompt_event.clear()

    def _check_for_patterns(self, text: str) -> None:
        """检查模式匹配"""
        if self.check_event.checks and re.search(
                "|".join(self.check_event.checks), text
        ):
            self.check_event.clear()

    def _write_to_sink(self, text: str) -> None:
        """写入输出流"""
        lines = text.split("\n")
        if self.log_fmt:
            timestamp = f"[{stamp(self.log_fmt)}] "
            output = "\n".join(
                timestamp + line if i > 0 else line
                for i, line in enumerate(lines)
            )
        else:
            output = text
        self._sink.write(output)
        self._sink.flush()

    def clear_buffer(self) -> None:
        """清空缓冲区"""
        self._buffer = ""

    @classmethod
    def list_ports(cls) -> List[str]:
        """获取可用串口列表"""
        return [
            port.device
            for port in list_ports_windows.comports()
            if "serial" in port.description.lower()
        ]

    @ctrl_c_decorator
    def logcat(self, interval: float = 60.0) -> None:
        """持续读取日志"""
        self.write("logcat")
        self.sleep(interval)

    @ctrl_c_decorator
    def logcat_filter(
            self,
            grep_str: str = "",
            interval: float = 60.0,
            *patterns: str
    ) -> bool:
        """带过滤的日志读取"""
        self.check_event.checks = patterns
        self.check_event.set()

        cmd = f'logcat | grep -i "{grep_str}"' if grep_str else "logcat"
        self.write(cmd)

        try:
            self.check_event.wait_for("clear", timeout=interval, error_type="strict")
            return True
        except TimeoutError:
            return False
        finally:
            self.clear_buffer()

    def check_log(self, timeout: int = 10, *args):
        """
        检查日志中是否包含某些关键字
        :param timeout: 超市时间
        :param args: List[str]，待检查的关键字列表
        :return:
        """
        self.check_event.checks = args
        self.check_event.set()
        return self._wait_check_clear(timeout)

    def _wait_check_clear(self, timeout: float = 60.0) -> bool:
        try:
            self.check_event.wait_for("clear", timeout=timeout, error_type="strict")
            return True
        except TimeoutError:
            self.check_event.clear()
            return False
        finally:
            self._buffer = ''

    def get_event(self, timeout: int = 2) -> str:
        """获取输入设备信息"""
        return self.write(
            "getevent",
            called=True,
            timeout=timeout,
            prompt=False
        ).decode(self.encoding)

    def __del__(self):
        """析构时自动清理"""
        self.stop_reader()
        try:
            self.close()
        except Exception:
            pass


__all__ = ["BaseSerial"]