import os
import json
import logging
import pandas as pd
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_bootstrap import Bootstrap
import plotly.express as px
import plotly.graph_objects as go
import plotly.utils
from threading import Thread
from pathlib import Path
import time
from simple_account_storage import load_account_details, save_account_details, update_account_with_orders, load_orders_from_csv

# Import our modules
from ibkr_client import IBKRApp
from portfolio_manager import PortfolioManager
from investment_manager import InvestmentManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("client_portal.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'arki_portfolio_management_secret_key'  # For session management
Bootstrap(app)

# Application state
app_state = {
    'ibkr_app': None,
    'portfolio_manager': None,
    'investment_manager': None,
    'connected': False,
    'config_path': 'config',
    'static_account_data': None  # For storing the loaded account data
}

# Configuration
def load_config():
    """Load application configuration"""
    
    config_file = os.path.join(app_state['config_path'], 'email')
    default_config = {
        'ibkr': {
            'host': '127.0.0.1',
            'port': 7497,  # 7497 for TWS demo, 4002 for Gateway demo
            'client_id': 2  # Different from scheduler
        },
        'accounts': {
            'cash_account_id': 'DU12345',
            'investment_account_id': 'DU4184147'
        },
        'dashboard': {
            'refresh_interval': 60,  # Seconds
            'charts': ['asset_allocation', 'performance']
        },
        'cash_management': {
            'min_cash_level': 10000.0,
            'transfer_threshold': 5000.0,
            'allocation_tolerance': 0.02
        },
        'email': {
            'smtp_server': 'smtp.gmail.com',
            'smtp_port': 587,
            'sender_email': 'avimcm77@gmail.com',
            'sender_password': '',
            'recipient_email': 'avimcm77@gmail.com',
            'email_service': 'resend',
            'resend_api_key': 're_2vznwWbq_E7LuhmuQgw3t2Sqfp3Y9u92Q',
            'resend_from_email': 'onboarding@resend.dev'
        }
    }
    
    # Create default config if it doesn't exist
    if not os.path.exists(config_file):
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        with open(config_file, 'w') as f:
            json.dump(default_config, f, indent=4)
        logger.info(f"Created default client portal configuration at {config_file}")
        return default_config
    
    # Load existing config
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
            
        # Add email configuration if it doesn't exist
        if 'email' not in config:
            config['email'] = default_config['email']
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
                
        # Make sure all required email parameters exist
        elif 'email' in config:
            email_updated = False
            if 'email_service' not in config['email']:
                config['email']['email_service'] = 'resend'
                email_updated = True
            if 'resend_api_key' not in config['email']:
                config['email']['resend_api_key'] = os.environ.get('RESEND_API_KEY', '')
                email_updated = True
            if 'resend_from_email' not in config['email']:
                config['email']['resend_from_email'] = 'onboarding@resend.dev'
                email_updated = True
                
            # Save updated config if needed
            if email_updated:
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=4)
                    
        logger.info(f"Loaded client portal configuration from {config_file}")
        return config
    except Exception as e:
        logger.error(f"Error loading client portal configuration: {e}", exc_info=True)
        return default_config

# Initialize components
def initialize_components():
    """Initialize IBKR client and managers"""
    
    config = load_config()
    # Debug logging for email config
    if 'email' in config and 'resend_api_key' in config['email']:
        # Don't log the actual API key for security
        logger.info(f"Resend API key configured: {'Yes' if config['email']['resend_api_key'] else 'No'}")
    else:
        logger.warning("Resend API key not found in configuration")

    # Add this to your initialize_components function
    if 'email' in config:
        logger.info(f"Email service configured: {config['email'].get('email_service', 'not specified')}")
    
    # Create IBKR client if it doesn't exist
    if app_state['ibkr_app'] is None:
        ibkr_config = config['ibkr']
        app_state['ibkr_app'] = IBKRApp()
    
    # Create portfolio manager (simulated cash account only) if it doesn't exist
    if app_state['portfolio_manager'] is None:
        app_state['portfolio_manager'] = PortfolioManager(config_path=app_state['config_path'])
        # Add cash management settings from config
        if 'cash_management' in config:
            app_state['portfolio_manager'].config.update(config['cash_management'])
    
    # Create investment manager (real IBKR account) if it doesn't exist
    if app_state['investment_manager'] is None:
        # Pass IBKR client directly to investment manager
        app_state['investment_manager'] = InvestmentManager(app_state['ibkr_app'])
        # Set the investment account ID from config
        app_state['investment_manager'].investment_account_id = config['accounts']['investment_account_id']
    
    # Load static account data from file
    if app_state['static_account_data'] is None:
        account_id = config['accounts']['investment_account_id']
        app_state['static_account_data'] = load_account_details(account_id)
        
        # Apply orders from CSV if account data was loaded
        if app_state['static_account_data']:
            orders = load_orders_from_csv()
            if orders:
                app_state['static_account_data'] = update_account_with_orders(app_state['static_account_data'], orders)
                # Save updated account data
                save_account_details(app_state['static_account_data'], account_id)
                logger.info(f"Applied {len(orders)} orders to account {account_id}")
            
            # Set account data in investment manager
            if app_state['investment_manager']:
                app_state['investment_manager'].investment_account = app_state['static_account_data']

# Connect to IBKR in a separate thread
def connect_ibkr_async():
    """Connect to IBKR in a separate thread (simulated for demo)"""
    
    def connect_job():
        try:
            initialize_components()
            
            # For the demo, set connected to true without actually connecting
            app_state['connected'] = True
            logger.info("Demo mode active - using static account data instead of IBKR connection")
            
            # Always load portfolio manager data 
            if app_state['portfolio_manager']:
                app_state['portfolio_manager'].load_account_info()
                app_state['portfolio_manager'].load_portfolio_allocations()
            
        except Exception as e:
            logger.error(f"Error in connection setup: {e}", exc_info=True)
            app_state['connected'] = False
            
            # Even if setup fails, still load simulated cash account
            try:
                if app_state['portfolio_manager']:
                    app_state['portfolio_manager'].load_account_info()
                    app_state['portfolio_manager'].load_portfolio_allocations()
            except Exception as inner_e:
                logger.error(f"Error loading account info: {inner_e}", exc_info=True)
    
    # Start connection in a separate thread
    thread = Thread(target=connect_job)
    thread.daemon = True
    thread.start()
    return thread

