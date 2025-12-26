from .parsers.uptime import system_uptime
from .parsers.cpu import cpu_temperature_avg, cpuload
from .parsers.memory import update1
from .parsers.network import update3
from .parsers.tempsensors import temperature
from .parsers.parity import parity
from .parsers.disks import disks
from .parsers.shares import shares
from .parsers.vms import vms
from .parsers.ups import handle_ups  # UPS handler

import json


async def default(self, msg_data, create_config):
    pass


async def session(self, msg_data, create_config):
    self.csrf_token = msg_data


async def apcups(self, msg_data, create_config):
    """
    Handle Unraid WS 'apcups' frames.
    Parse JSON and delegate to ups.handle_ups
    """
    try:
        data = json.loads(msg_data)
        if not isinstance(data, dict):
            return
    except Exception:
        self.logger.exception("apcups: failed to parse message JSON")
        return

    handle_ups(self, data, create_config)
