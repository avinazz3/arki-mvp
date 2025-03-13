import threading
import time
import logging
import queue
import sys
import json
import os
from datetime import datetime

# Import the InvestmentManager class
from investment_manager import InvestmentManager

# Import the IBKR client directly
from ibkr_client import IBKRApp

# Set up logging once at the top level
os.makedirs("logs", exist_ok=True)  # Ensure logs directory exists
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/main.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def load_config(config_path="config/config.json"):
    """Load configuration from file"""
    try:
        # Make sure config directory exists
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        
        if not os.path.exists(config_path):
            logger.warning(f"Config file not found: {config_path}")
            # Return default configuration
            return {
                "ibkr": {
                    "host": "127.0.0.1",
                    "port": 7497,
                    "client_id": 1
                }
            }
            
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded configuration from {config_path}")
        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        # Return default configuration
        return {
            "ibkr": {
                "host": "127.0.0.1",
                "port": 7497,
                "client_id": 1
            }
        }

class InvestmentDemo:
    def __init__(self, scheduler_interval=30):
        self.scheduler_interval = scheduler_interval
        self.cash_queue = queue.Queue()  # Queue for cash deposits
        self.logger = logger  # Use the root logger
        self.config_path = "config"
        
        # Load configuration
        self.config = load_config()
        
        # Initialize IBKR client
        self.ibkr_client = IBKRApp()
        
        # Try to connect to IBKR
        ibkr_config = self.config.get("ibkr", {
            "host": "127.0.0.1",
            "port": 7497,
            "client_id": 1
        })
        
        try:
            connected = self.ibkr_client.connect_to_ibkr(
                ibkr_config["host"], 
                ibkr_config["port"], 
                ibkr_config["client_id"]
            )
            if not connected:
                self.logger.warning("Could not connect to IBKR. Some functionality may be limited.")
                raise Exception("Failed to connect to IBKR TWS. Please make sure TWS is running.")
            else:
                self.logger.info("Successfully connected to IBKR TWS!")
        except Exception as e:
            self.logger.error(f"Error connecting to IBKR: {e}")
            raise
        
        # Initialize default portfolio with default values
        self.default_portfolio = {
            'growth': {
                'AAPL': {'target_percentage': 0.3, 'instrument_type': 'STK', 'exchange': 'SMART'},
                'MSFT': {'target_percentage': 0.3, 'instrument_type': 'STK', 'exchange': 'SMART'},
                'AMZN': {'target_percentage': 0.4, 'instrument_type': 'STK', 'exchange': 'SMART'}
            },
            'income': {
                'JNJ': {'target_percentage': 0.5, 'instrument_type': 'STK', 'exchange': 'SMART'},
                'PG': {'target_percentage': 0.5, 'instrument_type': 'STK', 'exchange': 'SMART'}
            }
        }
        
        # Get investment account ID from config
        self.investment_account_id = self.config.get("accounts", {}).get("investment_account_id")
        if not self.investment_account_id:
            self.logger.warning("Investment account ID not found in config, using default: DU4184147")
            self.investment_account_id = "DU4184147"
        
        self.logger.info(f"Using investment account ID: {self.investment_account_id}")
        
        # Initialize investment manager with direct access to IBKR client
        self.investment_manager = InvestmentManager(self.ibkr_client)
        
        # Set the investment account ID
        self.investment_manager.investment_account_id = self.investment_account_id
        
        # Load portfolio allocations
        try:
            portfolio_file = os.path.join(self.config_path, 'portfolio_allocation.csv')
            if os.path.exists(portfolio_file):
                self.investment_manager.load_portfolio_allocations(portfolio_file)
            else:
                self.logger.warning(f"Portfolio allocation file not found: {portfolio_file}")
                self.investment_manager.investment_portfolio = self.default_portfolio
        except Exception as e:
            self.logger.error(f"Error loading portfolio allocations: {e}")
            self.investment_manager.investment_portfolio = self.default_portfolio
        
        # Load account info
        try:
            self.investment_manager.load_account_info()
        except Exception as e:
            self.logger.error(f"Error loading investment account info: {e}")
        
        # Initialize scheduler thread flag
        self.running = False
    
    def start_cli(self):
        """Start the CLI interface in a separate thread"""
        cli_thread = threading.Thread(target=self._cli_loop)
        cli_thread.daemon = True
        cli_thread.start()
    
    def _cli_loop(self):
        """CLI interface to accept user commands"""
        print("\nInvestment Demo CLI")
        print("-------------------")
        print("Commands:")
        print("  deposit <amount> - Simulate a cash deposit")
        print("  balance - Show current account balance")
        print("  exit - Exit the program")
        
        while True:
            try:
                command = input("\nEnter command: ").strip()
                
                if command.lower() == "exit":
                    self.stop()
                    break
                
                if command.lower() == "balance":
                    try:
                        if not self.investment_manager.investment_account:
                            self.investment_manager.load_account_info()
                        
                        account_info = self.investment_manager.investment_account['data']['account_info']
                        balance = account_info.get('AvailableFunds_SGD', 'Unknown')
                        total_value = account_info.get('NetLiquidation_SGD', 'Unknown')
                        print(f"Available Funds: {balance} SGD")
                        print(f"Total Portfolio Value: {total_value} SGD")
                    except Exception as e:
                        print(f"Error retrieving balance: {e}")
                    continue
                
                parts = command.split()
                if len(parts) == 2 and parts[0].lower() == "deposit":
                    try:
                        amount = float(parts[1])
                        self.cash_queue.put(amount)
                        print(f"Queued cash deposit of {amount} for investment")
                    except ValueError:
                        print("Invalid amount. Please enter a number.")
                else:
                    print("Unknown command. Available commands: deposit <amount>, balance, exit")
            except KeyboardInterrupt:
                self.stop()
                break
    
    def start_scheduler(self):
        """Start the scheduler thread"""
        self.running = True
        scheduler_thread = threading.Thread(target=self._scheduler_loop)
        scheduler_thread.daemon = True
        scheduler_thread.start()
        return scheduler_thread
    
    def _scheduler_loop(self):
        """Main scheduler loop that runs at regular intervals"""
        self.logger.info(f"Starting scheduler with {self.scheduler_interval}s interval")
        
        while self.running:
            try:
                self.logger.info(f"Scheduler tick at {datetime.now()}")
                
                # Process any pending cash deposits
                self._process_cash_deposits()
                
                # Rebalance portfolio if needed
                # Uncomment to enable automatic rebalancing
                # self.investment_manager.rebalance_portfolio()
                
                # Wait for next interval
                time.sleep(self.scheduler_interval)
            except Exception as e:
                self.logger.error(f"Error in scheduler: {e}")
    
    def _process_cash_deposits(self):
        """Process any pending cash deposits in the queue"""
        if self.cash_queue.empty():
            return
        
        # Get all deposits in queue
        total_deposit = 0
        while not self.cash_queue.empty():
            try:
                amount = self.cash_queue.get_nowait()
                total_deposit += amount
            except queue.Empty:
                break
        
        if total_deposit > 0:
            self.logger.info(f"Processing cash deposit of {total_deposit}")
            
            try:
                # For a real demo, we should refresh account data to get the latest position
                # information before making trades
                self.logger.info("Refreshing account information before processing deposit...")
                try:
                    self.investment_manager.load_account_info()
                    self.logger.info("Account information refreshed successfully")
                except Exception as e:
                    self.logger.error(f"Error refreshing account information: {e}")
                
                # Ensure investment_account structure exists
                if not self.investment_manager.investment_account:
                    self.logger.warning("Investment account not initialized. Creating dummy data.")
                    self.investment_manager.investment_account = {
                        'id': self.investment_account_id,
                        'data': {'account_info': {'AvailableFunds_SGD': '0.0', 'NetLiquidation_SGD': '0.0'}},
                        'positions': {}
                    }
                
                # Update account cash balance with the deposit
                self.investment_manager.receive_cash_transfer(total_deposit)
                
                self.logger.info(f"Processing deposit of {total_deposit} to account {self.investment_account_id}")
                
                # Get updated balance for logging
                account_info = self.investment_manager.investment_account['data']['account_info']
                self.logger.info(f"New available funds: {account_info.get('AvailableFunds_SGD', 'Unknown')} SGD")
                
                # Invest the excess cash
                print(f"Investing {total_deposit} SGD according to portfolio allocation...")
                result = self.investment_manager.handle_excess_cash_investment(total_deposit)
                
                # Print a more user-friendly summary of the investment result
                if 'orders' in result and result['orders']:
                    print("\nTrades executed:")
                    for i, order in enumerate(result['orders']):
                        print(f"{i+1}. {order['action']} {order['quantity']} {order['contract'].symbol} on {order['contract'].exchange}")
                
                    print("\nThese trades should now be visible in your TWS.")
                else:
                    print("No trades were executed.")
                
                self.logger.info(f"Investment result: {result}")
            except Exception as e:
                self.logger.error(f"Error processing deposit: {e}")
    
    def stop(self):
        """Stop the demo"""
        self.logger.info("Stopping investment demo")
        self.running = False


def main():
    try:
        # Create and start the demo with a 10-second scheduler interval for demo purposes
        demo = InvestmentDemo(scheduler_interval=10)
        
        # Start the CLI interface
        demo.start_cli()
        
        # Start the scheduler
        scheduler_thread = demo.start_scheduler()
        
        # Keep the main thread running
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        print(f"\nFatal error: {e}")
    finally:
        print("\nShutting down...")
        if 'demo' in locals():
            demo.stop()
            
            # Wait for the scheduler to stop
            if 'scheduler_thread' in locals() and scheduler_thread.is_alive():
                scheduler_thread.join(timeout=2)
            
            # Disconnect from IBKR
            if hasattr(demo.ibkr_client, 'disconnect_from_ibkr'):
                try:
                    demo.ibkr_client.disconnect_from_ibkr()
                except Exception as e:
                    logger.error(f"Error disconnecting from IBKR: {e}")
        
        print("Goodbye!")


if __name__ == "__main__":
    main()