# Disconnect from IBKR
def disconnect_ibkr():
    """Disconnect from IBKR (simulated for demo)"""
    app_state['connected'] = False
    logger.info("Demo mode: Disconnected from simulated IBKR connection")

# Add a function to simulate cash deposit
@app.route('/deposit', methods=['GET', 'POST'])
def deposit():
    """Deposit cash to simulated cash account"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None:
        initialize_components()
    
    if request.method == 'POST':
        amount = request.form.get('amount')
        
        if amount and float(amount) > 0:
            success = app_state['portfolio_manager'].simulate_cash_deposit(float(amount))
            
            if success:
                flash(f'Successfully deposited ${amount} to cash account', 'success')
                # Reload account info
                app_state['portfolio_manager'].load_account_info()
                
                # Check if we need to transfer excess cash
                cash_info = app_state['portfolio_manager'].check_cash_level()
                
                if 'should_transfer' in cash_info and cash_info['should_transfer']:
                    # Get account IDs
                    config = load_config()
                    cash_account_id = app_state['portfolio_manager'].cash_account['id']
                    investment_account_id = config['accounts']['investment_account_id']
                    
                    # Calculate amount to transfer (excess cash)
                    transfer_amount = cash_info['excess_cash']
                    
                    # Perform transfer from simulated cash account
                    transfer_success = app_state['portfolio_manager'].transfer_cash(
                        amount=transfer_amount,
                        from_account=cash_account_id,
                        to_account=investment_account_id
                    )
                    
                    if transfer_success:
                        flash(f'Automatically transferred ${transfer_amount:.2f} to investment account', 'success')
                        # Update investment account (same code as in the transfer route)
                        if app_state['static_account_data']:
                            try:
                                # Update cash balances in static account data
                                if 'data' in app_state['static_account_data'] and 'account_info' in app_state['static_account_data']['data']:
                                    for key in ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'CashBalance_BASE']:
                                        if key in app_state['static_account_data']['data']['account_info']:
                                            current_cash = float(app_state['static_account_data']['data']['account_info'][key])
                                            app_state['static_account_data']['data']['account_info'][key] = str(current_cash + transfer_amount)
                                
                                # More update code as in your transfer route...
                                
                                # Save updated account data
                                save_account_details(app_state['static_account_data'], investment_account_id)
                                
                                # Update investment manager
                                if app_state['investment_manager']:
                                    app_state['investment_manager'].investment_account = app_state['static_account_data']
                                    app_state['investment_manager'].receive_cash_transfer(transfer_amount)
                            except Exception as e:
                                logger.error(f"Error updating investment account after automatic transfer: {e}")
                    else:
                        flash('Failed to execute automatic transfer', 'warning')
            else:
                flash('Failed to deposit to cash account', 'danger')
        else:
            flash('Invalid deposit amount', 'warning')
        
        return redirect(url_for('dashboard'))
    
    return render_template('deposit.html')

# Add route for transferring cash from cash account to investment account
@app.route('/transfer', methods=['POST'])
def transfer():
    """Transfer cash from cash account to investment account"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None or app_state['investment_manager'] is None:
        initialize_components()
    
    amount = request.form.get('amount')
    
    if not amount or float(amount) <= 0:
        flash('Invalid transfer amount', 'warning')
        return redirect(url_for('dashboard'))
    
    amount = float(amount)
    
    # Check if we have enough excess cash
    cash_info = app_state['portfolio_manager'].check_cash_level()
    
    if 'error' in cash_info:
        flash(f'Error checking cash level: {cash_info["error"]}', 'danger')
        return redirect(url_for('dashboard'))
    
    if amount > cash_info['excess_cash']:
        flash(f'Transfer amount exceeds excess cash. Maximum available: ${cash_info["excess_cash"]:.2f}', 'warning')
        return redirect(url_for('dashboard'))
    
    # Get account IDs
    config = load_config()
    cash_account_id = config['accounts']['cash_account_id']
    investment_account_id = config['accounts']['investment_account_id']
    
    # Perform transfer from simulated cash account
    success_cash = app_state['portfolio_manager'].transfer_cash(
        amount=amount,
        from_account=cash_account_id,
        to_account=investment_account_id
    )
    
    # Update static account data
    investment_success = False
    if app_state['static_account_data']:
        try:
            # Update cash balances in static account data
            if 'data' in app_state['static_account_data'] and 'account_info' in app_state['static_account_data']['data']:
                for key in ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'CashBalance_BASE']:
                    if key in app_state['static_account_data']['data']['account_info']:
                        current_cash = float(app_state['static_account_data']['data']['account_info'][key])
                        app_state['static_account_data']['data']['account_info'][key] = str(current_cash + amount)
            
            if 'summary' in app_state['static_account_data']:
                for key in ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'CashBalance_BASE']:
                    if key in app_state['static_account_data']['summary']:
                        current_cash = float(app_state['static_account_data']['summary'][key])
                        app_state['static_account_data']['summary'][key] = str(current_cash + amount)
            
            # Update portfolio values
            for key in ['NetLiquidation_SGD', 'EquityWithLoanValue_SGD']:
                if 'data' in app_state['static_account_data'] and 'account_info' in app_state['static_account_data']['data']:
                    if key in app_state['static_account_data']['data']['account_info']:
                        current_value = float(app_state['static_account_data']['data']['account_info'][key])
                        app_state['static_account_data']['data']['account_info'][key] = str(current_value + amount)
                
                if 'summary' in app_state['static_account_data']:
                    if key in app_state['static_account_data']['summary']:
                        current_value = float(app_state['static_account_data']['summary'][key])
                        app_state['static_account_data']['summary'][key] = str(current_value + amount)
            
            # Save updated account data
            save_account_details(app_state['static_account_data'], investment_account_id)
            
            # Update investment manager
            if app_state['investment_manager']:
                app_state['investment_manager'].investment_account = app_state['static_account_data']
                app_state['investment_manager'].receive_cash_transfer(amount)
            
            investment_success = True
            
        except Exception as e:
            logger.error(f"Error updating investment account after transfer: {e}")
            investment_success = False
    
    if success_cash and investment_success:
        flash(f'Successfully transferred ${amount:.2f} to investment account', 'success')
        # Reload account info
        app_state['portfolio_manager'].load_account_info()
    elif success_cash:
        flash(f'Transfer completed, but there was an issue updating investment account', 'warning')
    else:
        flash('Failed to transfer from cash account', 'danger')
    
    return redirect(url_for('dashboard'))

