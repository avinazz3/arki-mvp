# main.py

import logging
import argparse
import json
import os
import time

from ibkr_client import IBKRApp
from portfolio_manager import PortfolioManager

# Set up logging
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
        with open(config_path, 'r') as f:
            config = json.load(f)
        logger.info(f"Loaded configuration from {config_path}")
        return config
    except Exception as e:
        logger.error(f"Error loading configuration: {e}")
        return None

def create_default_config(config_path="config.json"):
    """Create default configuration file"""
    default_config = {
        "ibkr": {
            "host": "127.0.0.1",
            "port": 7497,
            "client_id": 1
        },
        "accounts": {
            "cash_account_id": "DU3915301",
            "investment_account_id": "DU4184147" 
        },
        "cash_management": {
            "min_cash_level": 10000,
            "transfer_threshold": 12000
        },
        "email": {
            "smtp_server": "smtp.gmail.com",
            "smtp_port": 587,
            "sender": "avimcm77@gmail.com",
            "password": "your-app-password",
            "recipient": "denverlitcus@gmail.com"
        }
    }
    
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        with open(config_path, 'w') as f:
            json.dump(default_config, f, indent=4)
        logger.info(f"Created default configuration at {config_path}")
        return default_config
    except Exception as e:
        logger.error(f"Error creating default configuration: {e}")
        return None

def test_connection():
    """Test connection to IBKR"""
    logger.info("Testing connection to IBKR")
    
    # Load configuration
    config = load_config()
    if not config:
        logger.error("Failed to load configuration")
        return False
    
    # Create IBKR client
    ibkr = IBKRApp()
    
    # Connect to IBKR
    ibkr_config = config["ibkr"]
    connected = ibkr.connect_to_ibkr(ibkr_config["host"], ibkr_config["port"], ibkr_config["client_id"])
    
    if not connected:
        logger.error("Failed to connect to IBKR")
        return False
    
    try:
        # Request account information
        accounts = ibkr.accounts
        logger.info(f"Connected to IBKR. Available accounts: {accounts}")
        
        # Request account summary
        account_summary = ibkr.request_account_summary()
        logger.info(f"Account summary: {json.dumps(account_summary, indent=2)}")
        
        return True
    finally:
        # Disconnect from IBKR
        ibkr.disconnect_from_ibkr()

def run_cash_management():
    """Run cash management process"""
    logger.info("Running cash management process")
    
    # Load configuration
    config = load_config()
    if not config:
        logger.error("Failed to load configuration")
        return False
    
    # Create IBKR client
    ibkr = IBKRApp()
    
    # Connect to IBKR
    ibkr_config = config["ibkr"]
    connected = ibkr.connect_to_ibkr(ibkr_config["host"], ibkr_config["port"], ibkr_config["client_id"])
    
    if not connected:
        logger.error("Failed to connect to IBKR")
        return False
    
    try:
        # Create portfolio manager
        portfolio_manager = PortfolioManager(ibkr)
        
        # Run cash management
        result = portfolio_manager.handle_cash_management()
        logger.info(f"Cash management result: {result}")
        
        return result
    finally:
        # Disconnect from IBKR
        ibkr.disconnect_from_ibkr()

