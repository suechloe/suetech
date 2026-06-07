"""
Sue Tech Bot Manager
====================
同时管理和监控 Nora、Sage、Elle 三个飞书 WebSocket 连接。
在任何一个 bot 失败时自动重启。
"""
import logging
import subprocess
import sys
import time
import signal
from pathlib import Path
from datetime import datetime

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(name)s] %(levelname)s: %(message)s'
)
logger = logging.getLogger("bot_manager")

# Bot 配置
BOTS = {
    "nora": {"script": "bot_nora.py", "label": "📋 Nora [CEO]"},
    "sage": {"script": "bot_sage.py", "label": "💻 Sage [代码]"},
    "elle": {"script": "bot_elle.py", "label": "⚖️ Elle [法律]"},
}

PYTHON_BIN = sys.executable
PROJECT_ROOT = Path(__file__).parent


class BotProcess:
    """管理单个 Bot 进程的生命周期"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.process = None
        self.start_time = None
        self.restart_count = 0
        self.last_error = None

    def start(self):
        """启动 Bot 进程"""
        script_path = PROJECT_ROOT / self.config["script"]

        if not script_path.exists():
            logger.error(f"[{self.name}] ❌ 脚本不存在: {script_path}")
            return False

        try:
            logger.info(f"[{self.name}] 🚀 启动 {self.config['label']}")

            self.process = subprocess.Popen(
                [PYTHON_BIN, str(script_path)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # 行缓冲
            )

            self.start_time = time.time()
            self.restart_count += 1
            logger.info(f"[{self.name}] ✅ 进程已启动 (PID: {self.process.pid}, 重启 #{self.restart_count})")

            return True

        except Exception as e:
            logger.error(f"[{self.name}] ❌ 启动失败: {e}")
            self.last_error = str(e)
            return False

    def is_alive(self) -> bool:
        """检查进程是否还活着"""
        if self.process is None:
            return False

        returncode = self.process.poll()
        return returncode is None

    def get_uptime(self) -> int:
        """获取进程运行时间（秒）"""
        if self.start_time is None:
            return 0
        return int(time.time() - self.start_time)

    def stop(self):
        """停止进程"""
        if self.process:
            try:
                logger.info(f"[{self.name}] 🛑 停止进程 (PID: {self.process.pid})")
                self.process.terminate()

                # 等待 5 秒让进程优雅关闭
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[{self.name}] ⚠️  进程未响应终止信号，强制杀死")
                    self.process.kill()
                    self.process.wait()

                logger.info(f"[{self.name}] ✅ 进程已停止")

            except Exception as e:
                logger.error(f"[{self.name}] ❌ 停止失败: {e}")

    def get_status(self) -> dict:
        """获取进程状态"""
        alive = self.is_alive()

        return {
            "name": self.name,
            "status": "online" if alive else "offline",
            "uptime_seconds": self.get_uptime() if alive else 0,
            "restart_count": self.restart_count,
            "pid": self.process.pid if self.process else None,
            "last_error": self.last_error,
        }


class BotManager:
    """管理所有 Bot 进程"""

    def __init__(self):
        self.bots = {}
        self._init_bots()
        self._setup_signals()
        self.running = False

    def _init_bots(self):
        """初始化所有 Bot"""
        for name, config in BOTS.items():
            self.bots[name] = BotProcess(name, config)

    def _setup_signals(self):
        """设置信号处理器，优雅关闭"""
        def signal_handler(sig, frame):
            logger.info(f"📊 收到信号 {sig}，准备关闭...")
            self.stop_all()
            sys.exit(0)

        signal.signal(signal.SIGTERM, signal_handler)
        signal.signal(signal.SIGINT, signal_handler)

    def start_all(self):
        """启动所有 Bot"""
        logger.info("=" * 60)
        logger.info("🤖 Sue Tech Bot Manager 启动")
        logger.info("=" * 60)

        self.running = True

        for name, bot in self.bots.items():
            bot.start()
            time.sleep(0.5)  # 稍微错开启动时间

    def monitor(self):
        """监控所有 Bot，失败时重启"""
        logger.info("📊 进入监控模式")

        check_interval = 10  # 每 10 秒检查一次
        health_check_interval = 60  # 每 60 秒打印一次健康状态

        last_health_check = time.time()

        while self.running:
            try:
                current_time = time.time()

                # 检查每个 Bot
                for name, bot in self.bots.items():
                    if not bot.is_alive():
                        logger.warning(f"[{name}] ⚠️  进程已死亡，准备重启...")
                        time.sleep(1)
                        bot.start()

                # 定期打印健康状态
                if current_time - last_health_check >= health_check_interval:
                    self._print_health_status()
                    last_health_check = current_time

                time.sleep(check_interval)

            except KeyboardInterrupt:
                logger.info("📊 收到中断信号")
                break
            except Exception as e:
                logger.error(f"❌ 监控循环异常: {e}")
                time.sleep(check_interval)

    def _print_health_status(self):
        """打印所有 Bot 的健康状态"""
        logger.info("-" * 60)
        logger.info("🏥 Bot 健康状态检查")

        for name, bot in self.bots.items():
            status = bot.get_status()
            status_emoji = "✅" if status["status"] == "online" else "❌"
            uptime = status["uptime_seconds"]
            uptime_str = f"{uptime // 3600}h {(uptime % 3600) // 60}m {uptime % 60}s"

            logger.info(
                f"{status_emoji} {name:6} | 状态: {status['status']:8} | "
                f"运行时间: {uptime_str:15} | 重启次数: {status['restart_count']}"
            )

        logger.info("-" * 60)

    def stop_all(self):
        """停止所有 Bot"""
        logger.info("🛑 关闭所有 Bot...")
        self.running = False

        for name, bot in self.bots.items():
            bot.stop()

        logger.info("✅ 所有 Bot 已关闭")


def main():
    """主入口"""
    manager = BotManager()

    try:
        manager.start_all()
        manager.monitor()
    except Exception as e:
        logger.error(f"❌ 致命错误: {e}")
        manager.stop_all()
        sys.exit(1)
    finally:
        manager.stop_all()


if __name__ == "__main__":
    main()