# Flask routes
@app.route('/')
def index():
    """Home page"""
    return render_template('index.html', connected=app_state['connected'])

@app.route('/connect', methods=['POST'])
def connect():
    """Connect to IBKR"""
    
    if not app_state['connected']:
        connect_ibkr_async()
        flash('Connecting to IBKR...', 'info')
    else:
        flash('Already connected to IBKR', 'info')
    
    return redirect(url_for('index'))

@app.route('/disconnect', methods=['POST'])
def disconnect():
    """Disconnect from IBKR"""
    
    if app_state['connected']:
        disconnect_ibkr()
        flash('Disconnected from IBKR', 'info')
    else:
        flash('Not connected to IBKR', 'info')
    
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    """Dashboard page"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None or app_state['investment_manager'] is None:
        initialize_components()
        connect_ibkr_async()
    
    # Wait a moment for initialization
    time.sleep(1)
    
    # Get cash account information (from portfolio manager)
    try:
        if app_state['portfolio_manager'].cash_account is None:
            app_state['portfolio_manager'].load_account_info()
    except Exception as e:
        logger.error(f"Error loading cash account info: {e}", exc_info=True)
        flash('Error loading cash account information', 'danger')
    
    # Get investment account information from static data
    investment_account_raw = app_state['static_account_data']
    
    # Process investment account data for dashboard display
    processed_investment_account = {
        'id': 'N/A',
        'cash_balance': 0.0,
        'total_value': 0.0,
        'positions': {}
    }
    
    if investment_account_raw:
        # Basic account information
        processed_investment_account['id'] = investment_account_raw.get('id', 'N/A')
        
        # Extract positions (filter out non-position entries)
        positions = {}
        if 'positions' in investment_account_raw:
            for key, pos in investment_account_raw['positions'].items():
                if isinstance(pos, dict) and 'symbol' in pos and 'marketValue' in pos:
                    positions[key] = pos
        
        processed_investment_account['positions'] = positions
        
        # Calculate total position value
        position_value = sum(float(pos.get('marketValue', 0)) for pos in positions.values())
        
        # Get cash balance - try different paths
        cash_balance = 0.0
        
        # Try data/account_info path first
        if ('data' in investment_account_raw and 
            'account_info' in investment_account_raw['data'] and 
            'TotalCashValue_SGD' in investment_account_raw['data']['account_info']):
            cash_balance = float(investment_account_raw['data']['account_info']['TotalCashValue_SGD'])
        # Then try summary path
        elif ('summary' in investment_account_raw and 
              'TotalCashValue_SGD' in investment_account_raw['summary']):
            cash_balance = float(investment_account_raw['summary']['TotalCashValue_SGD'])
        # If both fail, check positions for cash value
        elif 'CashBalance_BASE' in investment_account_raw.get('positions', {}):
            cash_balance = float(investment_account_raw['positions']['CashBalance_BASE'])
        
        processed_investment_account['cash_balance'] = cash_balance
        
        # Get portfolio value - try different paths
        portfolio_value = 0.0
        
        # Try data/account_info path first
        if ('data' in investment_account_raw and 
            'account_info' in investment_account_raw['data'] and 
            'NetLiquidation_SGD' in investment_account_raw['data']['account_info']):
            portfolio_value = float(investment_account_raw['data']['account_info']['NetLiquidation_SGD'])
        # Then try summary path
        elif ('summary' in investment_account_raw and 
              'NetLiquidation_SGD' in investment_account_raw['summary']):
            portfolio_value = float(investment_account_raw['summary']['NetLiquidation_SGD'])
        # If both fail, calculate from positions and cash
        else:
            portfolio_value = position_value + cash_balance
        
        processed_investment_account['total_value'] = portfolio_value
        
        # Add additional useful information
        
        # Available funds
        if ('data' in investment_account_raw and 
            'account_info' in investment_account_raw['data'] and 
            'AvailableFunds_SGD' in investment_account_raw['data']['account_info']):
            processed_investment_account['available_funds'] = float(investment_account_raw['data']['account_info']['AvailableFunds_SGD'])
        elif ('summary' in investment_account_raw and 
              'AvailableFunds_SGD' in investment_account_raw['summary']):
            processed_investment_account['available_funds'] = float(investment_account_raw['summary']['AvailableFunds_SGD'])
        else:
            processed_investment_account['available_funds'] = cash_balance
        
        # Position count
        processed_investment_account['position_count'] = len(positions)
        
        # Position value
        processed_investment_account['position_value'] = position_value
    
    # Prepare account data for template
    account_data = {
        'cash_account': app_state['portfolio_manager'].cash_account,
        'investment_account': processed_investment_account
    }
    
    # Generate charts
    allocation_chart = generate_allocation_chart()
    performance_chart = generate_performance_chart()
    
    # Format cash level data
    cash_info = app_state['portfolio_manager'].check_cash_level()
    
    return render_template(
        'dashboard.html',
        account_data=account_data,
        cash_info=cash_info,
        allocation_chart=allocation_chart,
        performance_chart=performance_chart,
        cash_account=app_state['portfolio_manager'].cash_account,
        connected=app_state['connected']
    )

@app.route('/portfolio')
def portfolio():
    """Portfolio details page"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None or app_state['investment_manager'] is None:
        initialize_components()
    
    # Get cash portfolio data
    cash_portfolio = None
    if app_state['portfolio_manager']:
        cash_portfolio = app_state['portfolio_manager'].cash_portfolio
        if not cash_portfolio:
            app_state['portfolio_manager'].load_portfolio_allocations()
            cash_portfolio = app_state['portfolio_manager'].cash_portfolio
    
    # Get investment portfolio data from investment manager
    investment_portfolio = {}
    if app_state['investment_manager'] and hasattr(app_state['investment_manager'], 'investment_portfolio'):
        if not investment_portfolio:
            app_state['investment_manager'].load_portfolio_allocations()
        investment_portfolio = app_state['investment_manager'].investment_portfolio
    
    # Get cash positions
    cash_positions = {}
    if app_state['portfolio_manager'] and app_state['portfolio_manager'].cash_account:
        cash_positions = app_state['portfolio_manager'].cash_account.get('positions', {})
    
    # Get investment positions from static data
    investment_positions = {}
    if app_state['static_account_data'] and 'positions' in app_state['static_account_data']:
        positions = app_state['static_account_data']['positions']
        for key, pos in positions.items():
            # Only include actual position objects
            if isinstance(pos, dict) and ('symbol' in pos or 'position' in pos):
                investment_positions[key] = pos
    
    return render_template(
        'portfolio.html',
        cash_portfolio=cash_portfolio,
        investment_portfolio=investment_portfolio,
        cash_positions=cash_positions,
        investment_positions=investment_positions
    )

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    """Settings page"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None:
        initialize_components()
    
    config = load_config()
    
    if request.method == 'POST':
        # Update cash thresholds
        min_cash_level = request.form.get('min_cash_level')
        transfer_threshold = request.form.get('transfer_threshold')
        
        if min_cash_level and transfer_threshold:
            min_cash_level = float(min_cash_level)
            transfer_threshold = float(transfer_threshold)
            
            # Update config file
            config['cash_management'] = config.get('cash_management', {})
            config['cash_management']['min_cash_level'] = min_cash_level
            config['cash_management']['transfer_threshold'] = transfer_threshold
            
            # Save updated config
            config_file = os.path.join(app_state['config_path'], 'client_portal_config.json')
            with open(config_file, 'w') as f:
                json.dump(config, f, indent=4)
            
            # Update portfolio manager config
            if app_state['portfolio_manager']:
                app_state['portfolio_manager'].config['min_cash_level'] = min_cash_level
                app_state['portfolio_manager'].config['transfer_threshold'] = transfer_threshold
                
                # Save simulated cash account if needed
                if hasattr(app_state['portfolio_manager'], 'save_config'):
                    app_state['portfolio_manager'].save_config()
            
            flash('Settings updated successfully', 'success')
        
        return redirect(url_for('settings'))
    
    # Get current settings
    cash_management = config.get('cash_management', {})
    settings_data = {
        'min_cash_level': cash_management.get('min_cash_level', 10000.0),
        'transfer_threshold': cash_management.get('transfer_threshold', 5000.0),
        'allocation_tolerance': cash_management.get('allocation_tolerance', 0.02),
        'ibkr_host': config['ibkr'].get('host', '127.0.0.1'),
        'ibkr_port': config['ibkr'].get('port', 7497)
    }
    
    return render_template('settings.html', settings=settings_data)

@app.route('/api/account_data')
def api_account_data():
    """API endpoint for account data"""
    
    # Initialize components if needed
    if app_state['portfolio_manager'] is None or app_state['investment_manager'] is None:
        initialize_components()
    
    # Refresh account data
    if app_state['portfolio_manager']:
        app_state['portfolio_manager'].load_account_info()
    
    # Prepare cash account data
    cash_account_data = {
        'id': 'N/A',
        'cash_balance': 0,
        'total_value': 0
    }
    
    if app_state['portfolio_manager'] and app_state['portfolio_manager'].cash_account:
        cash_account = app_state['portfolio_manager'].cash_account
        cash_account_data = {
            'id': cash_account.get('id', 'N/A'),
            'cash_balance': get_cash_balance(cash_account),
            'total_value': get_account_value(cash_account)
        }
    
    # Prepare investment account data from static data
    investment_account_data = {
        'id': 'N/A',
        'cash_balance': 0,
        'total_value': 0
    }
    
    if app_state['static_account_data']:
        investment_account = app_state['static_account_data']
        investment_account_data = {
            'id': investment_account.get('id', 'N/A'),
            'cash_balance': get_cash_balance(investment_account),
            'total_value': get_account_value(investment_account)
        }
    
    # Format cash level info
    cash_level = {'error': 'Cash level check not available'}
    if app_state['portfolio_manager']:
        cash_level = app_state['portfolio_manager'].check_cash_level()
    
    # Format response data
    response = {
        'cash_account': cash_account_data,
        'investment_account': investment_account_data,
        'cash_level': cash_level,
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(response)

# Helper functions
def generate_allocation_chart():
    """Generate asset allocation chart"""
    
    # Get investment positions from static data using the same approach as portfolio()
    investment_positions = {}
    if app_state['static_account_data'] and 'positions' in app_state['static_account_data']:
        positions = app_state['static_account_data']['positions']
        for key, pos in positions.items():
            # Only include actual position objects
            if isinstance(pos, dict) and ('symbol' in pos or 'position' in pos):
                investment_positions[key] = pos
    
    # If no positions found, try investment manager
    if not investment_positions and app_state['investment_manager'] and hasattr(app_state['investment_manager'], 'investment_account'):
        account = app_state['investment_manager'].investment_account
        if account and 'positions' in account:
            for key, pos in account['positions'].items():
                if isinstance(pos, dict) and ('symbol' in pos or 'position' in pos):
                    investment_positions[key] = pos
    
    # Prepare data for chart
    allocation_data = {}
    for key, position in investment_positions.items():
        # Get symbol
        symbol = position.get('symbol', key)
        
        # Extract symbol from key if needed
        if not symbol and '_' in key:
            symbol = key.split('_')[0]
        
        # Get market value
        market_value = position.get('marketValue', 0)
        if not market_value and 'position' in position and 'marketPrice' in position:
            market_value = position['position'] * position['marketPrice']
        
        if market_value > 0:
            allocation_data[symbol] = market_value
    
    # Create chart if we have data
    if allocation_data:
        df = pd.DataFrame({
            'Asset': list(allocation_data.keys()),
            'Value': list(allocation_data.values())
        })
        
        fig = px.pie(df, values='Value', names='Asset', title='Asset Allocation')
        return plotly.utils.PlotlyJSONEncoder().encode(fig)
    
    return None

def generate_performance_chart():
    """Generate performance chart"""
    
    # Simulated performance data
    # In a real implementation, this would pull historical data from IBKR
    dates = pd.date_range(start='2024-01-01', end='2025-2-28', freq='M')
    
    cash_values = [10000 + i*500 for i in range(len(dates))]
    investment_values = [20000 + i*1000 + (i*i*10) for i in range(len(dates))]
    benchmark_values = [30000 + i*800 + (i*5) for i in range(len(dates))]
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=dates, y=cash_values,
        mode='lines',
        name='Cash Account'
    ))
    
    fig.add_trace(go.Scatter(
        x=dates, y=investment_values,
        mode='lines',
        name='Investment Account'
    ))
    
    fig.add_trace(go.Scatter(
        x=dates, y=benchmark_values,
        mode='lines',
        name='Benchmark'
    ))
    
    fig.update_layout(
        title='Portfolio Performance',
        xaxis_title='Date',
        yaxis_title='Value (SGD)',
        legend_title='Accounts'
    )
    
    return plotly.utils.PlotlyJSONEncoder().encode(fig)

def get_cash_balance(account):
    """Get cash balance from account data"""
    
    if not account:
        return 0
    
    # Try different formats for cash balance
    if 'data' in account and 'account_info' in account['data']:
        account_info = account['data']['account_info']
        
        # Look for cash balance keys
        cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'TotalCashValue', 'AvailableFunds']
        
        for key in cash_keys:
            if key in account_info:
                return float(account_info[key])
    
    # Alternative format
    if 'summary' in account:
        summary = account['summary']
        
        cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'TotalCashValue', 'AvailableFunds']
        
        for key in cash_keys:
            if key in summary:
                return float(summary[key])
    
    # Direct cash value
    if 'cash_balance' in account:
        return float(account['cash_balance'])
    
    return 0

def get_account_value(account):
    """Get total account value"""
    
    if not account:
        return 0
    
    # Try different formats for account value
    if 'data' in account and 'account_info' in account['data']:
        account_info = account['data']['account_info']
        
        # Look for value keys
        value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
        
        for key in value_keys:
            if key in account_info:
                return float(account_info[key])
    
    # Alternative format
    if 'summary' in account:
        summary = account['summary']
        
        value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
        
        for key in value_keys:
            if key in summary:
                return float(summary[key])
    
    # Direct total value
    if 'total_value' in account:
        return float(account['total_value'])
    
    return 0

# Create necessary directories
def ensure_directories():
    """Ensure necessary directories exist"""
    
    os.makedirs(app_state['config_path'], exist_ok=True)
    os.makedirs('static', exist_ok=True)
    os.makedirs('templates', exist_ok=True)

# Create template files
def create_templates():
    """Create template files if they don't exist"""
    
    templates_dir = 'templates'
    
    # Base template
    base_html = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Arki Portfolio Management{% endblock %}</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@4.6.0/dist/css/bootstrap.min.css">
    <link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
    {% block head %}{% endblock %}
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <a class="navbar-brand" href="/">Arki Portfolio</a>
        <button class="navbar-toggler" type="button" data-toggle="collapse" data-target="#navbarNav">
            <span class="navbar-toggler-icon"></span>
        </button>
        <div class="collapse navbar-collapse" id="navbarNav">
            <ul class="navbar-nav">
                <li class="nav-item">
                    <a class="nav-link" href="/">Home</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/dashboard">Dashboard</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/portfolio">Portfolio</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/deposit">Deposit</a>
                </li>
                <li class="nav-item">
                    <a class="nav-link" href="/settings">Settings</a>
                </li>
            </ul>
        </div>
    </nav>
    
    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert alert-{{ category }}">{{ message }}</div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        {% block content %}{% endblock %}
    </div>
    
    <footer class="mt-5 p-3 text-center bg-light">
        <div class="container">
            <p>Arki Portfolio Management &copy; 2025</p>
        </div>
    </footer>
    
    <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
    '''
    
    # Index page (updated version with deposit)
    index_html = '''
{% extends "base.html" %}

