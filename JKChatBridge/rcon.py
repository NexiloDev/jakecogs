import socket
import time
from concurrent.futures import ThreadPoolExecutor

class RCONHandler:
    def setup_attributes(self):
        self.executor = ThreadPoolExecutor(max_workers=2)

    def send_rcon_command(self, command, host, port, password):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(1)
        cmd = self.clean_for_latin1(command)
        pwd = self.clean_for_latin1(password)
        packet = b'\xff\xff\xff\xffrcon ' + pwd.encode('latin-1') + b' ' + cmd.encode('latin-1')
        try:
            sock.sendto(packet, (host, port))
            time.sleep(0.1)
            response = b""
            start = time.time()
            while time.time() - start < 5:
                try:
                    data, _ = sock.recvfrom(16384)
                    response += data
                except socket.timeout:
                    break
            if not response:
                raise Exception("No response")
            return response
        except Exception as e:
            raise Exception(f"RCON error: {e}")
        finally:
            sock.close()

    async def validate_rcon_settings(self):
        return all([await self.config.rcon_host(), await self.config.rcon_port(), await self.config.rcon_password()])

    async def send_welcome_message(self, message: str):
        await asyncio.sleep(5)
        try:
            await self.bot.loop.run_in_executor(
                self.executor, self.send_rcon_command,
                message, await self.config.rcon_host(),
                await self.config.rcon_port(), await self.config.rcon_password()
            )
        except Exception as e:
            logger.error(f"Welcome message failed: {e}")

    async def auto_reload_monitor(self):
        while True:
            try:
                await asyncio.sleep(300)
                await self.reload_monitor()
                logger.debug("Auto-reload triggered")
            except Exception as e:
                logger.error(f"Auto-reload error: {e}")
                await asyncio.sleep(300)