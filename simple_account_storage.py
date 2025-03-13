import os
import json
import csv
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# Hardcoded file path for account data
ACCOUNT_DATA_PATH = "/Users/avinashparthiban/arki-mvp/data/accounts/DU4184147/account_data.json"

def save_account_details(account_data, account_id):
    """
    Simple function to save account details locally
    
    Args:
        account_data: The account data to save
        account_id: The account ID (not used with hardcoded path)
    """
    try:
        # Create directory path if it doesn't exist
        os.makedirs(os.path.dirname(ACCOUNT_DATA_PATH), exist_ok=True)
        
        # Save to hardcoded JSON file path
        with open(ACCOUNT_DATA_PATH, 'w') as f:
            json.dump(account_data, f, indent=2)
        
        logger.info(f"Account data saved to {ACCOUNT_DATA_PATH}")
        return True
    except Exception as e:
        logger.error(f"Error saving account data: {e}")
        return False

def load_account_details(account_id):
    """
    Simple function to load account details from hardcoded path
    
    Args:
        account_id: The account ID (not used with hardcoded path)
    
    Returns:
        The account data if found, None otherwise
    """
    try:
        # Try loading from hardcoded path
        if os.path.exists(ACCOUNT_DATA_PATH):
            with open(ACCOUNT_DATA_PATH, 'r') as f:
                account_data = json.load(f)
            
            logger.info(f"Account data loaded from {ACCOUNT_DATA_PATH}")
            return account_data
        
        # If the hardcoded path doesn't exist, use DU4184147.json in the current directory as fallback
        fallback_path = "DU4184147.json"
        if os.path.exists(fallback_path):
            with open(fallback_path, 'r') as f:
                account_data = json.load(f)
            
            logger.info(f"Account data loaded from fallback path {fallback_path}")
            
            # Save to the hardcoded path for future use
            save_account_details(account_data, account_id)
            
            return account_data
        
        logger.warning(f"No saved account data found at {ACCOUNT_DATA_PATH} or fallback path")
        return None
    except Exception as e:
        logger.error(f"Error loading account data: {e}")
        return None

def load_orders_from_csv(csv_path='logs/orders.csv'):
    """
    Load orders from CSV file
    
    Args:
        csv_path: Path to the orders CSV file
    
    Returns:
        List of orders
    """
    orders = []
    
    try:
        if not os.path.exists(csv_path):
            logger.warning(f"Orders CSV file not found: {csv_path}")
            return orders
        
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert CSV row to order format
                order = {
                    'contract': {
                        'symbol': row.get('symbol'),
                        'secType': row.get('secType'),
                        'exchange': row.get('exchange'),
                        'currency': 'USD'  # Default currency
                    },
                    'action': row.get('action'),
                    'quantity': float(row.get('quantity', 0)),
                    'price': float(row.get('price', 0)),
                    'strategy': row.get('strategy'),
                    'order_type': 'MKT'
                }
                orders.append(order)
        
        logger.info(f"Loaded {len(orders)} orders from {csv_path}")
        return orders
    except Exception as e:
        logger.error(f"Error loading orders from CSV: {e}")
        return []

def update_account_with_orders(account_data, orders):
    """
    Update account data with orders (treating them as fulfilled)
    
    Args:
        account_data: Account data to update
        orders: List of orders to apply
    
    Returns:
        Updated account data
    """
    if not account_data or not orders:
        return account_data
    
    try:
        # Make a copy to avoid modifying the original
        updated_account = account_data.copy()
        
        # Initialize positions if not present
        if 'positions' not in updated_account:
            updated_account['positions'] = {}
        
        # Process each order
        for order in orders:
            symbol = order.get('contract', {}).get('symbol')
            if not symbol:
                continue
            
            action = order.get('action')
            quantity = float(order.get('quantity', 0))
            price = float(order.get('price', 0))
            
            # Calculate order value
            order_value = quantity * price
            
            # Create position key
            position_key = f"{symbol}_STK"
            
            # Update or create position
            if position_key not in updated_account['positions']:
                updated_account['positions'][position_key] = {
                    'symbol': symbol,
                    'secType': 'STK',
                    'position': 0,
                    'marketPrice': price,
                    'marketValue': 0,
                    'avgCost': price
                }
            
            position = updated_account['positions'][position_key]
            
            # Update position based on action
            if action == 'BUY':
                # Calculate new average cost
                total_cost = (position['position'] * position.get('avgCost', price)) + order_value
                new_position = position['position'] + quantity
                
                if new_position > 0:
                    position['avgCost'] = total_cost / new_position
                
                position['position'] = new_position
                position['marketPrice'] = price  # Update to latest price
                position['marketValue'] = position['position'] * position['marketPrice']
                
                # Update cash balance
                cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'CashBalance_BASE']
                
                # Update in account_info
                if 'data' in updated_account and 'account_info' in updated_account['data']:
                    for key in cash_keys:
                        if key in updated_account['data']['account_info']:
                            current_cash = float(updated_account['data']['account_info'][key])
                            updated_account['data']['account_info'][key] = str(current_cash - order_value)
                
                # Update in summary
                if 'summary' in updated_account:
                    for key in cash_keys:
                        if key in updated_account['summary']:
                            current_cash = float(updated_account['summary'][key])
                            updated_account['summary'][key] = str(current_cash - order_value)
                
            elif action == 'SELL':
                # Calculate realized P&L
                if position['position'] > 0:
                    # Calculate new position
                    new_position = position['position'] - quantity
                    
                    # If selling all or more than we have, reset position
                    if new_position <= 0:
                        position['position'] = 0
                        position['marketValue'] = 0
                    else:
                        position['position'] = new_position
                        position['marketPrice'] = price  # Update to latest price
                        position['marketValue'] = position['position'] * position['marketPrice']
                    
                    # Update cash balance
                    cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'CashBalance_BASE']
                    
                    # Update in account_info
                    if 'data' in updated_account and 'account_info' in updated_account['data']:
                        for key in cash_keys:
                            if key in updated_account['data']['account_info']:
                                current_cash = float(updated_account['data']['account_info'][key])
                                updated_account['data']['account_info'][key] = str(current_cash + order_value)
                    
                    # Update in summary
                    if 'summary' in updated_account:
                        for key in cash_keys:
                            if key in updated_account['summary']:
                                current_cash = float(updated_account['summary'][key])
                                updated_account['summary'][key] = str(current_cash + order_value)
        
        # Update total values based on positions
        position_value = 0
        for key, pos in updated_account['positions'].items():
            if isinstance(pos, dict) and 'marketValue' in pos:
                position_value += pos['marketValue']
        
        # Get cash value
        cash_value = 0
        if 'data' in updated_account and 'account_info' in updated_account['data']:
            if 'TotalCashValue_SGD' in updated_account['data']['account_info']:
                cash_value = float(updated_account['data']['account_info']['TotalCashValue_SGD'])
        
        # Update total portfolio value
        if 'data' in updated_account and 'account_info' in updated_account['data']:
            total_value = cash_value + position_value
            
            for key in ['NetLiquidation_SGD', 'EquityWithLoanValue_SGD']:
                if key in updated_account['data']['account_info']:
                    updated_account['data']['account_info'][key] = str(total_value)
        
        if 'summary' in updated_account:
            for key in ['NetLiquidation_SGD', 'EquityWithLoanValue_SGD']:
                if key in updated_account['summary']:
                    updated_account['summary'][key] = str(cash_value + position_value)
        
        return updated_account
    
    except Exception as e:
        logger.error(f"Error updating account with orders: {e}")
        return account_data