{% block title %}Arki Portfolio - Home{% endblock %}

{% block content %}
<div class="jumbotron">
    <h1 class="display-4">Arki Portfolio Management</h1>
    <p class="lead">A portfolio management system for IBKR accounts</p>
    <hr class="my-4">
    <p>Connect to IBKR to view and manage your portfolio.</p>
    <div class="d-flex">
        {% if connected %}
            <form action="/disconnect" method="post" class="mr-2">
                <button type="submit" class="btn btn-warning">Disconnect from IBKR</button>
            </form>
            <a href="/dashboard" class="btn btn-primary">View Dashboard</a>
        {% else %}
            <form action="/connect" method="post">
                <button type="submit" class="btn btn-success">Connect to IBKR</button>
            </form>
        {% endif %}
    </div>
</div>

<div class="row mt-4">
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Portfolio Dashboard</h5>
                <p class="card-text">View your portfolio dashboard with real-time account information and charts.</p>
                <a href="/dashboard" class="btn btn-primary">View Dashboard</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Portfolio Details</h5>
                <p class="card-text">Explore detailed information about your portfolio allocations and positions.</p>
                <a href="/portfolio" class="btn btn-primary">View Portfolio</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Deposit Funds</h5>
                <p class="card-text">Deposit funds to your simulated cash account to test the transfer functionality.</p>
                <a href="/deposit" class="btn btn-success">Deposit Funds</a>
            </div>
        </div>
    </div>
    <div class="col-md-3">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Settings</h5>
                <p class="card-text">Configure system parameters and adjust portfolio allocation settings.</p>
                <a href="/settings" class="btn btn-primary">Manage Settings</a>
            </div>
        </div>
    </div>
