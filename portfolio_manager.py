import os
import json
import logging
import pandas as pd
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import base64
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import resend

VERIFIED_EMAIL = "avimcm77@gmail.com"

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

# Email helper functions
def create_message(sender, to, subject, message_text):
    """
    Create a message for an email.
    
    Args:
        sender: Email address of the sender
        to: Email address of the recipient
        subject: Subject of the email
        message_text: HTML content of the email
        
    Returns:
        Dictionary containing the raw message
    """
    message = MIMEText(message_text, 'html')
    message['to'] = to
    message['from'] = sender
    message['subject'] = subject
    return {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}

def send_message(service, user_id, message):
    """
    Send an email message.
    
    Args:
        service: Gmail API service instance
        user_id: User's email address or 'me'
        message: Message to be sent
        
    Returns:
        Sent message object
    """
    try:
        message = (service.users().messages().send(userId=user_id, body=message)
                   .execute())
        logger.info(f'Message Id: {message["id"]}')
        return message
    except HttpError as error:
        logger.error(f'An error occurred while sending email: {error}')
        raise

class PortfolioManager:
    """
    Portfolio Manager class for handling the simulated cash account only
    """
    
    def __init__(self, config_path="config"):
        """
        Initialize the portfolio manager
        
        Args:
            config_path: Path to configuration files
        """
        # No IBKR client dependency
        self.config_path = config_path
        
        # Ensure config directory exists
        os.makedirs(self.config_path, exist_ok=True)
        
        # Initialize portfolio states
        self.cash_account = None
        self.investment_account = None  # Used only for reference
        
        # Portfolio allocation data
        self.cash_portfolio = None
        self.investment_portfolio = None
        
        # Load configuration
        self.config = self._load_config()
        
        # Initialize simulated cash account if needed
        self._initialize_simulated_cash_account()
        
        # Check for required dependencies
        self._check_dependencies()

    def _check_dependencies(self):
        """Check for required dependencies based on configuration"""
        email_config = self.config.get('email', {})
        email_service = email_config.get('email_service', 'smtp').lower()
        
        if email_service == 'resend':
            try:
                import resend
                logger.info("Resend library is available")
            except ImportError:
                logger.warning(
                    "Resend library is not installed but configured as email service. "
                    "Install it with 'pip install resend' or email notifications will fail."
                )
        
    def _load_config(self):
        """Load configuration from file"""
        # First try to load client_portal_config.json
        portal_config_path = os.path.join(self.config_path, 'client_portal_config.json')
        
        try:
            if os.path.exists(portal_config_path):
                with open(portal_config_path, 'r') as f:
                    config = json.load(f)
                logger.info(f"Loaded configuration from {portal_config_path}")
                
                # Set default values if not present
                if 'accounts' not in config:
                    config['accounts'] = {}
                
                # Extract relevant account info and set defaults
                config['cash_account_id'] = config['accounts'].get('cash_account_id', 'DU12345')
                config['investment_account_id'] = config['accounts'].get('investment_account_id', 'DU3915301')
                
                # Get cash management settings
                cash_management = config.get('cash_management', {})
                config['min_cash_level'] = cash_management.get('min_cash_level', 10000.0)
                config['transfer_threshold'] = cash_management.get('transfer_threshold', 5000.0)
                config['allocation_tolerance'] = cash_management.get('allocation_tolerance', 0.02)
                
                # Add portfolio file and log directory paths
                config['portfolio_file'] = os.path.join(self.config_path, 'portfolio_allocation.csv')
                config['simulated_cash_file'] = os.path.join(self.config_path, 'simulated_cash_account.json')
                config['log_dir'] = os.path.join(self.config_path, 'logs')
                
                # Make sure email config exists with defaults
                if 'email' not in config:
                    config['email'] = {
                        'recipient_email': 'example@example.com',
                        'email_service': 'resend',
                        'resend_api_key': os.environ.get('RESEND_API_KEY', ''),
                        'resend_from_email': 'transfers@yourdomain.com'
                    }
                
                # Ensure log directory exists
                os.makedirs(config['log_dir'], exist_ok=True)
                
                return config
            
            # If no config file exists, create default config
            logger.warning("No configuration file found. Creating default configuration.")
            default_config = {
                'cash_account_id': 'DU12345',
                'investment_account_id': 'DU4184147',
                'min_cash_level': 10000.0,
                'transfer_threshold': 5000.0,
                'allocation_tolerance': 0.02,
                'portfolio_file': os.path.join(self.config_path, 'portfolio_allocation.csv'),
                'simulated_cash_file': os.path.join(self.config_path, 'simulated_cash_account.json'),
                'log_dir': os.path.join(self.config_path, 'logs'),
                'email': {
                    'recipient_email': 'example@example.com',
                    'email_service': 'resend',
                    'resend_api_key': os.environ.get('RESEND_API_KEY', ''),
                    'resend_from_email': 'transfers@yourdomain.com'
                }
            }
            
            # Save default config
            os.makedirs(os.path.dirname(portal_config_path), exist_ok=True)
            with open(portal_config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            
            # Ensure log directory exists
            os.makedirs(default_config['log_dir'], exist_ok=True)
            
            return default_config
            
        except Exception as e:
            logger.error(f"Error loading configuration: {e}", exc_info=True)
            # Return minimal default config
            return {
                'cash_account_id': 'DU12345',
                'investment_account_id': 'DU4184147',
                'min_cash_level': 10000.0,
                'transfer_threshold': 5000.0,
                'allocation_tolerance': 0.02,
                'portfolio_file': os.path.join(self.config_path, 'portfolio_allocation.csv'),
                'simulated_cash_file': os.path.join(self.config_path, 'simulated_cash_account.json'),
                'log_dir': os.path.join(self.config_path, 'logs'),
                'email': {
                    'recipient_email': 'example@example.com',
                    'email_service': 'resend',
                    'resend_api_key': os.environ.get('RESEND_API_KEY', ''),
                    'resend_from_email': 'transfers@yourdomain.com'
                }
            }
    
    def _initialize_simulated_cash_account(self):
        """Initialize simulated cash account if it doesn't exist"""
        if not self.config:
            logger.error("Configuration not loaded. Cannot initialize simulated cash account.")
            return
        
        simulated_cash_file = self.config.get('simulated_cash_file')
        if not simulated_cash_file:
            logger.error("Simulated cash file path not defined in config.")
            return
        
        # Check if simulated cash account file exists
        if not os.path.exists(simulated_cash_file):
            # Create default simulated cash account
            default_cash_account = {
                'id': self.config['cash_account_id'],
                'summary': {
                    'NetLiquidation_SGD': '50000',
                    'TotalCashValue_SGD': '50000',
                    'AvailableFunds_SGD': '50000'
                },
                'positions': {},
                'data': {
                    'account_info': {
                        'NetLiquidation_SGD': '50000',
                        'TotalCashValue_SGD': '50000',
                        'AvailableFunds_SGD': '50000',
                        'GrossPositionValue_SGD': '0'
                    }
                },
                'transactions': [],
                'last_updated': datetime.now().isoformat()
            }
            
            # Save to file
            os.makedirs(os.path.dirname(simulated_cash_file), exist_ok=True)
            with open(simulated_cash_file, 'w') as f:
                json.dump(default_cash_account, f, indent=4)
            
            logger.info(f"Created simulated cash account file at {simulated_cash_file}")
    
    def _load_simulated_cash_account(self):
        """Load simulated cash account from file"""
        simulated_cash_file = self.config.get('simulated_cash_file')
        if not simulated_cash_file or not os.path.exists(simulated_cash_file):
            logger.error("Simulated cash account file not found.")
            return None
        
        try:
            with open(simulated_cash_file, 'r') as f:
                cash_account = json.load(f)
            logger.info(f"Loaded simulated cash account from {simulated_cash_file}")
            return cash_account
        except Exception as e:
            logger.error(f"Error loading simulated cash account: {e}", exc_info=True)
            return None
    
    def _save_simulated_cash_account(self, cash_account):
        """Save simulated cash account to file"""
        simulated_cash_file = self.config.get('simulated_cash_file')
        if not simulated_cash_file:
            logger.error("Simulated cash file path not defined in config.")
            return False
        
        try:
            # Update last updated timestamp
            cash_account['last_updated'] = datetime.now().isoformat()
            
            # Save to file
            with open(simulated_cash_file, 'w') as f:
                json.dump(cash_account, f, indent=4)
            
            logger.info(f"Saved simulated cash account to {simulated_cash_file}")
            return True
        except Exception as e:
            logger.error(f"Error saving simulated cash account: {e}", exc_info=True)
            return False
    
    def load_account_info(self):
        """Load simulated cash account information"""
        logger.info("Loading simulated cash account information")
        
        # Load simulated cash account
        self.cash_account = self._load_simulated_cash_account()
        if not self.cash_account:
            # If loading failed, initialize and try again
            self._initialize_simulated_cash_account()
            self.cash_account = self._load_simulated_cash_account()
        
        # Create minimal investment account reference (without data)
        self.investment_account = {
            'id': self.config['investment_account_id'],
            'description': 'Investment account managed separately by InvestmentManager'
        }
        
        return {
            'cash_account': self.cash_account,
            'investment_account': self.investment_account
        }
    
    def simulate_cash_deposit(self, amount):
        """Simulate a cash deposit into the cash account"""
        logger.info(f"Simulating cash deposit of {amount} into cash account")
        
        if not self.cash_account:
            self.cash_account = self._load_simulated_cash_account()
            if not self.cash_account:
                logger.error("Failed to load simulated cash account.")
                return False
        
        # Update cash balances
        current_cash = float(self.cash_account['data']['account_info']['TotalCashValue_SGD'])
        new_cash = current_cash + amount
        
        self.cash_account['summary']['TotalCashValue_SGD'] = str(new_cash)
        self.cash_account['summary']['AvailableFunds_SGD'] = str(new_cash)
        self.cash_account['summary']['NetLiquidation_SGD'] = str(new_cash)
        
        self.cash_account['data']['account_info']['TotalCashValue_SGD'] = str(new_cash)
        self.cash_account['data']['account_info']['AvailableFunds_SGD'] = str(new_cash)
        self.cash_account['data']['account_info']['NetLiquidation_SGD'] = str(new_cash)
        
        # Record transaction
        transaction = {
            'timestamp': datetime.now().isoformat(),
            'type': 'deposit',
            'amount': amount,
            'balance_after': new_cash
        }
        
        if 'transactions' not in self.cash_account:
            self.cash_account['transactions'] = []
        
        self.cash_account['transactions'].append(transaction)
        
        # Save updated account
        success = self._save_simulated_cash_account(self.cash_account)
        
        return success
    
    def load_portfolio_allocations(self):
        """Load portfolio allocation from CSV file"""
        try:
            if os.path.exists(self.config['portfolio_file']):
                df = pd.read_csv(self.config['portfolio_file'])
                
                # Filter for cash portfolio
                cash_df = df[df['account_type'] == 'cash']
                self.cash_portfolio = cash_df.set_index('instrument')['target_percentage'].to_dict()
                
                # Filter for investment portfolio (for reference only)
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
        
        if not self.cash_account or 'data' not in self.cash_account or 'account_info' not in self.cash_account['data']:
            logger.error("Cash account information not loaded")
            return {'error': 'Cash account information not loaded'}
        
        # Get cash balance from account info
        account_info = self.cash_account['data']['account_info']
        
        # Look for TotalCashValue or AvailableFunds in SGD
        cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'TotalCashValue', 'AvailableFunds']
        
        cash_balance = None
        for key in cash_keys:
            if key in account_info:
                cash_balance = float(account_info[key])
                logger.info(f"Found cash balance using {key}: {cash_balance}")
                break
                
        if cash_balance is None:
            logger.error(f"Cash balance not found in account info: {account_info.keys()}")
            return {'error': 'Cash balance not found'}
        
        # Calculate excess cash
        min_cash_level = self.config['min_cash_level']
        transfer_threshold = self.config['transfer_threshold']
        
        excess_cash = max(0, cash_balance - min_cash_level)
        should_transfer = excess_cash >= transfer_threshold
        
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
        Transfer cash from simulated cash account
        
        Args:
            amount: Amount to transfer
            from_account: Source account ID (must be cash account)
            to_account: Destination account ID
            
        Returns:
            bool: Success or failure
        """
        logger.info(f"Transferring {amount} from {from_account} to {to_account}")
        
        # Only handle transfers from the simulated cash account
        if from_account != self.config['cash_account_id']:
            logger.error(f"Invalid source account: {from_account}. This manager only handles the simulated cash account.")
            return False
        
        # Load cash account if not loaded
        if not self.cash_account:
            self.cash_account = self._load_simulated_cash_account()
            if not self.cash_account:
                logger.error("Failed to load simulated cash account.")
                return False
        
        # Check if sufficient funds
        current_cash = float(self.cash_account['data']['account_info']['TotalCashValue_SGD'])
        if current_cash < amount:
            logger.error(f"Insufficient funds in cash account. Available: {current_cash}, Requested: {amount}")
            return False
        
        # Update cash account
        new_cash = current_cash - amount
        
        self.cash_account['summary']['TotalCashValue_SGD'] = str(new_cash)
        self.cash_account['summary']['AvailableFunds_SGD'] = str(new_cash)
        self.cash_account['summary']['NetLiquidation_SGD'] = str(new_cash)
        
        self.cash_account['data']['account_info']['TotalCashValue_SGD'] = str(new_cash)
        self.cash_account['data']['account_info']['AvailableFunds_SGD'] = str(new_cash)
        self.cash_account['data']['account_info']['NetLiquidation_SGD'] = str(new_cash)
        
        # Record transaction
        transaction = {
            'timestamp': datetime.now().isoformat(),
            'type': 'transfer_out',
            'amount': amount,
            'destination_account': to_account,
            'balance_after': new_cash
        }
        
        if 'transactions' not in self.cash_account:
            self.cash_account['transactions'] = []
        
        self.cash_account['transactions'].append(transaction)
        
        # Save updated account
        success = self._save_simulated_cash_account(self.cash_account)
        
        if not success:
            logger.error("Failed to save cash account after transfer.")
            return False
        
        # Record transfer details for notification and logging
        transfer_data = {
            'timestamp': datetime.now().isoformat(),
            'from_account': from_account,
            'to_account': to_account,
            'amount': amount
        }
        
        # Save transfer log
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
        Send email notification about cash transfer using Resend
        
        Args:
            transfer_data: Transfer details
        """
        try:
            import resend
            
            # Get email configuration
            email_config = self.config['email']
            original_recipient = email_config.get('recipient_email')
            
            if not original_recipient:
                logger.warning("Recipient email not configured. Notification not sent.")
                return False
            
            # In testing mode with onboarding@resend.dev, we can only send to the owner's email
            from_email = email_config.get('resend_from_email', 'onboarding@resend.dev')
            testing_mode = from_email == 'onboarding@resend.dev'
            
            # If in testing mode, force the recipient to be your own email
            recipient_email = VERIFIED_EMAIL if testing_mode else original_recipient
            
            # Resend API key
            resend_api_key = "re_2vznwWbq_E7LuhmuQgw3t2Sqfp3Y9u92Q"
            
            # Set API key
            resend.api_key = resend_api_key
            
            # Create email subject
            subject = f"Cash Transfer Notification - {transfer_data['amount']} SGD"
            
            # Create HTML content
            html_content = f"""
            <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px; border: 1px solid #e0e0e0; border-radius: 5px;">
                    <h2 style="color: #333366;">Cash Transfer Notification</h2>
                    <p>A cash transfer has been executed between accounts:</p>
                    <table style="width: 100%; border-collapse: collapse; margin: 20px 0;">
                        <tr style="background-color: #f2f2f2;">
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Item</th>
                            <th style="padding: 10px; border: 1px solid #ddd; text-align: left;">Details</th>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">Date/Time</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{transfer_data['timestamp']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">From Account</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{transfer_data['from_account']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">To Account</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{transfer_data['to_account']}</td>
                        </tr>
                        <tr>
                            <td style="padding: 10px; border: 1px solid #ddd;">Amount</td>
                            <td style="padding: 10px; border: 1px solid #ddd;">{transfer_data['amount']} SGD</td>
                        </tr>
                    </table>
                    <p style="color: #666;">This is an automated notification from the portfolio management system.</p>
                    
                    {f"<p><em>Note: This email was sent to you as the verified account owner. The intended recipient was {original_recipient}.</em></p>" if testing_mode and original_recipient != recipient_email else ""}
                </div>
            </body>
            </html>
            """
            
            # Log sending attempt
            logger.info(f"Sending transfer notification email via Resend from {from_email} to {recipient_email}")
            
            if testing_mode and original_recipient != recipient_email:
                logger.info(f"In testing mode: redirecting email from {original_recipient} to {recipient_email}")
            
            # Prepare email parameters
            email_params = {
                "from": from_email,
                "to": recipient_email,
                "subject": subject,
                "html": html_content
            }
            
            # Send the email
            response = resend.Emails.send(email_params)
            
            if hasattr(response, 'id'):
                logger.info(f"Transfer notification email sent via Resend. Email ID: {response.id}")
                return True
            else:
                logger.error(f"Failed to send email. Resend response: {response}")
                return False
                
        except ImportError:
            logger.error("Resend library not installed. Run 'pip install resend' to install it.")
            return False
        except Exception as e:
            logger.error(f"Error sending email via Resend: {e}", exc_info=True)
            return False
    
    def save_config(self):
        """Save configuration changes back to file"""
        portal_config_path = os.path.join(self.config_path, 'client_portal_config.json')
        
        try:
            if os.path.exists(portal_config_path):
                with open(portal_config_path, 'r') as f:
                    config = json.load(f)
                
                # Update cash management settings
                config['cash_management'] = config.get('cash_management', {})
                config['cash_management']['min_cash_level'] = self.config['min_cash_level']
                config['cash_management']['transfer_threshold'] = self.config['transfer_threshold']
                config['cash_management']['allocation_tolerance'] = self.config['allocation_tolerance']
                
                # Save updated config
                with open(portal_config_path, 'w') as f:
                    json.dump(config, f, indent=4)
                
                logger.info(f"Saved updated configuration to {portal_config_path}")
                return True
            else:
                logger.error(f"Configuration file not found: {portal_config_path}")
                return False
        except Exception as e:
            logger.error(f"Error saving configuration: {e}", exc_info=True)
            return False