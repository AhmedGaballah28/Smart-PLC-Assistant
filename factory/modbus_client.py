"""
Modbus Client Wrapper
Handles communication with Factory I/O
"""

import logging
from typing import Optional, List
from pyModbusTCP.client import ModbusClient

from factory.config import (
    MODBUS_HOST,
    MODBUS_PORT,
    MODBUS_SLAVE_ID,
    MODBUS_TIMEOUT,
)

logger = logging.getLogger(__name__)


class FactoryModbusClient:
    """
    Modbus TCP client for Factory I/O communication.
    
    Wraps pyModbusTCP with error handling and logging.
    """

    def __init__(
        self,
        host: str = MODBUS_HOST,
        port: int = MODBUS_PORT,
        slave_id: int = MODBUS_SLAVE_ID,
        timeout: float = MODBUS_TIMEOUT,
    ):
        self.host = host
        self.port = port
        self.slave_id = slave_id
        self.timeout = timeout
        
        self.client: Optional[ModbusClient] = None
        self.is_connected = False
        
        # Statistics
        self._read_count = 0
        self._write_count = 0
        self._error_count = 0

    def connect(self) -> bool:
        """Connect to Factory I/O Modbus server."""
        try:
            self.client = ModbusClient(
                host=self.host,
                port=self.port,
                unit_id=self.slave_id,
                auto_open=True,
                auto_close=False,
                timeout=self.timeout,
            )
            
            if self.client.open():
                self.is_connected = True
                logger.info(f"✅ Connected to Factory I/O ({self.host}:{self.port})")
                return True
            else:
                logger.error(f"❌ Failed to connect to Factory I/O")
                return False
                
        except Exception as e:
            logger.error(f"❌ Modbus connection error: {e}")
            self._error_count += 1
            return False

    def disconnect(self):
        """Disconnect from Factory I/O."""
        if self.client:
            self.client.close()
        self.is_connected = False
        logger.info("Disconnected from Factory I/O")

    def read_input(self, address: int) -> Optional[bool]:
        """
        Read a single digital input (sensor).
        
        Args:
            address: Input address (0, 1, 2, ...)
            
        Returns:
            True/False if successful, None if error
        """
        try:
            result = self.client.read_discrete_inputs(address, 1)
            if result is None:
                # Try alternative method
                result = self.client.read_coils(address, 1)
            
            if result:
                self._read_count += 1
                return result[0]
            else:
                logger.warning(f"⚠️ Failed to read input {address}")
                self._error_count += 1
                return None
                
        except Exception as e:
            logger.error(f"❌ Error reading input {address}: {e}")
            self._error_count += 1
            return None

    def read_inputs(self, start_address: int, count: int) -> Optional[List[bool]]:
        """
        Read multiple digital inputs.
        
        Args:
            start_address: Starting address
            count: Number of inputs to read
            
        Returns:
            List of bool values, or None if error
        """
        try:
            result = self.client.read_discrete_inputs(start_address, count)
            if result is None:
                result = self.client.read_coils(start_address, count)
            
            if result:
                self._read_count += 1
                return list(result)
            else:
                logger.warning(f"⚠️ Failed to read inputs {start_address}-{start_address+count}")
                self._error_count += 1
                return None
                
        except Exception as e:
            logger.error(f"❌ Error reading inputs: {e}")
            self._error_count += 1
            return None

    def write_output(self, address: int, value: bool) -> bool:
        """
        Write a single digital output (actuator).
        
        Args:
            address: Output address (0, 1, 2, ...)
            value: True = ON, False = OFF
            
        Returns:
            True if successful, False if error
        """
        try:
            result = self.client.write_single_coil(address, value)
            
            if result:
                self._write_count += 1
                logger.debug(f"Output {address} = {value}")
                return True
            else:
                logger.warning(f"⚠️ Failed to write output {address}")
                self._error_count += 1
                return False
                
        except Exception as e:
            logger.error(f"❌ Error writing output {address}: {e}")
            self._error_count += 1
            return False

    def write_outputs(self, start_address: int, values: List[bool]) -> bool:
        """
        Write multiple digital outputs.
        
        Args:
            start_address: Starting address
            values: List of bool values
            
        Returns:
            True if successful, False if error
        """
        try:
            result = self.client.write_multiple_coils(start_address, values)
            
            if result:
                self._write_count += 1
                return True
            else:
                logger.warning(f"⚠️ Failed to write outputs {start_address}")
                self._error_count += 1
                return False
                
        except Exception as e:
            logger.error(f"❌ Error writing outputs: {e}")
            self._error_count += 1
            return False

    def get_statistics(self) -> dict:
        """Get communication statistics."""
        return {
            "is_connected": self.is_connected,
            "host": self.host,
            "port": self.port,
            "read_count": self._read_count,
            "write_count": self._write_count,
            "error_count": self._error_count,
        }