</div>
{% endblock %}
    '''
    
    # Dashboard page
    dashboard_html = '''
{% extends "base.html" %}

{% block title %}Arki Portfolio - Dashboard{% endblock %}

{% block head %}
<style>
    .metrics-card {
        height: 100%;
    }
    .chart-container {
        min-height: 400px;
    }
</style>
{% endblock %}

{% block content %}
<h1>Portfolio Dashboard</h1>

<div class="row mt-4">
    <!-- First row with account cards - full width on small screens, half width on medium+ screens -->
    <div class="col-12 col-md-6 mb-4">
        <div class="card metrics-card h-100">
            <div class="card-header">
                <h5>Cash Account (Simulated)</h5>
            </div>
            <div class="card-body">
                {% if account_data.cash_account %}
                    <p><strong>Account ID:</strong> {{ account_data.cash_account.id }}</p>
                    <p><strong>Cash Balance:</strong> ${{ "%.2f"|format(account_data.cash_account.data.account_info.get('TotalCashValue_SGD', 0)|float) }}</p>
                    <p><strong>Min Cash Level:</strong> ${{ "%.2f"|format(cash_info.min_cash_level) }}</p>
                    <p><strong>Excess Cash:</strong> ${{ "%.2f"|format(cash_info.excess_cash) }}</p>
                    <p><strong>Transfer Threshold:</strong> ${{ "%.2f"|format(cash_info.transfer_threshold) }}</p>
                    <p><strong>Should Transfer:</strong> {{ "Yes" if cash_info.should_transfer else "No" }}</p>
                    
                    <div class="mt-3">
                        <a href="/deposit" class="btn btn-success">Deposit Funds</a>
                        {% if cash_info.should_transfer %}
                            <form action="/transfer" method="post" class="d-inline ml-2">
                                <input type="hidden" name="amount" value="{{ cash_info.excess_cash }}">
                                <button type="submit" class="btn btn-primary">Transfer to Investment</button>
                            </form>
                        {% endif %}
                    </div>
                {% else %}
                    <p>Cash account data not available</p>
                {% endif %}
            </div>
        </div>
    </div>
    
    <div class="col-12 col-md-6 mb-4">
        <div class="card metrics-card h-100">
            <div class="card-header">
                <h5>Investment Account{% if not connected %} (Simulated){% endif %}</h5>
            </div>
            <div class="card-body">
                {% if account_data.investment_account %}
                    <p><strong>Account ID:</strong> {{ account_data.investment_account.id }}</p>
                    
                    {% if account_data.investment_account.cash_balance is defined and account_data.investment_account.cash_balance is not none %}
                        <p><strong>Cash Balance:</strong> ${{ "%.2f"|format(account_data.investment_account.cash_balance|float) }}</p>
                    {% else %}
                        <p><strong>Cash Balance:</strong> $0.00</p>
                    {% endif %}
                    
                    {% if account_data.investment_account.total_value is defined and account_data.investment_account.total_value is not none %}
                        <p><strong>Portfolio Value:</strong> ${{ "%.2f"|format(account_data.investment_account.total_value|float) }}</p>
                    {% else %}
                        <p><strong>Portfolio Value:</strong> $0.00</p>
                    {% endif %}
                    
                    <p><strong>Number of Positions:</strong> {{ account_data.investment_account.positions|length if account_data.investment_account.positions else 0 }}</p>
                    
                    {% if not connected %}
                        <div class="alert alert-warning mt-3">
                            <small>Investment account is in simulation mode. Connect to IBKR for real data.</small>
                        </div>
                    {% endif %}
                {% else %}
                    <p>Investment account data not available</p>
                {% endif %}
            </div>
        </div>
    </div>

    <!-- Second row with charts - full width on small screens, half width on medium+ screens -->
    <div class="col-12 col-md-6 mb-4">
        <div class="card h-100">
            <div class="card-header">
                <h5>Asset Allocation</h5>
            </div>
            <div class="card-body">
                <div id="allocation-chart" class="chart-container">
                    {% if allocation_chart %}
                        <div id="allocation-plot"></div>
                    {% else %}
                        <p>No allocation data available</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
    
    <div class="col-12 col-md-6 mb-4">
        <div class="card h-100">
            <div class="card-header">
                <h5>Performance History</h5>
            </div>
            <div class="card-body">
                <div id="performance-chart" class="chart-container">
                    {% if performance_chart %}
                        <div id="performance-plot"></div>
                    {% else %}
                        <p>No performance data available</p>
                    {% endif %}
                </div>
            </div>
        </div>
    </div>
