#!/usr/bin/env python3
# GPL-3.0 License — Copyright (c) 2026 csteenwyk
# https://github.com/csteenwyk/udi-roborock-poly/blob/main/LICENSE
"""
Roborock Polyglot v3 NodeServer
Communicates with Roborock vacuums via the python-roborock library.
Prefers direct LAN communication; falls back to cloud MQTT automatically.

Authentication uses email + one-time verification code (no password).
Credentials are cached in Polyglot customdata after first login.

Custom Parameters:
  email         — Roborock account email (required)
  login_code    — Verification code sent to email (set to trigger first-time login)
"""

import asyncio
import os
import re
import sys
import threading

import udi_interface
from udi_interface import Custom

try:
    from roborock.roborock_typing import RoborockCommand
    from roborock.web_api import RoborockApiClient
    from roborock.data.containers import UserData
    from roborock.devices.device_manager import create_device_manager, UserParams
except ImportError:
    RoborockCommand = RoborockApiClient = UserData = create_device_manager = UserParams = None

LOGGER = udi_interface.LOGGER

_PLUGIN_DIR  = os.path.dirname(os.path.abspath(__file__))
_PROFILE_DIR = os.path.join(_PLUGIN_DIR, 'profile')

# ---------------------------------------------------------------------------
# State / mode mappings
# ---------------------------------------------------------------------------

# Roborock state int → compact ISY index (0-based)
_ROBOROCK_TO_STATE = {
    0:   0,   # Unknown
    1:   1,   # Starting → Cleaning
    2:   2,   # Charger disconnected → Idle
    3:   2,   # Idle
    4:   1,   # Remote control → Cleaning
    5:   1,   # Cleaning
    6:   3,   # Returning home
    7:   1,   # Manual mode → Cleaning
    8:   4,   # Charging
    9:   5,   # Charging problem → Error
    10:  6,   # Paused
    11:  7,   # Spot cleaning
    12:  5,   # Error
    13:  2,   # Shutting down → Idle
    14:  2,   # Updating → Idle
    15:  3,   # Docking → Returning
    16:  1,   # Going to target → Cleaning
    17:  1,   # Zoned cleaning → Cleaning
    18:  1,   # Segment cleaning → Cleaning
    22:  8,   # Emptying bin
    23:  9,   # Washing mop
    26:  9,   # Going to wash → Washing mop
    100: 10,  # Charging complete
    101: 11,  # Device offline
}

# ISY index → Roborock fan_power value
FAN_SPEED_MAP  = {0: 101, 1: 102, 2: 103, 3: 104}   # Quiet/Balanced/Turbo/Max
_FAN_TO_IDX    = {v: k for k, v in FAN_SPEED_MAP.items()}

# ISY index → Roborock water_box_mode value
WATER_MAP    = {0: 200, 1: 201, 2: 202, 3: 203}      # Off/Mild/Moderate/Intense
_WATER_TO_IDX = {v: k for k, v in WATER_MAP.items()}

# ISY index → Roborock mop_mode value (common across all S/Q models)
MOP_MODE_MAP  = {0: 300, 1: 301, 2: 303}             # Standard/Deep/Deep+
_MOP_TO_IDX   = {v: k for k, v in MOP_MODE_MAP.items()}

# Consumable max usage times in seconds (manufacturer rated life)
_CONSUMABLE_MAX = {
    'main_brush': 300 * 3600,   # 300 h
    'side_brush': 200 * 3600,   # 200 h
    'filter':     150 * 3600,   # 150 h
    'sensor':      30 * 3600,   #  30 h
}

# ---------------------------------------------------------------------------
# Static profile content
# ---------------------------------------------------------------------------