def configure():
    """Configure the application interactively"""
    logger.info("Configuring the application")
    
    # Load current configuration or create default
    config = load_config()
    if not config:
        config = create_default_config()
        if not config:
            logger.error("Failed to create default configuration")
            return False
    
    # Display current configuration
    print("\nCurrent Configuration:")
    print("=====================")
    print(f"IBKR Host: {config['ibkr']['host']}")
    print(f"IBKR Port: {config['ibkr']['port']}")
    print(f"IBKR Client ID: {config['ibkr']['client_id']}")
    print(f"Cash Account ID: {config['accounts']['cash_account_id']}")
    print(f"Investment Account ID: {config['accounts']['investment_account_id']}")
    print(f"Min Cash Level: {config['cash_management']['min_cash_level']}")
    print(f"Transfer Threshold: {config['cash_management']['transfer_threshold']}")
    print(f"Email Recipient: {config['email']['recipient']}")
    
    # Allow user to update configuration
    print("\nEnter new values (press Enter to keep current value):")
    
    # IBKR Configuration
    host = input(f"IBKR Host [{config['ibkr']['host']}]: ")
    if host:
        config['ibkr']['host'] = host
    
    port_str = input(f"IBKR Port [{config['ibkr']['port']}]: ")
    if port_str:
        try:
            port = int(port_str)
            config['ibkr']['port'] = port
        except ValueError:
            print("Invalid port number, keeping current value")
    
    client_id_str = input(f"IBKR Client ID [{config['ibkr']['client_id']}]: ")
    if client_id_str:
        try:
            client_id = int(client_id_str)
            config['ibkr']['client_id'] = client_id
        except ValueError:
            print("Invalid client ID, keeping current value")
    
    # Account Configuration
    cash_account = input(f"Cash Account ID [{config['accounts']['cash_account_id']}]: ")
    if cash_account:
        config['accounts']['cash_account_id'] = cash_account
    
    investment_account = input(f"Investment Account ID [{config['accounts']['investment_account_id']}]: ")
    if investment_account:
        config['accounts']['investment_account_id'] = investment_account
    
    # Cash Management Configuration
    min_cash_str = input(f"Min Cash Level [{config['cash_management']['min_cash_level']}]: ")
    if min_cash_str:
        try:
            min_cash = float(min_cash_str)
            config['cash_management']['min_cash_level'] = min_cash
        except ValueError:
            print("Invalid value, keeping current value")
    
    threshold_str = input(f"Transfer Threshold [{config['cash_management']['transfer_threshold']}]: ")
    if threshold_str:
        try:
            threshold = float(threshold_str)
            config['cash_management']['transfer_threshold'] = threshold
        except ValueError:
            print("Invalid value, keeping current value")
    
    # Email Configuration
    recipient = input(f"Email Recipient [{config['email']['recipient']}]: ")
    if recipient:
        config['email']['recipient'] = recipient
    
    smtp_server = input(f"SMTP Server [{config['email']['smtp_server']}]: ")
    if smtp_server:
        config['email']['smtp_server'] = smtp_server
    
    smtp_port_str = input(f"SMTP Port [{config['email']['smtp_port']}]: ")
    if smtp_port_str:
        try:
            smtp_port = int(smtp_port_str)
            config['email']['smtp_port'] = smtp_port
        except ValueError:
            print("Invalid port number, keeping current value")
    
    sender = input(f"Sender Email [{config['email']['sender']}]: ")
    if sender:
        config['email']['sender'] = sender
    
    password = input("Email Password (leave blank to keep current): ")
    if password:
        config['email']['password'] = password
    
    # Save configuration
    try:
        with open("config.json", 'w') as f:
            json.dump(config, f, indent=4)
        logger.info("Configuration saved successfully")
        print("\nConfiguration saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving configuration: {e}")
        print(f"\nError saving configuration: {e}")
        return False

def simulate_transfer():
    """Simulate a cash transfer for testing"""
    logger.info("Simulating cash transfer")
    
    # Load configuration
    config = load_config()
    if not config:
        logger.error("Failed to load configuration")
        return False
    
    # Create IBKR client (not actually used for simulation)
    ibkr = IBKRApp()
    
    # Create portfolio manager
    portfolio_manager = PortfolioManager(ibkr)
    
    # Simulate transfer - not using the API now
    cash_account_id = config["accounts"]["cash_account_id"]
    investment_account_id = config["accounts"]["investment_account_id"]
    amount = 15000  # Simulated transfer amount
    
    success = portfolio_manager.transfer_cash(
        amount=amount,
        from_account=cash_account_id,
        to_account=investment_account_id
    )
    
    if success:
        logger.info(f"Simulated transfer of {amount} successful")
        return {"status": "simulated", "amount": amount}
    else:
        logger.error("Simulated transfer failed")
        return {"status": "error", "message": "Simulated transfer failed"}

def main():
    """Main entry point"""
    # Create logs directory if it doesn't exist
    os.makedirs("logs", exist_ok=True)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="Arki Portfolio Management - Milestone 1")
    parser.add_argument("action", choices=["test", "run", "configure", "simulate"],
                        help="Action to perform: test connection, run cash management, configure, or simulate transfer")
    
    args = parser.parse_args()
    
    # Execute requested action
    if args.action == "test":
        success = test_connection()
        print(f"Connection test {'successful' if success else 'failed'}")
        return success
    elif args.action == "run":
        result = run_cash_management()
        print(f"Cash management result: {result}")
        return result
    elif args.action == "configure":
        return configure()
    elif args.action == "simulate":
        result = simulate_transfer()
        print(f"Simulation result: {result}")
        return result

if __name__ == "__main__":
    main()