</div>

{% if cash_account and cash_account.transactions and cash_account.transactions|length > 0 %}
<div class="row mt-4">
    <div class="col-12">
        <div class="card">
            <div class="card-header">
                <h5>Recent Transactions</h5>
            </div>
            <div class="card-body">
                <div class="table-responsive">
                    <table class="table table-striped">
                        <thead>
                            <tr>
                                <th>Date/Time</th>
                                <th>Type</th>
                                <th>Amount</th>
                                <th>Details</th>
                                <th>Balance After</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for tx in cash_account.transactions|sort(attribute='timestamp', reverse=True) %}
                                {% if loop.index <= 10 %}
                                <tr>
                                    <td>{{ tx.timestamp }}</td>
                                    <td>{{ tx.type }}</td>
                                    <td>${{ "%.2f"|format(tx.amount) }}</td>
                                    <td>
                                        {% if tx.type == 'transfer_out' %}
                                            To: {{ tx.destination_account }}
                                        {% endif %}
                                    </td>
                                    <td>${{ "%.2f"|format(tx.balance_after) }}</td>
                                </tr>
                                {% endif %}
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endif %}
{% endblock %}

{% block scripts %}
<script>
    // Render charts if data is available
    {% if allocation_chart %}
        const allocationData = {{ allocation_chart|safe }};
        Plotly.newPlot('allocation-plot', allocationData.data, allocationData.layout);
    {% endif %}
    
    {% if performance_chart %}
        const performanceData = {{ performance_chart|safe }};
        Plotly.newPlot('performance-plot', performanceData.data, performanceData.layout);
    {% endif %}
    
    // Auto-refresh data every minute
    setTimeout(function() {
        location.reload();
    }, 60000);

    // Resize Plotly charts when window size changes
    window.addEventListener('resize', function() {
        if (allocationData) Plotly.relayout('allocation-plot', {
            'width': document.getElementById('allocation-plot').offsetWidth
        });
        if (performanceData) Plotly.relayout('performance-plot', {
            'width': document.getElementById('performance-plot').offsetWidth
        });
    });