_STATIC_NLS = """\
# Node Server Names
ND-roborock_controller-NAME = Roborock Controller
ND-roborock_vacuum-NAME = Roborock Vacuum

# Controller Drivers
ST-roborock_controller-ST-NAME = Status

# Controller Commands
CMD-roborock_controller-DISCOVER-NAME = Re-Discover
CMD-roborock_controller-REQUEST_CODE-NAME = Request Login Code
CMD-roborock_controller-QUERY-NAME = Query All

# Vacuum Drivers
ST-roborock_vacuum-ST-NAME = State
ST-roborock_vacuum-BATLVL-NAME = Battery
ST-roborock_vacuum-GV1-NAME = Fan Speed
ST-roborock_vacuum-GV2-NAME = Error
ST-roborock_vacuum-GV3-NAME = Clean Area (m\u00b2)
ST-roborock_vacuum-GV4-NAME = Clean Time (min)
ST-roborock_vacuum-GV5-NAME = Main Brush
ST-roborock_vacuum-GV6-NAME = Side Brush
ST-roborock_vacuum-GV7-NAME = Filter
ST-roborock_vacuum-GV8-NAME = Water Box
ST-roborock_vacuum-GV9-NAME = Water Level
ST-roborock_vacuum-GV10-NAME = Mop Mode
ST-roborock_vacuum-GV11-NAME = Child Lock

# Vacuum Commands
CMD-roborock_vacuum-START-NAME = Start Cleaning
CMD-roborock_vacuum-STOP-NAME = Stop
CMD-roborock_vacuum-PAUSE-NAME = Pause
CMD-roborock_vacuum-DOCK-NAME = Return to Dock
CMD-roborock_vacuum-LOCATE-NAME = Locate (Find Me)
CMD-roborock_vacuum-SET_FAN-NAME = Set Fan Speed
CMD-roborock_vacuum-SET_WATER-NAME = Set Water Level
CMD-roborock_vacuum-SET_MOP-NAME = Set Mop Mode
CMD-roborock_vacuum-SET_CHILD_LOCK-NAME = Child Lock
CMD-roborock_vacuum-CLEAN_ROOM-NAME = Clean Room
CMD-roborock_vacuum-QUERY-NAME = Query

# Vacuum state index values (UOM 25)
CUST_VSTATE-0 = Unknown
CUST_VSTATE-1 = Cleaning
CUST_VSTATE-2 = Idle
CUST_VSTATE-3 = Returning
CUST_VSTATE-4 = Charging
CUST_VSTATE-5 = Error
CUST_VSTATE-6 = Paused
CUST_VSTATE-7 = Spot Cleaning
CUST_VSTATE-8 = Emptying Bin
CUST_VSTATE-9 = Washing Mop
CUST_VSTATE-10 = Charging Complete
CUST_VSTATE-11 = Offline

# Fan speed index values (UOM 25)
CUST_FAN-0 = Quiet
CUST_FAN-1 = Balanced
CUST_FAN-2 = Turbo
CUST_FAN-3 = Max

# Water level index values (UOM 25)
CUST_WATER-0 = Off
CUST_WATER-1 = Mild
CUST_WATER-2 = Moderate
CUST_WATER-3 = Intense

# Mop mode index values (UOM 25)
CUST_MOP-0 = Standard
CUST_MOP-1 = Deep
CUST_MOP-2 = Deep+
"""

_STATIC_EDITORS = """\
  <editor id="E_VSTATE">
    <range uom="25" subset="0,1,2,3,4,5,6,7,8,9,10,11" nls="CUST_VSTATE"/>
  </editor>
  <editor id="E_FAN">
    <range uom="25" subset="0,1,2,3" nls="CUST_FAN"/>
  </editor>
  <editor id="E_WATER">
    <range uom="25" subset="0,1,2,3" nls="CUST_WATER"/>
  </editor>
  <editor id="E_PERCENT">
    <range uom="51" min="0" max="100" prec="0"/>
  </editor>
  <editor id="E_AREA">
    <range uom="56" min="0" max="9999" prec="1"/>
  </editor>
  <editor id="E_TIME">
    <range uom="56" min="0" max="9999" prec="0"/>
  </editor>
  <editor id="E_STATUS">
    <range uom="2" subset="0,1"/>
  </editor>
  <editor id="E_MOP">
    <range uom="25" subset="0,1,2" nls="CUST_MOP"/>
  </editor>\
"""


