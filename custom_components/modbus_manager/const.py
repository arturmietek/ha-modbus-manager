"""Constants for Modbus Manager integration."""

DOMAIN = "modbus_manager"
PLATFORMS = ["binary_sensor", "switch", "sensor", "cover", "number"]

# Bus configuration keys
CONF_BUS_TYPE = "bus_type"
CONF_BUS_TYPE_RTU = "rtu"
CONF_BUS_TYPE_TCP = "tcp"
CONF_PORT = "port"
CONF_BAUDRATE = "baudrate"
CONF_PARITY = "parity"
CONF_STOPBITS = "stopbits"
CONF_BYTESIZE = "bytesize"
CONF_HOST = "host"
CONF_TCP_PORT = "tcp_port"
CONF_TIMEOUT = "timeout"

# Device configuration keys
CONF_DEVICES = "devices"
CONF_DEVICE_ID = "device_id"
CONF_DEVICE_NAME = "device_name"
CONF_SLAVE_ID = "slave_id"
CONF_SCAN_INTERVAL = "scan_interval"
CONF_DEFINITION = "definition"
CONF_DEFINITION_BUILTIN = "builtin"
CONF_DEFINITION_CUSTOM = "custom"
CONF_DEFINITION_USER = "user"
CONF_DEFINITION_SOURCE = "definition_source"
CONF_DEFINITION_FILE = "definition_file"
CONF_DEFINITION_USER_FILE = "definition_user_file"
CONF_DEFINITION_YAML = "definition_yaml"
CONF_DEVICE_PARAMS = "device_params"
CONF_DEVICE_ENABLED = "enabled"

# Modbus register types
REGISTER_COIL = "coil"
REGISTER_DISCRETE_INPUT = "discrete_input"
REGISTER_HOLDING = "holding"
REGISTER_INPUT = "input"

# Data types for multi-register values
DATA_TYPE_INT16 = "INT16"
DATA_TYPE_UINT16 = "UINT16"
DATA_TYPE_INT32 = "INT32"
DATA_TYPE_UINT32 = "UINT32"
DATA_TYPE_FLOAT32 = "FLOAT32"
DATA_TYPE_INT64 = "INT64"
DATA_TYPE_STRING = "STRING"

DATA_TYPE_REGISTER_COUNT = {
    DATA_TYPE_INT16: 1,
    DATA_TYPE_UINT16: 1,
    DATA_TYPE_INT32: 2,
    DATA_TYPE_UINT32: 2,
    DATA_TYPE_FLOAT32: 2,
    DATA_TYPE_INT64: 4,
}

# Byte order for multi-register values
BYTE_ORDER_BIG = "BIG"
BYTE_ORDER_LITTLE = "LITTLE"
BYTE_ORDER_BIG_SWAP = "BIG_SWAP"      # words big endian, bytes swapped
BYTE_ORDER_LITTLE_SWAP = "LITTLE_SWAP"  # words little endian, bytes swapped

# Entity types in device definition
ENTITY_TYPE_BINARY_SENSOR = "binary_sensor"
ENTITY_TYPE_SWITCH = "switch"
ENTITY_TYPE_SENSOR = "sensor"
ENTITY_TYPE_NUMBER = "number"
ENTITY_TYPE_TEXT = "text"
ENTITY_TYPE_COVER = "cover"

# Coordinator update interval defaults (seconds)
DEFAULT_SCAN_INTERVAL = 10
DEFAULT_TIMEOUT = 3

# RTU defaults
DEFAULT_BAUDRATE = 9600
DEFAULT_PARITY = "N"
DEFAULT_STOPBITS = 1
DEFAULT_BYTESIZE = 8

# TCP defaults
DEFAULT_TCP_PORT = 502
