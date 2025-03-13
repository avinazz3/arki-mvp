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

    # Add these methods to your IBKRApp class

    # Market Data Methods
    def tickPrice(self, reqId, tickType, price, attrib):
        """Called when price data is received"""
        if not hasattr(self, 'market_data'):
            self.market_data = {}
        
        if reqId not in self.market_data:
            self.market_data[reqId] = {}
        
        # Store the price based on tickType
        # 4 = Last Price, 1 = Bid, 2 = Ask
        self.market_data[reqId][tickType] = price
        
        # If it's the last price, log it
        if tickType == 4:
            logger.info(f"Market data received for reqId {reqId}: Last Price = {price}")

    def tickSize(self, reqId, tickType, size):
        """Called when size data is received"""
        pass  # We can implement this if needed

    def tickString(self, reqId, tickType, value):
        """Called when string data is received"""
        pass  # We can implement this if needed

    def tickGeneric(self, reqId, tickType, value):
        """Called when generic tick data is received"""
        pass  # We can implement this if needed

    def marketDataType(self, reqId, marketDataType):
        """Called when the market data type changes"""
        logger.info(f"Market data type for reqId {reqId}: {marketDataType}")

    def request_market_data(self, contract, snapshot=False, timeout=5):
        """Request market data for a contract and wait for the response"""
        if not hasattr(self, 'market_data'):
            self.market_data = {}
        
        # Generate a request ID
        reqId = self.next_order_id
        self.next_order_id += 1
        
        # Clear any existing data for this request ID
        if reqId in self.market_data:
            del self.market_data[reqId]
        
        # Request market data
        logger.info(f"Requesting market data for {contract.symbol} ({contract.secType})")
        self.reqMktData(reqId, contract, "", snapshot, False, [])
        
        # Wait for data to arrive with timeout
        start_time = time.time()
        while (reqId not in self.market_data or 
            4 not in self.market_data.get(reqId, {}) or 
            self.market_data[reqId].get(4) == 0) and time.time() - start_time < timeout:
            time.sleep(0.1)
        
        # Get the price
        price = None
        if reqId in self.market_data and 4 in self.market_data[reqId]:
            price = self.market_data[reqId][4]  # Get Last Price (tickType 4)
        
        # Cancel the market data subscription if it wasn't a snapshot
        if not snapshot:
            self.cancelMktData(reqId)
        
        if price is not None and price > 0:
            logger.info(f"Retrieved market price for {contract.symbol}: {price}")
            return price
        else:
            logger.warning(f"Could not retrieve valid price for {contract.symbol}")
            return None
    
    def request_delayed_market_data(self, contract):
        """
        Request delayed market data for a contract
        
        Args:
            contract: Contract object
            
        Returns:
            float: Market price (delayed)
        """
        try:
            # Set market data type to delayed
            if hasattr(self, 'client'):
                self.client.reqMarketDataType(3)  # 3 = delayed data
            
            # Request market data
            price = self.request_market_data(contract)
            
            # Set market data type back to real-time
            if hasattr(self, 'client'):
                self.client.reqMarketDataType(1)  # 1 = real-time data
            
            return price
        except Exception as e:
            logger.error(f"Error requesting delayed market data: {e}")
            return None