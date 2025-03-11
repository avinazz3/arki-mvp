# ibkr_client.py

import logging
import time
import threading
from ibapi.client import EClient
from ibapi.wrapper import EWrapper
from ibapi.contract import Contract

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/ibkr_client.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class IBKRApp(EWrapper, EClient):
    """
    IBKR API client and wrapper
    """
    
    def __init__(self):
        EWrapper.__init__(self)
        EClient.__init__(self, wrapper=self)
        
        # Connection status
        self.connected = False
        self.connection_event = threading.Event()
        
        # Store account information
        self.accounts = []
        self.account_values = {}
        self.account_summary = {}
        
        # Events for synchronization
        self.account_summary_event = threading.Event()
        self.account_update_event = threading.Event()
    
    # Connection Methods
    def connect_to_ibkr(self, host, port, client_id):
        """Connect to IBKR TWS/Gateway"""
        logger.info(f"Connecting to IBKR at {host}:{port} with client_id {client_id}")
        
        # Connect to IBKR
        self.connect(host, port, client_id)
        
        # Start the client thread
        self.client_thread = threading.Thread(target=self.run)
        self.client_thread.daemon = True
        self.client_thread.start()
        
        # Wait for connection event with timeout
        if not self.connection_event.wait(timeout=10):
            logger.error("Failed to connect to IBKR")
            return False
        
        return self.connected
    
    def disconnect_from_ibkr(self):
        """Disconnect from IBKR"""
        logger.info("Disconnecting from IBKR")
        self.disconnect()
        self.connected = False
    
    # IBKR API Callback Methods
    def error(self, reqId, errorCode, errorString, advancedOrderRejectJson=""):
        """Called when an error occurs"""
        logger.error(f"Error {errorCode}: {errorString}")
    
    def connectAck(self):
        """Called when connection is acknowledged"""
        logger.info("Connection acknowledged by IBKR")
    
    def nextValidId(self, orderId):
        """Called when connection is established and next valid order ID is provided"""
        logger.info(f"Connected to IBKR. Next valid order ID: {orderId}")
        self.next_order_id = orderId
        self.connected = True
        self.connection_event.set()
    
    def managedAccounts(self, accountsList):
        """Called when managed accounts are returned"""
        accounts = accountsList.split(',')
        logger.info(f"Managed accounts: {accounts}")
        self.accounts = accounts
    
    # Account Data Methods
    def accountSummary(self, reqId, account, tag, value, currency):
        """Called when account summary data is received"""
        if account not in self.account_summary:
            self.account_summary[account] = {}
        
        key = tag
        if currency:
            key = f"{tag}_{currency}"
            
        self.account_summary[account][key] = value
        logger.debug(f"Account Summary: {account}, {tag}: {value} {currency}")
    
    def accountSummaryEnd(self, reqId):
        """Called when all account summary data has been received"""
        logger.info(f"Account Summary End for request {reqId}")
        self.account_summary_event.set()
    
    def updateAccountValue(self, key, val, currency, accountName):
        """Called when account information is received"""
        if accountName not in self.account_values:
            self.account_values[accountName] = {}
        
        field_name = key
        if currency:
            field_name = f"{key}_{currency}"
            
        self.account_values[accountName][field_name] = val
        logger.debug(f"Account Update: {accountName}, {key}: {val} {currency}")
    
    def accountDownloadEnd(self, accountName):
        """Called when all account data has been received"""
        logger.info(f"Account download completed for {accountName}")
        self.account_update_event.set()
    
    # Data Request Methods
    def request_account_summary(self, reqId=1):
        """Request account summary data"""
        logger.info("Requesting account summary data")
        self.account_summary_event.clear()
        
        # Request all account tags
        tags = "TotalCashValue,AvailableFunds,NetLiquidation"
        self.reqAccountSummary(reqId, "All", tags)
        
        # Wait for response with timeout
        if not self.account_summary_event.wait(30):
            logger.warning("Account summary request timed out after 30 seconds")
            
        return self.account_summary
    
    def request_account_updates(self, account):
        """Request account updates for the specified account"""
        logger.info(f"Requesting account updates for {account}")
        self.account_update_event.clear()
        
        # Subscribe to account updates
        self.reqAccountUpdates(True, account)
        
        # Wait for response with timeout
        if not self.account_update_event.wait(30):
            logger.warning("Account updates request timed out after 30 seconds")
            
        # Unsubscribe from updates
        self.reqAccountUpdates(False, account)
        
        return self.account_values.get(account, {})
    
    def request_positions(self):
        """Request all positions for managed accounts"""
        logger.info("Requesting positions for all accounts")
        
        # Clear existing positions
        self.account_values = {}
        
        # Request positions
        self.reqPositions()
        
        # Wait for response with timeout
        if not self.account_update_event.wait(30):
            logger.warning("Positions request timed out after 30 seconds")
            
        # Cancel positions subscription
        self.cancelPositions()
        
        return self.account_values