import re
import math
import httpx
from lxml import etree
from utils import Preferences
from humanfriendly import parse_size
import time
import psutil
import json

from parsers.uptime import system_uptime
from parsers.cpu import cpu_temperature_avg, cpu_utilization, cpuload
from parsers.memory import update1
from parsers.network import update3
from parsers.tempsensors import temperature
from parsers.parity import parity
from parsers.disks import disks
from parsers.shares import shares
from parsers.vms import vms
from parsers.array_status import array_status
from parsers.update2 import update2
from parsers.ups import handle_ups


async def default(self, msg_data, create_config):
    pass


async def session(self, msg_data, create_config):
    self.csrf_token = msg_data


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]*>", "", s).strip()


def _to_int(text: str) -> int:
    m = re.search(r"[-+]?\d+", text)
    return int(m.group(0)) if m else 0


async def apcups(self, msg_data, create_config):
    """
    Unraid WS 'apcups' frames on your system look like:
      ["Back-UPS XS 1500M","<span class='green-text'>Online</span>","<span class='green-text'>100 %</span>","<span class='green-text'>30 minutes</span>","<span class='green-text'>900 W</span>","<span class='green-text'>180 W (20 %)</span>","<span>-</span>"]

    We convert that array into an APC-like dict and delegate to parsers.ups.handle_ups.
    Fields we emit (matching your UPS_FIELD_MAP):
      MODEL, STATUS, BCHARGE, TIMELEFT (minutes), NOMPOWER (W), LOADPCT (%)
    """
    data_dict = None

    # 1) Try JSON-decode
    try:
        j = json.loads(msg_data)
    except Exception:
        j = None

    # 2) If it's already a dict, pass through
    if isinstance(j, dict):
        data_dict = j

    # 3) If it's the array-of-HTML-strings we saw in DevTools, parse it
    elif isinstance(j, list) and len(j) >= 6:
        try:
            model_raw   = j[0]
            status_raw  = j[1]
            batt_raw    = j[2]
            time_raw    = j[3]
            nompwr_raw  = j[4]
            load_raw    = j[5]

            model   = _strip_html(str(model_raw))
            status  = _strip_html(str(status_raw))
            bcharge = _to_int(_strip_html(str(batt_raw)))            # e.g. "100 %"
            # "30 minutes" -> 30
            timeleft_min = _to_int(_strip_html(str(time_raw)))
            nompower_w   = _to_int(_strip_html(str(nompwr_raw)))     # e.g. "900 W"
            # "180 W (20 %)" -> 20
            load_w = _to_int(_strip_html(str(load_raw)))
            load_pct = 0
            m = re.search(r"\((\s*\d+)\s*%\)", _strip_html(str(load_raw)))
            if m:
                load_pct = int(m.group(1))

            data_dict = {
                "MODEL": model,
                "STATUS": status,
                "BCHARGE": bcharge,
                "TIMELEFT": timeleft_min,
                "NOMPOWER": nompower_w,
                "LOADPCT": load_pct,
                "LOADW": load_w,
            }
        except Exception:
            self.logger.exception("apcups: failed to parse array payload")
            data_dict = None

    # 4) If still nothing usable, bail quietly
    if not isinstance(data_dict, dict) or not data_dict:
        return

    # 5) Ensure we announce discovery once even if first frame was empty
    if not hasattr(self, "_apcups_announced"):
        self._apcups_announced = False
    force_config = create_config or not self._apcups_announced

    handle_ups(self, data_dict, force_config)
    self._apcups_announced = True
