import os
import logging
import pandas as pd
import numpy as np
import json
from datetime import datetime
import time

# Import IBKR API components
from ibapi.contract import Contract
from ibapi.order import Order
from ibapi.common import BarData

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("investment_manager.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class InvestmentManager:
    """
    Investment Manager class for handling the investment allocation logic (Milestone 2)
    """
    
    def __init__(self, portfolio_manager):
        """
        Initialize the investment manager
        
        Args:
            portfolio_manager: Instance of PortfolioManager
        """
        self.portfolio_manager = portfolio_manager
        self.ibkr = portfolio_manager.ibkr
        self.config = portfolio_manager.config
        
        # Additional configuration for investment manager
        self.investment_config = {
            'order_log_path': os.path.join(self.config['log_dir'], 'orders.csv'),
            'market_data_cache': {},
            'market_data_timeout': 300,  # Cache market data for 5 minutes
            'rebalance_threshold': 0.05  # 5% threshold for rebalancing
        }
        
        # Ensure directories exist
        os.makedirs(os.path.dirname(self.investment_config['order_log_path']), exist_ok=True)
    
    def handle_excess_cash_investment(self, excess_cash):
        """
        Handle investment of excess cash according to investment portfolio structure
        
        Args:
            excess_cash: Amount of cash to invest
            
        Returns:
            dict: Results of investment allocation
        """
        logger.info(f"Handling investment of {excess_cash} excess cash")
        
        # Load investment portfolio if not already loaded
        if not self.portfolio_manager.investment_portfolio:
            self.portfolio_manager.load_portfolio_allocations()
            
        if not self.portfolio_manager.investment_portfolio:
            logger.error("Investment portfolio allocation not available")
            return {'error': 'Investment portfolio allocation not available'}
        
        # Get current positions in investment account
        if not self.portfolio_manager.investment_account:
            self.portfolio_manager.load_account_info()
            
        # Get total asset value in investment account
        account_info = self.portfolio_manager.investment_account['data']['account_info']
        
        # Look for portfolio value in SGD
        value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
        
        total_value = None
        for key in value_keys:
            if key in account_info:
                total_value = float(account_info[key])
                logger.info(f"Found portfolio value using {key}: {total_value}")
                break
                
        if total_value is None:
            logger.error(f"Portfolio value not found in account info: {account_info.keys()}")
            return {'error': 'Portfolio value not found'}
        
        # New total value after adding excess cash
        new_total_value = total_value + excess_cash
        logger.info(f"Current portfolio value: {total_value}, new value after cash: {new_total_value}")
        
        # Calculate target allocation amounts
        allocation_plan = self._calculate_target_allocation(new_total_value)
        
        # Get current positions and market prices
        current_positions = self._get_current_positions()
        
        # Calculate orders needed to achieve target allocation
        orders = self._calculate_orders(allocation_plan, current_positions, excess_cash)
        
        # Generate order sheets
        order_sheets = self._generate_order_sheets(orders)
        
        # Execute orders
        execution_results = self._execute_orders(order_sheets)
        
        return {
            'status': 'Investment plan executed',
            'allocation_plan': allocation_plan,
            'orders': orders,
            'execution_results': execution_results
        }
    
    def _calculate_target_allocation(self, total_value):
        """
        Calculate target allocation amounts based on portfolio structure
        
        Args:
            total_value: Total portfolio value including new cash
            
        Returns:
            dict: Target allocation amounts by instrument
        """
        logger.info(f"Calculating target allocation for {total_value} total value")
        
        investment_portfolio = self.portfolio_manager.investment_portfolio
        allocation_plan = {}
        
        # Calculate allocation by strategy
        for strategy, instruments in investment_portfolio.items():
            # Assume equal weighting of strategies for now
            # In a real implementation, each strategy would have its own weight
            strategy_weight = 1.0 / len(investment_portfolio)
            strategy_value = total_value * strategy_weight
            
            allocation_plan[strategy] = {
                'target_value': strategy_value,
                'instruments': {}
            }
            
            # Calculate allocation by instrument within strategy
            for instrument, details in instruments.items():
                instrument_value = strategy_value * details['target_percentage']
                
                allocation_plan[strategy]['instruments'][instrument] = {
                    'target_value': instrument_value,
                    'instrument_type': details['instrument_type'],
                    'exchange': details['exchange']
                }
        
        return allocation_plan
    
    def _get_current_positions(self):
        """
        Get current positions and market prices
        
        Returns:
            dict: Current positions and values
        """
        logger.info("Getting current positions and market prices")
        
        positions = self.portfolio_manager.investment_account['positions']
        current_positions = {}
        
        # Process positions to get current values
        for key, position in positions.items():
            parts = key.split('_')
            if len(parts) >= 2:
                symbol = parts[0]
                secType = parts[1]
                
                # Get current market price
                contract = position['contract']
                market_price = self._get_market_price(contract)
                
                current_positions[symbol] = {
                    'symbol': symbol,
                    'secType': secType,
                    'position': position['position'],
                    'avgCost': position['avgCost'] if 'avgCost' in position else 0,
                    'marketPrice': market_price,
                    'marketValue': position['position'] * market_price,
                    'contract': contract
                }
        
        return current_positions
    
    def _get_market_price(self, contract, force_refresh=False):
        """
        Get current market price for a contract
        
        Args:
            contract: Contract object
            force_refresh: Whether to force refresh market data
            
        Returns:
            float: Market price
        """
        contract_key = f"{contract.symbol}_{contract.secType}_{contract.exchange}"
        
        # Check cache for market data
        if not force_refresh and contract_key in self.investment_config['market_data_cache']:
            cache_entry = self.investment_config['market_data_cache'][contract_key]
            cache_time = cache_entry['timestamp']
            
            # Use cache if not expired
            if time.time() - cache_time < self.investment_config['market_data_timeout']:
                return cache_entry['price']
        
        # Request market data from IBKR
        # For demo purposes, just return a simulated price
        # In actual implementation, use self.ibkr.reqMktData() 
        # and wait for response in tickPrice callback
        
        # Simulate market price based on contract details
        price = 100.0  # Default price
        
        if contract.secType == 'STK':
            price = 100.0 + (hash(contract.symbol) % 900)  # Range: 100-1000
        elif contract.secType == 'ETF':
            price = 50.0 + (hash(contract.symbol) % 450)   # Range: 50-500
        elif contract.secType == 'FUT':
            price = 1000.0 + (hash(contract.symbol) % 9000)  # Range: 1000-10000
        
        # Cache the price
        self.investment_config['market_data_cache'][contract_key] = {
            'price': price,
            'timestamp': time.time()
        }
        
        return price
    
    def _calculate_orders(self, allocation_plan, current_positions, available_cash):
        """
        Calculate orders needed to achieve target allocation
        
        Args:
            allocation_plan: Target allocation
            current_positions: Current positions
            available_cash: Cash available for investment
            
        Returns:
            list: Orders to execute
        """
        logger.info("Calculating orders to achieve target allocation")
        
        orders = []
        remaining_cash = available_cash
        
        # Flatten allocation plan for easier processing
        flattened_allocation = {}
        for strategy, strategy_info in allocation_plan.items():
            for instrument, details in strategy_info['instruments'].items():
                flattened_allocation[instrument] = {
                    'strategy': strategy,
                    'target_value': details['target_value'],
                    'instrument_type': details['instrument_type'],
                    'exchange': details['exchange']
                }
        
        # Calculate adjustments needed for each position
        for instrument, target in flattened_allocation.items():
            current_value = 0
            current_position = 0
            market_price = 0
            
            # Check if we already have this position
            if instrument in current_positions:
                pos_info = current_positions[instrument]
                current_position = pos_info['position']
                market_price = pos_info['marketPrice']
                current_value = current_position * market_price
            else:
                # Create a dummy contract to get market price
                contract = Contract()
                contract.symbol = instrument
                contract.secType = target['instrument_type']
                contract.exchange = target['exchange']
                contract.currency = "SGD"  # Assuming SGD as currency
                
                market_price = self._get_market_price(contract)
            
            # Calculate value difference
            value_diff = target['target_value'] - current_value
            
            # Skip small adjustments
            if abs(value_diff) < target['target_value'] * self.investment_config['rebalance_threshold']:
                continue
                
            # Calculate quantity to trade
            if market_price > 0:
                qty = int(value_diff / market_price)  # Round down to nearest whole number
                
                # Skip if quantity is too small
                if qty == 0:
                    continue
                    
                # Check if we have enough cash for buy orders
                order_value = qty * market_price
                if qty > 0 and order_value > remaining_cash:
                    # Adjust quantity based on available cash
                    qty = int(remaining_cash / market_price)
                    if qty == 0:
                        continue
                    order_value = qty * market_price
                
                # Update remaining cash
                if qty > 0:  # Buy order
                    remaining_cash -= order_value
                else:  # Sell order
                    remaining_cash += abs(order_value)
                
                # Create contract for order
                contract = Contract()
                contract.symbol = instrument
                contract.secType = target['instrument_type']
                contract.exchange = target['exchange']
                contract.currency = "SGD"  # Assuming SGD as currency
                
                # Create order details
                order = {
                    'contract': contract,
                    'action': 'BUY' if qty > 0 else 'SELL',
                    'quantity': abs(qty),
                    'order_type': 'MKT',  # Market order
                    'strategy': target['strategy']
                }
                
                orders.append(order)
        
        logger.info(f"Calculated {len(orders)} orders, remaining cash: {remaining_cash}")
        return orders
    
    def _generate_order_sheets(self, orders):
        """
        Generate order sheets for submission to IBKR
        
        Args:
            orders: List of orders to execute
            
        Returns:
            list: Order sheets with IBKR API compatible orders
        """
        logger.info(f"Generating order sheets for {len(orders)} orders")
        
        order_sheets = []
        
        for order_data in orders:
            # Create IBKR order object
            contract = order_data['contract']
            
            ibkr_order = Order()
            ibkr_order.action = order_data['action']
            ibkr_order.totalQuantity = order_data['quantity']
            ibkr_order.orderType = order_data['order_type']
            
            # For market orders, no price needed
            # For limit orders, would set ibkr_order.lmtPrice
            
            order_sheet = {
                'contract': contract,
                'order': ibkr_order,
                'strategy': order_data['strategy']
            }
            
            order_sheets.append(order_sheet)
            
            # Log order details
            order_log = {
                'timestamp': datetime.now().isoformat(),
                'symbol': contract.symbol,
                'secType': contract.secType,
                'exchange': contract.exchange,
                'action': ibkr_order.action,
                'quantity': ibkr_order.totalQuantity,
                'order_type': ibkr_order.orderType,
                'strategy': order_data['strategy']
            }
            
            # Append to order log file
            df = pd.DataFrame([order_log])
            if os.path.exists(self.investment_config['order_log_path']):
                df.to_csv(self.investment_config['order_log_path'], mode='a', header=False, index=False)
            else:
                df.to_csv(self.investment_config['order_log_path'], index=False)
        
        return order_sheets
    
    def _execute_orders(self, order_sheets):
        """
        Execute orders via IBKR API
        
        Args:
            order_sheets: List of order sheets
            
        Returns:
            list: Execution results
        """
        logger.info(f"Executing {len(order_sheets)} orders")
        
        execution_results = []
        
        # In a real implementation, these would be submitted via IBKR API
        # For demonstration, just log the orders
        
        for i, order_sheet in enumerate(order_sheets):
            contract = order_sheet['contract']
            order = order_sheet['order']
            
            # In real implementation:
            # order_id = self.ibkr.next_order_id
            # self.ibkr.next_order_id += 1
            # self.ibkr.placeOrder(order_id, contract, order)
            
            # For demo, simulate execution
            execution_result = {
                'order_id': i + 1000,  # Simulated order ID
                'symbol': contract.symbol,
                'action': order.action,
                'quantity': order.totalQuantity,
                'status': 'Filled',  # Simulated fill
                'fill_price': self._get_market_price(contract),
                'time': datetime.now().isoformat()
            }
            
            execution_results.append(execution_result)
            
            # In real implementation, would wait for orderStatus callbacks
            
        return execution_results
    
    def rebalance_portfolio(self):
        """
        Rebalance the investment portfolio
        
        This function:
        1. Checks current positions
        2. Calculates target allocations
        3. Generates and executes orders to achieve target allocation
        
        Returns:
            dict: Results of rebalancing
        """
        logger.info("Starting portfolio rebalancing process")
        
        # Load account info if not already loaded
        if not self.portfolio_manager.investment_account:
            self.portfolio_manager.load_account_info()
        
        # Get account value
        account_info = self.portfolio_manager.investment_account['data']['account_info']
        
        # Look for portfolio value in SGD
        value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
        
        total_value = None
        for key in value_keys:
            if key in account_info:
                total_value = float(account_info[key])
                logger.info(f"Found portfolio value using {key}: {total_value}")
                break
                
        if total_value is None:
            logger.error(f"Portfolio value not found in account info: {account_info.keys()}")
            return {'error': 'Portfolio value not found'}
        
        # Calculate target allocation
        allocation_plan = self._calculate_target_allocation(total_value)
        
        # Get current positions
        current_positions = self._get_current_positions()
        
        # Calculate orders needed (assuming no new cash)
        orders = self._calculate_orders(allocation_plan, current_positions, 0)
        
        # If no orders needed, portfolio is balanced
        if not orders:
            logger.info("Portfolio is already balanced within threshold. No orders needed.")
            return {
                'status': 'Portfolio balanced',
                'allocation_plan': allocation_plan,
                'orders': []
            }
        
        # Generate order sheets
        order_sheets = self._generate_order_sheets(orders)
        
        # Execute orders
        execution_results = self._execute_orders(order_sheets)
        
        return {
            'status': 'Portfolio rebalanced',
            'allocation_plan': allocation_plan,
            'orders': orders,
            'execution_results': execution_results
        }