def _subset(lst):
    return ','.join(str(i) for i in range(len(lst))) if lst else '0'


def _device_address(raw_name, duid):
    return re.sub(r'[^a-z0-9]', '', raw_name.lower())[:14] or duid[:14]


def _write_profile(rooms):
    """Write dynamic NLS and editors.xml with current room list."""
    lines = [_STATIC_NLS]
    lines.append('# Dynamic — Rooms')
    for i, name in enumerate(rooms):
        lines.append(f'CUST_ROOM-{i} = {name}')
    if not rooms:
        lines.append('CUST_ROOM-0 = (no rooms)')

    with open(os.path.join(_PROFILE_DIR, 'nls', 'en_us.txt'), 'w') as f:
        f.write('\n'.join(lines) + '\n')

    editors_xml = f"""<editors>
{_STATIC_EDITORS}

  <!-- Dynamic — Rooms (fetched from Roborock home data) -->
  <editor id="E_ROOM">
    <range uom="25" subset="{_subset(rooms)}" nls="CUST_ROOM"/>
  </editor>
</editors>
"""
    with open(os.path.join(_PROFILE_DIR, 'editor', 'editors.xml'), 'w') as f:
        f.write(editors_xml)

    LOGGER.info(f'Profile updated: {len(rooms)} rooms')


# ---------------------------------------------------------------------------
# Async bridge — runs a persistent event loop in a background thread
# ---------------------------------------------------------------------------