</script>

<style>
    .chart-container {
        height: 350px;
        width: 100%;
    }
    
    .metrics-card {
        height: 100%;
    }
    
    @media (min-width: 768px) {
        .chart-container {
            height: 450px;
        }
    }
</style>
{% endblock %}
    '''
    # Deposit page
    deposit_html = '''
{% extends "base.html" %}

{% block title %}Arki Portfolio - Deposit{% endblock %}

{% block content %}
<h1>Deposit to Cash Account</h1>

<div class="row mt-4">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Deposit Funds</h5>
            </div>
            <div class="card-body">
                <form action="/deposit" method="post">
                    <div class="form-group">
                        <label for="amount">Deposit Amount (SGD)</label>
                        <input type="number" class="form-control" id="amount" name="amount" step="1000" min="1000" required>
                        <small class="form-text text-muted">Enter the amount to deposit into your cash account</small>
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Deposit Funds</button>
                </form>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Information</h5>
            </div>
            <div class="card-body">
                <p>This is a simulated deposit to your cash account. In a real application, this would integrate with 
                    a payment gateway or banking API.</p>
                <p>After depositing funds, you'll be redirected to the dashboard where you can see your updated account balance.</p>
            </div>
        </div>
    </div>
</div>
{% endblock %}
    '''
    
    # Portfolio page - keep as is
    portfolio_html = '''
{% extends "base.html" %}

{% block title %}Arki Portfolio - Portfolio Details{% endblock %}

{% block content %}
<h1>Portfolio Details</h1>

<div class="row mt-4">
    <div class="col-md-12">
        <ul class="nav nav-tabs" id="portfolioTabs" role="tablist">
            <li class="nav-item">
                <a class="nav-link active" id="cash-tab" data-toggle="tab" href="#cash" role="tab">Cash Portfolio</a>
            </li>
            <li class="nav-item">
                <a class="nav-link" id="investment-tab" data-toggle="tab" href="#investment" role="tab">Investment Portfolio</a>
            </li>
            <li class="nav-item">
                <a class="nav-link" id="positions-tab" data-toggle="tab" href="#positions" role="tab">Current Positions</a>
            </li>
        </ul>
        
        <div class="tab-content mt-3" id="portfolioTabContent">
            <!-- Cash Portfolio Tab -->
            <div class="tab-pane fade show active" id="cash" role="tabpanel">
                <div class="card">
                    <div class="card-header">
                        <h5>Cash Portfolio Allocation</h5>
                    </div>
                    <div class="card-body">
                        {% if cash_portfolio %}
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Instrument</th>
                                        <th>Target Percentage</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for instrument, percentage in cash_portfolio.items() %}
                                        <tr>
                                            <td>{{ instrument }}</td>
                                            <td>{{ "%.2f"|format(percentage * 100) }}%</td>
                                        </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p>No cash portfolio allocation data available</p>
                        {% endif %}
                    </div>
                </div>
            </div>
            
            <!-- Investment Portfolio Tab -->
            <div class="tab-pane fade" id="investment" role="tabpanel">
                <div class="card">
                    <div class="card-header">
                        <h5>Investment Portfolio Allocation</h5>
                    </div>
                    <div class="card-body">
                        {% if investment_portfolio and investment_portfolio is mapping %}
                            {% for strategy, instruments in investment_portfolio.items() %}
                                <h6>{{ strategy }}</h6>
                                <table class="table table-striped">
                                    <thead>
                                        <tr>
                                            <th>Instrument</th>
                                            <th>Type</th>
                                            <th>Exchange</th>
                                            <th>Target Percentage</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {% for instrument, details in instruments.items() %}
                                            <tr>
                                                <td>{{ instrument }}</td>
                                                <td>{{ details.instrument_type }}</td>
                                                <td>{{ details.exchange }}</td>
                                                <td>{{ "%.2f"|format(details.target_percentage * 100) }}%</td>
                                            </tr>
                                        {% endfor %}
                                    </tbody>
                                </table>
                            {% endfor %}
                        {% else %}
                            <p>No investment portfolio allocation data available</p>
                        {% endif %}
                    </div>
                </div>
            </div>
            
            <!-- Positions Tab -->
            <div class="tab-pane fade" id="positions" role="tabpanel">
                <div class="card">
                    <div class="card-header">
                        <h5>Current Positions</h5>
                    </div>
                    <div class="card-body">
                        <h6>Cash Account Positions</h6>
                        {% if cash_positions %}
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Symbol</th>
                                        <th>Type</th>
                                        <th>Position</th>
                                        <th>Market Price</th>
                                        <th>Market Value</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for key, position in cash_positions.items() %}
                                        <tr>
                                            <td>{{ position.contract.symbol }}</td>
                                            <td>{{ position.contract.secType }}</td>
                                            <td>{{ position.position }}</td>
                                            <td>${{ "%.2f"|format(position.marketPrice or 0) }}</td>
                                            <td>${{ "%.2f"|format(position.marketValue or 0) }}</td>
                                        </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p>No cash account positions available</p>
                        {% endif %}
                        
                        <h6 class="mt-4">Investment Account Positions</h6>
                        {% if investment_positions %}
                            <table class="table table-striped">
                                <thead>
                                    <tr>
                                        <th>Symbol</th>
                                        <th>Type</th>
                                        <th>Position</th>
                                        <th>Market Price</th>
                                        <th>Market Value</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {% for key, position in investment_positions.items() %}
                                        <tr>
                                            <td>{{ position.symbol }}</td>
                                            <td>{{ position.secType }}</td>
                                            <td>{{ position.position }}</td>
                                            <td>${{ "%.2f"|format(position.marketPrice or 0) }}</td>
                                            <td>${{ "%.2f"|format(position.marketValue or 0) }}</td>
                                        </tr>
                                    {% endfor %}
                                </tbody>
                            </table>
                        {% else %}
                            <p>No investment account positions available</p>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
    '''
    
    # Settings page
    settings_html = '''
{% extends "base.html" %}

