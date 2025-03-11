import os
import logging
import pandas as pd
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
from ibkr_client import IBKRApp
import base64
import os.path
from email.mime.text import MIMEText
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("portfolio_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PortfolioManager:
    """
    Portfolio Manager class for handling the portfolio allocation logic
    """
    
    def __init__(self, ibkr_client, config_path="config"):
        """
        Initialize the portfolio manager
        
        Args:
            ibkr_client: The IBKR client instance
            config_path: Path to configuration files
        """
        self.ibkr = ibkr_client
        self.config_path = config_path
        
        # Ensure config directory exists
        os.makedirs(self.config_path, exist_ok=True)
        
        # Load configuration
        self.config = self._load_config()
        
        # Initialize portfolio states
        self.cash_account = None
        self.investment_account = None
        self.dummy_account = None
        
        # Portfolio allocation data
        self.cash_portfolio = None
        self.investment_portfolio = None
        
    def _load_config(self):
        """Load configuration from file"""
        config_path = os.path.join(self.config_path, 'config.json')
        logger.info(f"Attempting to load configuration from: {config_path}")
        
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded configuration from {config_path}")
            
            # Add portfolio file and log directory paths
            config['portfolio_file'] = os.path.join(self.config_path, 'portfolio_allocation.csv')
            config['log_dir'] = os.path.join(self.config_path, 'logs')
            
            # Ensure log directory exists
            os.makedirs(config['log_dir'], exist_ok=True)
            
            return config
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            return None
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON in configuration file: {config_path}")
            return None
        except Exception as e:
            logger.error(f"Error loading configuration: {e}")
            return None
    
    def load_account_info(self):
        """Load account information from IBKR"""
        logger.info("Loading account information from IBKR")
        
        # Request account summary
        account_summary = self.ibkr.request_account_summary()
        logger.info(f"Received account summary for {len(account_summary)} accounts")
        
        # Request positions for all accounts
        positions = self.ibkr.request_positions()
        logger.info(f"Received positions for {len(positions)} accounts")
        
        # Store account info
        self.cash_account = {
            'id': self.config['cash_account_id'],
            'summary': account_summary.get(self.config['cash_account_id'], {}),
            'positions': positions.get(self.config['cash_account_id'], {})
        }
        
        self.investment_account = {
            'id': self.config['investment_account_id'],
            'summary': account_summary.get(self.config['investment_account_id'], {}),
            'positions': positions.get(self.config['investment_account_id'], {})
        }
        
        self.dummy_account = {
            'id': self.config['dummy_account_id'],
            'summary': account_summary.get(self.config['dummy_account_id'], {}),
            'positions': positions.get(self.config['dummy_account_id'], {})
        }
        
        # Load detailed account data
        self.cash_account['data'] = self.ibkr.request_account_updates(self.config['cash_account_id'])
        self.investment_account['data'] = self.ibkr.request_account_updates(self.config['investment_account_id'])
        
        return {
            'cash_account': self.cash_account,
            'investment_account': self.investment_account,
            'dummy_account': self.dummy_account
        }
    
    def load_portfolio_allocations(self):
        """Load portfolio allocation from CSV file"""
        try:
            if os.path.exists(self.config['portfolio_file']):
                df = pd.read_csv(self.config['portfolio_file'])
                
                # Filter for cash portfolio
                cash_df = df[df['account_type'] == 'cash']
                self.cash_portfolio = cash_df.set_index('instrument')['target_percentage'].to_dict()
                
                # Filter for investment portfolio
                investment_df = df[df['account_type'] == 'investment']
                # Create hierarchical structure by strategy
                investment_strategies = {}
                for _, row in investment_df.iterrows():
                    strategy = row['strategy']
                    instrument = row['instrument']
                    
                    if strategy not in investment_strategies:
                        investment_strategies[strategy] = {}
                    
                    investment_strategies[strategy][instrument] = {
                        'target_percentage': row['target_percentage'],
                        'instrument_type': row['instrument_type'],
                        'exchange': row['exchange']
                    }
                
                self.investment_portfolio = investment_strategies
                
                logger.info(f"Loaded portfolio allocations: {len(self.cash_portfolio)} cash instruments, "
                           f"{len(self.investment_portfolio)} investment strategies")
                return True
            else:
                logger.error(f"Portfolio allocation file not found: {self.config['portfolio_file']}")
                return False
        except Exception as e:
            logger.error(f"Error loading portfolio allocations: {e}", exc_info=True)
            return False
    
    def check_cash_level(self):
        """Check cash level in cash account and determine if transfer is needed"""
        logger.info("Checking cash level in cash account")
        
        if not self.cash_account or 'summary' not in self.cash_account:
            logger.error("Cash account information not loaded")
            return {'error': 'Cash account information not loaded'}
        
        # Get cash balance from account summary
        account_summary = self.cash_account['summary']
        
        # Look for TotalCashValue or AvailableFunds in SGD
        cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'TotalCashValue', 'AvailableFunds']
        
        cash_balance = None
        for key in cash_keys:
            if key in account_summary:
                cash_balance = float(account_summary[key])
                logger.info(f"Found cash balance using {key}: {cash_balance}")
                break
                
        if cash_balance is None:
            logger.error(f"Cash balance not found in account summary: {account_summary.keys()}")
            return {'error': 'Cash balance not found'}
        
        # Calculate excess cash
        min_cash_level = self.config['min_cash_level']
        transfer_threshold = self.config['transfer_threshold']
        
        excess_cash = max(0, cash_balance - min_cash_level)
        should_transfer = excess_cash >= (transfer_threshold - min_cash_level)
        
        result = {
            'account_id': self.cash_account['id'],
            'cash_balance': cash_balance,
            'min_cash_level': min_cash_level,
            'excess_cash': excess_cash,
            'transfer_threshold': transfer_threshold,
            'should_transfer': should_transfer
        }
        
        logger.info(f"Cash level check result: {result}")
        return result
    
    def transfer_cash(self, amount, from_account, to_account):
        """
        Transfer cash between accounts
        
        Args:
            amount: Amount to transfer
            from_account: Source account ID
            to_account: Destination account ID
            
        Returns:
            bool: Success or failure
        """
        logger.info(f"Transferring {amount} from {from_account} to {to_account}")
        
        # In real implementation, this would use IBKR API to initiate transfer
        # For demonstration, we'll just log the transfer
        
        # Record transfer details
        transfer_data = {
            'timestamp': datetime.now().isoformat(),
            'from_account': from_account,
            'to_account': to_account,
            'amount': amount
        }
        
        # Save transfer log
        if not self.config:
            logger.error("Configuration not loaded")
            return False
        
        transfer_log_path = os.path.join(self.config['log_dir'], 'transfers.csv')
        df = pd.DataFrame([transfer_data])
        
        if os.path.exists(transfer_log_path):
            df.to_csv(transfer_log_path, mode='a', header=False, index=False)
        else:
            df.to_csv(transfer_log_path, index=False)
        
        # Send notification email
        self.notify_transfer(transfer_data)
        
        return True
    
    def notify_transfer(self, transfer_data):
        """
        Send email notification about cash transfer using Gmail API
        
        Args:
            transfer_data: Transfer details
        """
        logger.info("Sending transfer notification email via Gmail API")
        
        try:
            email_config = self.config['email']
            recipient_email = email_config.get('recipient_email')
            
            if not recipient_email:
                logger.warning("Recipient email not configured. Notification not sent.")
                return False
            
            # Set up Gmail API credentials
            creds = None
            # The file token.json stores the user's access and refresh tokens
            if os.path.exists("token.json"):
                creds = Credentials.from_authorized_user_file("token.json", 
                                                            ["https://www.googleapis.com/auth/gmail.send"])
            
            # If there are no (valid) credentials available, let the user log in
            if not creds or not creds.valid:
                if creds and creds.expired and creds.refresh_token:
                    creds.refresh(Request())
                else:
                    flow = InstalledAppFlow.from_client_secrets_file(
                        "credentials.json", ["https://www.googleapis.com/auth/gmail.send"]
                    )
                    creds = flow.run_local_server(port=0)
                # Save the credentials for the next run
                with open("token.json", "w") as token:
                    token.write(creds.to_json())
            
            # Create email message
            message = MIMEMultipart()
            message['to'] = recipient_email
            message['subject'] = f"Cash Transfer Notification - {transfer_data['amount']} SGD"
            
            # Create email body
            body = f"""
            <html>
            <body>
                <h3>Cash Transfer Notification</h3>
                <p>A cash transfer has been executed between accounts:</p>
                <table border="1">
                    <tr><th>Item</th><th>Details</th></tr>
                    <tr><td>Date/Time</td><td>{transfer_data['timestamp']}</td></tr>
                    <tr><td>From Account</td><td>{transfer_data['from_account']}</td></tr>
                    <tr><td>To Account</td><td>{transfer_data['to_account']}</td></tr>
                    <tr><td>Amount</td><td>{transfer_data['amount']} SGD</td></tr>
                </table>
                <p>This is an automated notification from the portfolio management system.</p>
            </body>
            </html>
            """
            
            message.attach(MIMEText(body, 'html'))
            
            # Encode the message
            encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
            
            # Create the Gmail API service
            service = build('gmail', 'v1', credentials=creds)
            
            # Send the message
            send_message = service.users().messages().send(
                userId="me", 
                body={'raw': encoded_message}
            ).execute()
            
            logger.info(f"Transfer notification email sent via Gmail API. Message ID: {send_message['id']}")
            return True
        
        except HttpError as error:
            logger.error(f"Gmail API error: {error}")
            return False
        except Exception as e:
            logger.error(f"Error sending notification email: {e}", exc_info=True)
            return False
    def allocate_excess_cash(self):
        """
        Allocate excess cash in cash account according to cash portfolio percentages
        
        Returns:
            dict: Allocation results
        """
        logger.info("Allocating excess cash in cash account")
        
        # Check cash level
        cash_info = self.check_cash_level()
        
        if 'error' in cash_info:
            return cash_info
        
        if not cash_info['excess_cash'] > 0:
            logger.info("No excess cash to allocate")
            return {'status': 'No excess cash to allocate'}
        
        # If cash portfolio is not loaded, try to load it
        if not self.cash_portfolio:
            self.load_portfolio_allocations()
            
        if not self.cash_portfolio:
            logger.error("Cash portfolio allocation not available")
            return {'error': 'Cash portfolio allocation not available'}
        
        # Calculate allocation amounts
        excess_cash = cash_info['excess_cash']
        allocation = {}
        
        for instrument, percentage in self.cash_portfolio.items():
            allocation[instrument] = excess_cash * percentage
            
        logger.info(f"Cash allocation plan: {allocation}")
        
        # In a real implementation, this would place orders via IBKR API
        # For demonstration, just log the allocation
        
        return {
            'status': 'Allocation plan created',
            'excess_cash': excess_cash,
            'allocation': allocation,
            'should_transfer': cash_info['should_transfer']
        }
    
    def handle_cash_management(self):
        """
        Main function for cash management (Milestone 1)
        
        This function:
        1. Checks cash level
        2. Allocates excess cash within cash account
        3. Transfers cash to investment account if threshold is reached
        """
        logger.info("Starting cash management process")
        
        # Load account info if not already loaded
        if not self.cash_account or not self.investment_account:
            self.load_account_info()
        
        # Check cash level and get allocation plan
        allocation_result = self.allocate_excess_cash()
        
        if 'error' in allocation_result:
            logger.error(f"Error in cash management: {allocation_result['error']}")
            return allocation_result
        
        # If threshold for transfer is reached, transfer cash to investment account
        if allocation_result.get('should_transfer', False):
            excess_cash = allocation_result['excess_cash']
            
            # Transfer cash
            transfer_success = self.transfer_cash(
                amount=excess_cash,
                from_account=self.cash_account['id'],
                to_account=self.investment_account['id']
            )
            
            if transfer_success:
                logger.info(f"Successfully transferred {excess_cash} to investment account")
                return {
                    'status': 'Cash transferred to investment account',
                    'amount': excess_cash,
                    'from_account': self.cash_account['id'],
                    'to_account': self.investment_account['id']
                }
            else:
                logger.error("Failed to transfer cash")
                return {'error': 'Failed to transfer cash'}
        else:
            # If threshold not reached, just maintain cash allocation
            logger.info("Cash threshold for transfer not reached. Maintaining allocation within cash account.")
            return {
                'status': 'Maintaining cash allocation',
                'allocation': allocation_result.get('allocation', {})
            }


# Example usage
if __name__ == "__main__":
    # Create IBKR client
    ibkr_app = IBKRApp(host="127.0.0.1", port=7497, client_id=1)
    
    try:
        # Connect to IBKR
        if ibkr_app.connect():
            # Create portfolio manager
            manager = PortfolioManager(ibkr_app)
            
            # Load account information
            accounts = manager.load_account_info()
            logger.info(f"Loaded account info: {accounts.keys()}")
            
            # Load portfolio allocations
            manager.load_portfolio_allocations()
            
            # Handle cash management
            result = manager.handle_cash_management()
            logger.info(f"Cash management result: {result}")
            
    except Exception as e:
        logger.error(f"Error in portfolio management: {e}", exc_info=True)
    finally:
        # Disconnect from IBKR
        ibkr_app.disconnect()