class _AsyncBridge:
    def __init__(self):
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name='roborock-async')
        self._thread.start()

    def run(self, coro, timeout=30):
        """Submit a coroutine to the background loop and block until done."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except asyncio.TimeoutError:
            LOGGER.error('Async call timed out')
            return None
        except Exception as e:
            LOGGER.error(f'Async error: {e}')
            return None

    def shutdown(self):
        self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------------------
# Vacuum Node
# ---------------------------------------------------------------------------

class VacuumNode(udi_interface.Node):
    """One node per Roborock device."""

    id = 'roborock_vacuum'

    drivers = [
        {'driver': 'ST',    'value': 0,  'uom': 25},
        {'driver': 'BATLVL','value': 0,  'uom': 51},
        {'driver': 'GV1',   'value': 0,  'uom': 25},
        {'driver': 'GV2',   'value': 0,  'uom': 25},
        {'driver': 'GV3',   'value': 0,  'uom': 56},
        {'driver': 'GV4',   'value': 0,  'uom': 56},
        {'driver': 'GV5',   'value': 100,'uom': 51},
        {'driver': 'GV6',   'value': 100,'uom': 51},
        {'driver': 'GV7',   'value': 100,'uom': 51},
        {'driver': 'GV8',   'value': 0,  'uom': 2},
        {'driver': 'GV9',   'value': 0,  'uom': 25},
        {'driver': 'GV10',  'value': 0,  'uom': 25},
        {'driver': 'GV11',  'value': 0,  'uom': 2},
    ]

    def __init__(self, polyglot, primary, address, name, device_id, ctrl):
        super().__init__(polyglot, primary, address, name)
        self.device_id  = device_id   # Roborock device duid
        self._ctrl      = ctrl
        self._driver_cache: dict = {}

    def _set(self, driver, value):
        if self._driver_cache.get(driver) != value:
            self._driver_cache[driver] = value
            self.setDriver(driver, value)

    def _device(self):
        return self._ctrl._devices.get(self.device_id)

    def _run(self, coro, timeout=30):
        return self._ctrl._async.run(coro, timeout=timeout)

    # --- State update ---
    def update_from_status(self, status):
        """Apply a Roborock StatusTrait to ISY drivers.
        StatusTrait inherits StatusV2, so attribute names are unchanged."""
        raw_state  = getattr(status, 'state',            0) or 0
        battery    = getattr(status, 'battery',          0) or 0
        fan_power  = getattr(status, 'fan_power',      101) or 101
        error_code = getattr(status, 'error_code',       0) or 0
        area_cm2   = getattr(status, 'clean_area',       0) or 0
        clean_sec  = getattr(status, 'clean_time',       0) or 0
        water_box  = getattr(status, 'water_box_status', 0) or 0
        water_mode = getattr(status, 'water_box_mode',   0) or 0
        mop_mode   = getattr(status, 'mop_mode',         0) or 0
        lock       = getattr(status, 'lock_status',      0) or 0

        self._set('ST',    _ROBOROCK_TO_STATE.get(raw_state, 0))
        self._set('BATLVL', battery)
        self._set('GV1',   _FAN_TO_IDX.get(fan_power, 1))
        self._set('GV2',   error_code)
        self._set('GV3',   round(area_cm2 / 1_000_000, 1))
        self._set('GV4',   clean_sec // 60)
        self._set('GV8',   1 if water_box else 0)
        self._set('GV9',   _WATER_TO_IDX.get(water_mode, 0))
        self._set('GV10',  _MOP_TO_IDX.get(mop_mode, 0))
        self._set('GV11',  1 if lock else 0)

    def update_from_consumables(self, consumables):
        def _pct(used, key):
            mx = _CONSUMABLE_MAX.get(key, 1)
            return max(0, round((1 - used / mx) * 100))

        mb = getattr(consumables, 'main_brush_work_time', 0) or 0
        sb = getattr(consumables, 'side_brush_work_time', 0) or 0
        f  = getattr(consumables, 'filter_work_time',     0) or 0
        self._set('GV5', _pct(mb, 'main_brush'))
        self._set('GV6', _pct(sb, 'side_brush'))
        self._set('GV7', _pct(f,  'filter'))

    def query(self, command=None):
        device = self._device()
        if not device or not getattr(device, 'v1_properties', None):
            return
        props = device.v1_properties

        async def _refresh():
            await asyncio.gather(props.status.refresh(), props.consumables.refresh())

        self._run(_refresh(), timeout=30)
        self.update_from_status(props.status)
        self.update_from_consumables(props.consumables)
        self.reportDrivers()

    # --- Commands ---
    def _send(self, cmd, params=None):
        device = self._device()
        if not device or not getattr(device, 'v1_properties', None):
            LOGGER.warning(f'{self.name}: no device available')
            return
        coro = device.v1_properties.command.send(cmd, params)
        self._run(coro)

    def cmd_start(self, command):
        self._send(RoborockCommand.APP_START)

    def cmd_stop(self, command):
        self._send(RoborockCommand.APP_STOP)

    def cmd_pause(self, command):
        self._send(RoborockCommand.APP_PAUSE)

    def cmd_dock(self, command):
        self._send(RoborockCommand.APP_CHARGE)

    def cmd_locate(self, command):
        self._send(RoborockCommand.FIND_ME)

    def cmd_set_fan(self, command):
        idx = int(command.get('value', 1))
        fan_power = FAN_SPEED_MAP.get(idx, 102)
        self._send(RoborockCommand.SET_CUSTOM_MODE, [fan_power])

    def cmd_set_water(self, command):
        idx = int(command.get('value', 1))
        water_mode = WATER_MAP.get(idx, 201)
        self._send(RoborockCommand.SET_WATER_BOX_CUSTOM_MODE, [water_mode])

    def cmd_set_mop(self, command):
        idx = int(command.get('value', 0))
        mop_val = MOP_MODE_MAP.get(idx, 300)
        self._send(RoborockCommand.SET_MOP_MODE, [mop_val])

    def cmd_set_child_lock(self, command):
        val = int(command.get('value', 0))
        self._send(RoborockCommand.SET_CHILD_LOCK_STATUS, {'lock_status': 1 if val else 0})

    def cmd_clean_room(self, command):
        idx = int(command.get('value', 0))
        room_ids = self._ctrl.room_ids
        if idx < len(room_ids):
            self._send(RoborockCommand.APP_SEGMENT_CLEAN,
                       [{'segments': [room_ids[idx]], 'repeat': 1}])
        else:
            LOGGER.warning(f'{self.name}: room index {idx} out of range')

    commands = {
        'START':      cmd_start,
        'STOP':       cmd_stop,
        'PAUSE':      cmd_pause,
        'DOCK':       cmd_dock,
        'LOCATE':     cmd_locate,
        'SET_FAN':    cmd_set_fan,
        'SET_WATER':       cmd_set_water,
        'SET_MOP':         cmd_set_mop,
        'SET_CHILD_LOCK':  cmd_set_child_lock,
        'CLEAN_ROOM':      cmd_clean_room,
        'QUERY':      query,
    }


# ---------------------------------------------------------------------------
# Controller Node
# ---------------------------------------------------------------------------

class Controller(udi_interface.Node):

    id = 'roborock_controller'

    drivers = [
        {'driver': 'ST', 'value': 0, 'uom': 2},
    ]

    def __init__(self, polyglot, primary, address, name):
        super().__init__(polyglot, primary, address, name)
        self.poly = polyglot

        # State
        self._email           = ''
        self._device_manager  = None   # DeviceManager (owns MQTT + all devices)
        self._devices         = {}     # duid → RoborockDevice
        self._vacuums         = {}     # address → VacuumNode
        self.rooms            = []     # room name strings (for ISY dropdown)
        self.room_ids         = []     # parallel segment IDs
        self._customdata      = Custom(polyglot, 'customdata')
        self._params          = Custom(polyglot, 'customparams')
        self._login_api       = None   # reuse client between request_code and code_login
        self._initialized     = False
        self._controller_added = False

        # Infrastructure
        self._async       = _AsyncBridge()
        self._poll_lock   = threading.Lock()
        self._node_added  = threading.Event()

        polyglot.subscribe(polyglot.CONFIGDONE,   self._on_config_done)
        polyglot.subscribe(polyglot.START,        self.start)
        polyglot.subscribe(polyglot.CUSTOMPARAMS, self.param_handler)
        polyglot.subscribe(polyglot.CUSTOMDATA,   self.data_handler)
        polyglot.subscribe(polyglot.POLL,         self.poll)
        polyglot.subscribe(polyglot.STOP,         self.stop)
        polyglot.subscribe(polyglot.ADDNODEDONE,  self._on_node_added)
        polyglot.ready()

    # --- Node lifecycle ---

    def _on_node_added(self, data):
        LOGGER.debug(f'ADDNODEDONE: {data}')
        self._node_added.set()

    def _add_node_wait(self, node, timeout=15):
        self._node_added.clear()
        self.poly.addNode(node)
        if not self._node_added.wait(timeout=timeout):
            LOGGER.warning(f'Timeout waiting for node {getattr(node, "address", "?")}')

    def _on_config_done(self):
        """Fires after all getAll responses are processed — always fires, even on
        first install when no nodes exist yet."""
        if self._controller_added:
            return
        LOGGER.info('Config done — adding controller node')
        try:
            # Only clear the profile on first install. On restarts, param_handler
            # fires before CONFIGDONE and the connection may already be live with
            # rooms populated — don't wipe them.
            if not self.rooms:
                _write_profile([])
            self._add_node_wait(self, timeout=3)
            self._controller_added = True
            self.setDriver('ST', 1)
            if not self._initialized:
                self._try_connect()
        except Exception as e:
            LOGGER.error(f'Failed to add controller node: {e}', exc_info=True)

    def start(self):
        """Called by udi_interface after a fresh addNode is acknowledged."""
        LOGGER.info('Roborock NodeServer start event')
        self._controller_added = True
        self.setDriver('ST', 1)
        if not self._initialized:
            self._try_connect()

    def stop(self):
        LOGGER.info('Roborock NodeServer stopping')
        self.setDriver('ST', 0)
        if self._device_manager:
            self._async.run(self._device_manager.close(), timeout=10)
        self._async.shutdown()

    # --- Parameter / data handlers ---

    def param_handler(self, params):
        self._params.load(params)
        self.poly.Notices.clear()
        email = params.get('email', '').strip()
        code  = params.get('login_code', '').strip()

        if not email:
            self.poly.Notices['config'] = 'Set your Roborock account email in Custom Parameters'
            return

        self._email = email

        if code:
            code = re.sub(r'\D', '', code)   # strip spaces/dashes the user may have typed
            LOGGER.info('Login code provided — attempting login')
            self._async.run(self._do_code_login(code))
            # Clear the code from params so it isn't stored in plain text
            self._params['login_code'] = ''
        elif not self._initialized:
            # No code yet — try with cached credentials
            self._try_connect()

    def data_handler(self, data):
        """Called by udi_interface when customdata is loaded."""
        self._customdata.load(data)

    def _try_connect(self):
        """Attempt to connect using cached credentials."""
        creds = self._customdata.get('roborock_creds')
        if not creds:
            if self._email:
                self.poly.Notices['auth'] = (
                    'No credentials cached. Click "Request Login Code" on the '
                    'controller, then enter the code in the login_code parameter.')
            return
        self._async.run(self._connect_with_creds(creds))

    async def _connect_with_user_data(self, user_data):
        """Create a device manager from UserData and discover devices."""
        user_params = UserParams(username=self._email, user_data=user_data)
        self._device_manager = await create_device_manager(user_params)
        devices = await self._device_manager.get_devices()
        await self._setup_devices(devices)

    async def _connect_with_creds(self, creds_dict):
        """Restore a session from cached credentials and discover devices."""
        try:
            user_data = UserData.from_dict(creds_dict)
            await self._connect_with_user_data(user_data)
        except Exception as e:
            LOGGER.error(f'Failed to connect with cached credentials: {e}')
            self.poly.Notices['auth'] = f'Re-authentication required: {e}'

    async def _do_code_login(self, code):
        """Exchange a verification code for credentials, cache, then connect."""
        try:
            # Reuse the same client that sent the code — it may hold region state.
            api = self._login_api or RoborockApiClient(username=self._email)
            user_data = await api.code_login(code)
            self._login_api = None
            self._customdata['roborock_creds'] = user_data.as_dict()
            LOGGER.info('Login successful — credentials cached')
            await self._connect_with_user_data(user_data)
        except Exception as e:
            LOGGER.error(f'Code login failed: {e}')
            self.poly.Notices['auth'] = f'Login failed: {e}. Check the code and try again.'

    async def _setup_devices(self, devices):
        """Store devices and collect rooms from each V1 device."""
        try:
            self._devices = {d.duid: d for d in devices}

            all_rooms = []
            all_room_ids = []
            for device in devices:
                props = getattr(device, 'v1_properties', None)
                if not props:
                    continue
                fetched = False
                # Prefer maps API: gives per-floor (per-map) room lists with names
                try:
                    await props.maps.refresh()
                    for map_info in (props.maps.map_info or []):
                        floor = (map_info.name or 'Floor').strip()
                        for room in (map_info.rooms or []):
                            seg_id  = getattr(room, 'id', None)
                            name    = getattr(room, 'iot_name', None) or str(seg_id)
                            all_rooms.append(f'{floor}: {name}')
                            all_room_ids.append(seg_id)
                    fetched = bool(all_rooms)
                except Exception as e:
                    LOGGER.warning(f'Could not fetch maps for {device.name}: {e}')

                if not fetched:
                    # Fall back to flat rooms list (no floor info)
                    try:
                        await props.rooms.refresh()
                        for room in (props.rooms.rooms or []):
                            seg_id = room.segment_id
                            name   = getattr(room, 'raw_name', None) or str(seg_id)
                            all_rooms.append(name)
                            all_room_ids.append(seg_id)
                    except Exception as e:
                        LOGGER.warning(f'Could not fetch rooms for {device.name}: {e}')

            self.rooms    = all_rooms
            self.room_ids = all_room_ids
            self._initialized = True
            self._discover_nodes(devices)
        except Exception as e:
            LOGGER.error(f'Device setup failed: {e}')

    def _discover_nodes(self, devices):
        """Add VacuumNode entries to ISY for each device (runs in sync context)."""
        _write_profile(self.rooms)

        for device in devices:
            address = _device_address(device.name, device.duid)
            if address not in self._vacuums:
                LOGGER.info(f'Adding vacuum node: {device.name} ({address})')
                node = VacuumNode(
                    self.poly, self.address, address, device.name, device.duid, self)
                self._add_node_wait(node)
                self._vacuums[address] = node

        self.poly.updateProfile()
        for node in self._vacuums.values():
            node.query()

    # --- Commands ---

    def cmd_request_code(self, command):
        """Send a verification code to the configured email address."""
        if not self._email:
            self.poly.Notices['config'] = 'Set email in Custom Parameters first'
            return

        async def _request():
            # Keep the client instance — request_code() may store region state
            # that code_login() needs to use the same endpoint.
            self._login_api = RoborockApiClient(username=self._email)
            await self._login_api.request_code()
            LOGGER.info(f'Verification code sent to {self._email}')
            self.poly.Notices['auth'] = (
                f'Code sent to {self._email}. Enter it in the login_code parameter.')

        self._async.run(_request())

    def cmd_discover(self, command=None):
        if not self._initialized:
            self._try_connect()
        else:
            for node in self._vacuums.values():
                node.query()

    def query(self, command=None):
        self.reportDrivers()
        for node in self._vacuums.values():
            node.query()

    def poll(self, flag):
        if not self._initialized:
            return
        if not self._poll_lock.acquire(blocking=False):
            LOGGER.debug('Poll already running, skipping')
            return
        try:
            if flag == 'shortPoll':
                self._short_poll()
            else:
                self._long_poll()
        finally:
            self._poll_lock.release()

    def _poll_all(self, refresh_fn, update_fn, label):
        async def _fetch_one(node, device):
            try:
                await refresh_fn(device)
                update_fn(node, device)
            except Exception as e:
                LOGGER.warning(f'{label} poll failed for {node.name}: {e}')

        async def _fetch_all():
            pairs = [(node, self._devices[node.device_id])
                     for node in self._vacuums.values()
                     if node.device_id in self._devices
                     and getattr(self._devices[node.device_id], 'v1_properties', None)]
            await asyncio.gather(*[_fetch_one(n, d) for n, d in pairs])

        self._async.run(_fetch_all(), timeout=60)

    def _short_poll(self):
        self._poll_all(
            lambda d: d.v1_properties.status.refresh(),
            lambda n, d: n.update_from_status(d.v1_properties.status),
            'Short',
        )

    def _long_poll(self):
        self._poll_all(
            lambda d: d.v1_properties.consumables.refresh(),
            lambda n, d: n.update_from_consumables(d.v1_properties.consumables),
            'Long',
        )

    commands = {
        'DISCOVER':      cmd_discover,
        'REQUEST_CODE':  cmd_request_code,
        'QUERY':         query,
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    try:
        poly = udi_interface.Interface([])
        poly.start()
        Controller(poly, 'controller', 'controller', 'Roborock')
        poly.runForever()
    except (KeyboardInterrupt, SystemExit):
        sys.exit(0)
    except Exception as e:
        LOGGER.exception(f'Fatal error: {e}')
        sys.exit(1)