{% block title %}Arki Portfolio - Settings{% endblock %}

{% block content %}
<h1>Portfolio Settings</h1>

<div class="row mt-4">
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Cash Management Settings</h5>
            </div>
            <div class="card-body">
                <form action="/settings" method="post">
                    <div class="form-group">
                        <label for="min_cash_level">Minimum Cash Level (SGD)</label>
                        <input type="number" class="form-control" id="min_cash_level" name="min_cash_level" step="1000" value="{{ settings.min_cash_level }}">
                        <small class="form-text text-muted">Minimum cash amount to maintain in cash account</small>
                    </div>
                    
                    <div class="form-group">
                        <label for="transfer_threshold">Transfer Threshold (SGD)</label>
                        <input type="number" class="form-control" id="transfer_threshold" name="transfer_threshold" step="1000" value="{{ settings.transfer_threshold }}">
                        <small class="form-text text-muted">Cash level that triggers transfer to investment account</small>
                    </div>
                    
                    <button type="submit" class="btn btn-primary">Save Changes</button>
                </form>
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card">
            <div class="card-header">
                <h5>Connection Settings</h5>
            </div>
            <div class="card-body">
                <p><strong>IBKR Host:</strong> {{ settings.ibkr_host }}</p>
                <p><strong>IBKR Port:</strong> {{ settings.ibkr_port }}</p>
                <p><small class="form-text text-muted">To change connection settings, edit the configuration file directly.</small></p>
                
                <div class="form-group">
                    <label for="allocation_tolerance">Allocation Tolerance</label>
                    <input type="number" class="form-control" id="allocation_tolerance" name="allocation_tolerance" step="0.01" min="0.01" max="0.10" value="{{ settings.allocation_tolerance }}" disabled>
                    <small class="form-text text-muted">Percentage threshold for rebalancing (e.g., 0.02 = 2%)</small>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
    '''
    
    # Create template files
    templates = {
        'base.html': base_html,
        'index.html': index_html,
        'dashboard.html': dashboard_html,
        'portfolio.html': portfolio_html,
        'settings.html': settings_html,
        'deposit.html': deposit_html
    }
    
    for filename, content in templates.items():
        file_path = os.path.join(templates_dir, filename)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w') as f:
            f.write(content)
        logger.info(f"Created template file {file_path}")

# Create static files
def create_static_files():
    """Create static CSS file"""
    
    css_content = '''
/* Custom styles for Arki Portfolio Management */

.navbar-brand {
    font-weight: bold;
}

.jumbotron {
    background-color: #f8f9fa;
}

.card {
    margin-bottom: 20px;
}

.chart-container {
    width: 100%;
    min-height: 300px;
}

footer {
    margin-top: 50px;
}
    '''
    
    css_path = os.path.join('static', 'style.css')
    if not os.path.exists(css_path):
        os.makedirs(os.path.dirname(css_path), exist_ok=True)
        with open(css_path, 'w') as f:
            f.write(css_content)
        logger.info(f"Created CSS file {css_path}")

# Create sample portfolio allocation file
def create_sample_portfolio_file():
    """Create sample portfolio allocation file"""
    
    config = load_config()
    portfolio_file = os.path.join(app_state['config_path'], 'portfolio_allocation.csv')
    
    if not os.path.exists(portfolio_file):
        # Create sample portfolio allocation data
        data = [
            # Cash portfolio
            {'account_type': 'cash', 'strategy': 'Cash', 'instrument': 'CASH_SGD', 'instrument_type': 'CASH', 'exchange': '', 'target_percentage': 0.4},
            {'account_type': 'cash', 'strategy': 'Cash', 'instrument': 'SHY', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.3},
            {'account_type': 'cash', 'strategy': 'Cash', 'instrument': 'VGSH', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.3},
            
            # Investment portfolio - Equities strategy
            {'account_type': 'investment', 'strategy': 'Equities', 'instrument': 'SPY', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.4},
            {'account_type': 'investment', 'strategy': 'Equities', 'instrument': 'QQQ', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.3},
            {'account_type': 'investment', 'strategy': 'Equities', 'instrument': 'EWS', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.3},
            
            # Investment portfolio - Bonds strategy
            {'account_type': 'investment', 'strategy': 'Bonds', 'instrument': 'AGG', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.5},
            {'account_type': 'investment', 'strategy': 'Bonds', 'instrument': 'LQD', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.5},
            
            # Investment portfolio - Commodities strategy
            {'account_type': 'investment', 'strategy': 'Commodities', 'instrument': 'GLD', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.6},
            {'account_type': 'investment', 'strategy': 'Commodities', 'instrument': 'USO', 'instrument_type': 'ETF', 'exchange': 'SMART', 'target_percentage': 0.4}
        ]
        
        # Create DataFrame and save to CSV
        df = pd.DataFrame(data)
        os.makedirs(os.path.dirname(portfolio_file), exist_ok=True)
        df.to_csv(portfolio_file, index=False)
        
        logger.info(f"Created sample portfolio allocation file at {portfolio_file}")

# Initialize application
def init_app():
    """Initialize the application"""
    
    # Ensure directories exist
    ensure_directories()
    
    # Create template files
    create_templates()
    
    # Create static files
    create_static_files()
    
    # Create sample portfolio file
    create_sample_portfolio_file()
    
    # Load configuration
    load_config()

# Main entry point
if __name__ == "__main__":
    # Initialize application
    init_app()
    
    # Start Flask app
    app.run(debug=True, host='0.0.0.0', port=5001)
                