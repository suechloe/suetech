"""
Feishu WebSocket 连接管理器
处理自动重连、心跳保活、错误恢复
"""
import logging
import time
import asyncio
import threading
import lark_oapi as lark
from typing import Callable, Optional

logger = logging.getLogger("feishu_connection")


class FeishuConnectionManager:
    """
    管理 Feishu WebSocket 连接的生命周期。
    - 自动重连（指数退避）
    - 心跳保活
    - 优雅关闭
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        on_message_handler: Callable,
        bot_name: str = "Bot",
        initial_backoff: int = 5,
        max_backoff: int = 300,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.on_message_handler = on_message_handler
        self.bot_name = bot_name
        self.initial_backoff = initial_backoff
        self.max_backoff = max_backoff

        self.client: Optional[lark.ws.Client] = None
        self.is_running = False
        self.backoff_delay = initial_backoff
        self.connection_attempts = 0
        self.last_heartbeat = time.time()

    def _create_handler(self):
        """创建 Lark 事件处理器"""
        handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(
            self.on_message_handler
        ).build()
        return handler

    def _connect(self):
        """建立 WebSocket 连接"""
        try:
            self.connection_attempts += 1
            logger.info(
                f"[{self.bot_name}] 尝试连接 (尝试 #{self.connection_attempts}, 延迟 {self.backoff_delay}s)..."
            )

            handler = self._create_handler()
            self.client = lark.ws.Client(
                self.app_id,
                self.app_secret,
                event_handler=handler,
                log_level=lark.LogLevel.INFO
            )

            self.client.start()

            # 连接成功，重置延迟和计数
            self.backoff_delay = self.initial_backoff
            self.connection_attempts = 0
            self.last_heartbeat = time.time()
            logger.info(f"[{self.bot_name}] ✅ 连接成功")

            return True
        except Exception as e:
            logger.error(f"[{self.bot_name}] ❌ 连接失败: {e}")
            return False

    def _monitor_heartbeat(self):
        """监控连接健康状况（后台线程）"""
        while self.is_running:
            time.sleep(300)  # 每 5 分钟检查一次

            if not self.is_running:
                break

            # 检查连接是否长时间没有活动（仅 debug 级别，正常空闲不报警）
            if self.client:
                try:
                    time_since_heartbeat = time.time() - self.last_heartbeat
                    if time_since_heartbeat > 3600:  # 1 小时没收到任何消息才提示
                        logger.debug(
                            f"[{self.bot_name}] 连接空闲 {time_since_heartbeat/3600:.1f}h，WebSocket 仍运行中"
                        )
                except Exception as e:
                    logger.error(f"[{self.bot_name}] 心跳监控错误: {e}")

    def _reconnect_loop(self):
        """后台重连循环"""
        logger.info(f"[{self.bot_name}] 🔄 启动重连循环...")

        # 启动心跳监控线程
        heartbeat_thread = threading.Thread(
            target=self._monitor_heartbeat,
            daemon=True,
            name=f"{self.bot_name}-heartbeat"
        )
        heartbeat_thread.start()
        logger.info(f"[{self.bot_name}] ✅ 心跳监控线程已启动")

        while self.is_running:
            try:
                if not self._connect():
                    # 连接失败，等待后重试
                    logger.info(f"[{self.bot_name}] 等待 {self.backoff_delay}s 后重新尝试...")
                    time.sleep(self.backoff_delay)

                    # 指数退避：每次失败增加延迟，但不超过 max_backoff
                    self.backoff_delay = min(
                        int(self.backoff_delay * 1.5),
                        self.max_backoff
                    )
                else:
                    # 连接成功，client.start() 会阻塞直到连接断开
                    # 当 client.start() 返回时，说明连接被中断
                    if self.is_running:
                        logger.warning(f"[{self.bot_name}] 🔄 连接被中断，准备重连...")
                        time.sleep(self.initial_backoff)
                        self.backoff_delay = self.initial_backoff  # 重置延迟

            except Exception as e:
                logger.error(f"[{self.bot_name}] 重连循环异常: {e}")
                time.sleep(self.initial_backoff)

    def start(self):
        """启动连接管理器（阻塞式）"""
        self.is_running = True
        logger.info(f"[{self.bot_name}] 启动连接管理器...")

        try:
            self._reconnect_loop()
        except KeyboardInterrupt:
            logger.info(f"[{self.bot_name}] 收到中断信号")
        finally:
            self.stop()

    def start_in_background(self):
        """在后台线程启动连接管理器"""
        self.is_running = True
        thread = threading.Thread(
            target=self._reconnect_loop,
            daemon=False,
            name=f"{self.bot_name}-connection-manager"
        )
        thread.start()
        logger.info(f"[{self.bot_name}] 在后台启动连接管理器")
        return thread

    def stop(self):
        """优雅关闭"""
        logger.info(f"[{self.bot_name}] 关闭连接...")
        self.is_running = False
        if self.client:
            try:
                # Lark Client 没有 close() 方法，只需设置 is_running = False
                # 连接会在下一次 client.start() 返回时自动关闭
                pass
            except Exception as e:
                logger.error(f"[{self.bot_name}] 关闭错误: {e}")

    def update_heartbeat(self):
        """更新最后心跳时间（在消息处理时调用）"""
        self.last_heartbeat = time.time()
