import os
import logging
import pandas as pd
import time
from datetime import datetime
from ibapi.contract import Contract
from ibapi.order import Order

logger = logging.getLogger(__name__)

class InvestmentManager:
    
    def __init__(self, ibkr_client):
        """
        Initialize the investment manager
        
        Args:
            ibkr_client: Instance of IBKRApp
        """
        # IBKR client connection
        self.ibkr = ibkr_client
        self.investment_account_id = None  # Will be set from outside
        
        # Storage for account/portfolio data
        self.investment_account = None
        self.investment_portfolio = None
        
        # NEW: Order persistence and cash reservation
        self.pending_orders = []  # Track unfulfilled orders
        self.reserved_cash = 0.0  # Cash reserved for pending orders
        self.order_buffer = 1.05  # 5% buffer for price fluctuations
        
        # Config is now internal to this class
        self.config = {
            'log_dir': 'logs'
        }
        
        # Additional configuration for investment manager
        self.investment_config = {
            'order_log_path': os.path.join(self.config.get('log_dir', './logs'), 'orders.csv'),
            'market_data_cache': {},
            'market_data_timeout': 300,  # Cache market data for 5 minutes
            'rebalance_threshold': 0.05,  # 5% threshold for rebalancing
            'max_retry_attempts': 3,  # Maximum number of retry attempts for orders
            'use_delayed_market_data': True  # Accept delayed market data
        }
        
        # Ensure directories exist
        os.makedirs(os.path.dirname(self.investment_config['order_log_path']), exist_ok=True)
    
    def load_portfolio_allocations(self, file_path=None):
        """Load investment portfolio allocation from CSV file"""
        if not file_path:
            file_path = os.path.join('config', 'portfolio_allocation.csv')
            
        try:
            if os.path.exists(file_path):
                df = pd.read_csv(file_path)
                
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
                logger.info(f"Loaded portfolio allocations: {len(investment_strategies)} investment strategies")
                return True
            else:
                logger.error(f"Portfolio allocation file not found: {file_path}")
                return False
        except Exception as e:
            logger.error(f"Error loading portfolio allocations: {e}", exc_info=True)
            return False
    
    def load_account_info(self):
        """Load account information from IBKR"""
        if not self.investment_account_id:
            logger.error("Investment account ID not set")
            return None
            
        logger.info(f"Loading account information for {self.investment_account_id}")
        
        try:
            # Request account summary
            account_summary = self.ibkr.request_account_summary()
            
            # Request positions
            positions = self.ibkr.request_positions()
            
            # Request account updates
            account_data = self.ibkr.request_account_updates(self.investment_account_id)
            
            # Store account info
            self.investment_account = {
                'id': self.investment_account_id,
                'summary': account_summary.get(self.investment_account_id, {}),
                'positions': positions.get(self.investment_account_id, {}),
                'data': {
                    'account_info': account_data
                }
            }
            
            return self.investment_account
        except Exception as e:
            logger.error(f"Error loading account info: {e}", exc_info=True)
            
            # Create dummy account if loading fails
            self.investment_account = {
                'id': self.investment_account_id,
                'data': {
                    'account_info': {
                        'NetLiquidation_SGD': '100000',
                        'AvailableFunds_SGD': '10000'
                    }
                },
                'positions': {}
            }
            
            return self.investment_account
    
    def handle_excess_cash_investment(self, excess_cash):
        """
        Enhanced method to handle investment of excess cash according to portfolio allocation.
        Maintains persistent orders and cash reservation across scheduler events.

        Args:
            excess_cash: Amount of cash to invest.

        Returns:
            dict: Results of investment allocation.
        """
        logger.info(f"Handling investment of {excess_cash} excess cash")

        # Ensure we have account info and portfolio allocations
        if not self.investment_account:
            self.load_account_info()

        if not self.investment_portfolio:
            self.load_portfolio_allocations()

        # Calculate total available cash (new cash + any released from expired orders)
        total_available_cash = excess_cash

        # STEP 1: Process pending orders first (retry mechanism)
        retry_results = []
        updated_pending_orders = []
        released_cash = 0.0

        if self.pending_orders:
            logger.info(f"Processing {len(self.pending_orders)} pending orders first")

            for order_item in self.pending_orders:
                # Check if order has expired (exceeded max retry attempts)
                if order_item.get('retry_count', 0) >= self.investment_config['max_retry_attempts']:
                    logger.warning(f"Order {order_item['order_id']} expired after {order_item['retry_count']} attempts")

                    # Release reserved cash for expired buy orders
                    if order_item['action'] == 'BUY':
                        reserved_amount = order_item['quantity'] * order_item['price'] * self.order_buffer
                        released_cash += reserved_amount
                        logger.info(f"Released {reserved_amount} from expired order")

                    continue  # Skip this order

                # Update market price and adjust quantity to maintain target allocation
                updated_order = self._adjust_order_for_current_price(order_item)

                # Increment retry count
                updated_order['retry_count'] = order_item.get('retry_count', 0) + 1

                # Generate order sheet for this single order
                order_sheet = self._generate_order_sheet(updated_order)

                # Try to execute the order
                execution_result = self._execute_orders([order_sheet])[0]
                retry_results.append(execution_result)

                # If order failed, keep it in pending list
                if execution_result['status'] != 'Submitted':
                    updated_pending_orders.append(updated_order)

        # Update available cash with any released from expired orders
        total_available_cash += released_cash

        # STEP 2: Calculate target allocation
        # Get total asset value in investment account
        account_info = self.investment_account['data']['account_info']

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
        new_total_value = total_value + total_available_cash
        logger.info(f"Current portfolio value: {total_value}, new value after cash: {new_total_value}")

        # Calculate target allocation amounts
        allocation_plan = self._calculate_target_allocation(new_total_value)

        # STEP 3: Get current positions and calculate new orders
        current_positions = self._get_current_positions()

        # Calculate new orders, accounting for reserved cash
        effective_cash = total_available_cash - self._calculate_reserved_cash(updated_pending_orders)
        logger.info(f"Effective available cash after reservations: {effective_cash}")

        # We only calculate new orders if we have positive effective cash
        new_orders = []
        if effective_cash > 0:
            new_orders = self._calculate_orders(allocation_plan, current_positions, effective_cash, updated_pending_orders)

        # STEP 4: Execute new orders
        new_order_sheets = self._generate_order_sheets(new_orders)
        new_execution_results = self._execute_orders(new_order_sheets)

        # STEP 5: Update pending orders list with any failed new orders
        for i, result in enumerate(new_execution_results):
            if result['status'] != 'Submitted':
                # Add to pending orders with retry tracking
                order_data = new_orders[i].copy()
                order_data['retry_count'] = 1
                order_data['order_id'] = result.get('order_id', f"pending_{int(time.time())}")
                updated_pending_orders.append(order_data)

        # Update class state with new pending orders
        self.pending_orders = updated_pending_orders

        # Calculate and update reserved cash
        self.reserved_cash = self._calculate_reserved_cash(self.pending_orders)

        # Combine all execution results
        all_execution_results = retry_results + new_execution_results

        return {
            'status': 'Investment plan executed',
            'allocation_plan': allocation_plan,
            'orders': new_orders,
            'retry_orders': len(retry_results),
            'execution_results': all_execution_results,
            'pending_orders': len(self.pending_orders),
            'reserved_cash': self.reserved_cash
        }
    
    def _adjust_order_for_current_price(self, order_item):
        """
        Adjust order quantity based on current market price to maintain target allocation
        
        Args:
            order_item: Order to adjust
            
        Returns:
            dict: Updated order
        """
        updated_order = order_item.copy()
        
        # Get current market price
        contract = updated_order['contract']
        current_price = self._get_market_price(contract)
        
        # Get original target value
        original_value = updated_order.get('target_value', updated_order['quantity'] * updated_order.get('price', 0))
        
        # If original price is not stored, store current as original
        if 'price' not in updated_order:
            updated_order['price'] = current_price
        
        # Adjust quantity to maintain target value
        if current_price > 0 and original_value > 0:
            new_quantity = int(original_value / current_price)
            
            # Only update if quantity has changed
            if new_quantity != updated_order['quantity']:
                logger.info(f"Adjusting order for {contract.symbol}: quantity {updated_order['quantity']} -> {new_quantity} (price: {updated_order.get('price', 0)} -> {current_price})")
                updated_order['quantity'] = max(1, new_quantity)  # Ensure at least 1 share
                updated_order['price'] = current_price
        
        return updated_order
    
    def _calculate_reserved_cash(self, pending_orders):
        """
        Calculate total cash reserved for pending buy orders
        
        Args:
            pending_orders: List of pending orders
            
        Returns:
            float: Total reserved cash
        """
        reserved = 0.0
        
        for order in pending_orders:
            if order['action'] == 'BUY':
                # Use stored price or get current price
                price = order.get('price', self._get_market_price(order['contract']))
                reserved += order['quantity'] * price * self.order_buffer
        
        return reserved
    
    def _calculate_target_allocation(self, total_value):
        """
        Calculate target allocation amounts based on portfolio structure
        
        Args:
            total_value: Total portfolio value including new cash
            
        Returns:
            dict: Target allocation amounts by instrument
        """
        logger.info(f"Calculating target allocation for {total_value} total value")
        
        if not self.investment_portfolio:
            logger.error("No investment portfolio allocation available")
            return {}
        
        allocation_plan = {}
        
        # Calculate allocation by strategy
        for strategy, instruments in self.investment_portfolio.items():
            # Assume equal weighting of strategies for now
            strategy_weight = 1.0 / len(self.investment_portfolio)
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
        Get current positions and market prices with robust error handling
        
        Returns:
            dict: Current positions and values
        """
        logger.info("Getting current positions and market prices")
        
        if not self.investment_account:
            logger.error("Investment account information not loaded")
            return {}
        
        positions = self.investment_account['positions']
        
        # Add check to ensure positions is a dictionary
        if not isinstance(positions, dict):
            logger.error(f"Positions data is not a dictionary: {type(positions)}")
            return {}
            
        current_positions = {}
        
        # Process positions to get current values
        for key, position in positions.items():
            try:
                # Make sure position is a dictionary before accessing it
                if not isinstance(position, dict):
                    logger.warning(f"Position for {key} is not a dictionary, skipping: {position}")
                    continue
                    
                parts = key.split('_')
                if len(parts) >= 2:
                    symbol = parts[0]
                    secType = parts[1]
                    
                    # Check that contract exists and is an object
                    if 'contract' not in position:
                        logger.warning(f"No contract information for {key}, skipping")
                        continue
                        
                    contract = position['contract']
                    market_price = self._get_market_price(contract)
                    
                    # Make sure we have a valid position value before calculating market value
                    if 'position' not in position:
                        logger.warning(f"No position quantity for {key}, skipping")
                        continue
                        
                    current_positions[symbol] = {
                        'symbol': symbol,
                        'secType': secType,
                        'position': position['position'],
                        'avgCost': position.get('avgCost', 0),
                        'marketPrice': market_price,
                        'marketValue': position['position'] * market_price,
                        'contract': contract
                    }
            except Exception as e:
                logger.error(f"Error processing position for {key}: {e}")
                continue
        
        return current_positions
    
    def _get_market_price(self, contract, force_refresh=False):
        """
        Get market price using delayed market data
        
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
                logger.info(f"Using cached price for {contract.symbol}: ${cache_entry['price']:.2f}")
                return cache_entry['price']
        
        # Set contract currency to USD for US stocks
        if contract.exchange == "SMART" or contract.exchange == "NYSE" or contract.exchange == "NASDAQ":
            contract.currency = "USD"
        
        # Request delayed market data from IBKR
        try:
            # Make sure we're not using spaces in secType
            contract.secType = contract.secType.strip()
            
            logger.info(f"Requesting delayed market price for {contract.symbol} ({contract.secType}) on {contract.exchange}")
            
            # Always use delayed data for consistency
            if hasattr(self.ibkr, 'client') and hasattr(self.ibkr.client, 'reqMarketDataType'):
                # Set to always use delayed data (4 = delayed data + frozen)
                self.ibkr.client.reqMarketDataType(4)
            
            # Request market data
            price = self.ibkr.request_market_data(contract)
            
            # Log the received price
            if price is not None and price > 0:
                logger.info(f"Received delayed price for {contract.symbol}: ${price:.2f}")
                
                # Cache the price
                self.investment_config['market_data_cache'][contract_key] = {
                    'price': price,
                    'timestamp': time.time(),
                    'delayed': True
                }
                
                return price
            else:
                logger.warning(f"Received invalid delayed price for {contract.symbol}: {price}")
                raise Exception(f"Could not retrieve valid delayed price for {contract.symbol}")
                
        except Exception as e:
            logger.error(f"Error getting delayed price for {contract.symbol}: {e}")
            
            # If we have a cached price, use it even if expired
            if contract_key in self.investment_config['market_data_cache']:
                cache_price = self.investment_config['market_data_cache'][contract_key]['price']
                logger.info(f"Using expired cached price for {contract.symbol}: ${cache_price:.2f}")
                return cache_price
            
            # Only use simulated price as absolute last resort
            import random
            base_price = 100.0 + (hash(contract.symbol) % 900)  # Range: 100-1000
            variation = random.uniform(-5, 5)  # Add some randomness
            price = base_price + variation
            logger.warning(f"Using simulated price for {contract.symbol} as last resort: ${price:.2f}")
            
            # Cache the simulated price
            self.investment_config['market_data_cache'][contract_key] = {
                'price': price,
                'timestamp': time.time(),
                'delayed': True,
                'simulated': True
            }
            
            return price

    def _create_order(self, action, quantity, order_type="MKT"):
        """
        Create a properly configured order object
        
        Args:
            action: "BUY" or "SELL"
            quantity: Number of shares/contracts
            order_type: Order type (e.g., "MKT", "LMT")
            
        Returns:
            Order: Configured order object
        """
        from ibapi.order import Order
        
        order = Order()
        order.action = action
        order.totalQuantity = quantity
        order.orderType = order_type
        
        # Disable attributes that might cause rejection
        order.eTradeOnly = False
        order.firmQuoteOnly = False
        
        # For US market orders, these settings may help
        if order_type == "MKT":
            order.tif = "DAY"  # Time in force
            order.outsideRth = False  # Only during regular trading hours
        
        return order
    
    def _calculate_orders(self, allocation_plan, current_positions, available_cash, pending_orders):
        """
        Calculate orders needed to achieve target allocation with proportional cash allocation.
        Considers both current positions and pending orders to avoid redundant purchases.

        Args:
            allocation_plan: Target allocation plan.
            current_positions: Current positions in the portfolio.
            available_cash: Cash available for investment.
            pending_orders: List of pending orders that are assumed to be fulfilled.

        Returns:
            list: Orders to execute.
        """
        logger.info(f"========== CALCULATING ORDERS ==========")
        logger.info(f"Available cash: ${available_cash:.2f}")

        # Log allocation plan details
        logger.info("Target allocation plan:")
        for strategy, strategy_info in allocation_plan.items():
            logger.info(f"  Strategy: {strategy}, Target value: ${strategy_info['target_value']:.2f}")
            for instrument, details in strategy_info['instruments'].items():
                logger.info(f"    {instrument} ({details['instrument_type']} on {details['exchange']}): ${details['target_value']:.2f}")

        # Combine current positions and pending orders
        effective_positions = current_positions.copy()
        for order in pending_orders:
            symbol = order['contract'].symbol
            if symbol in effective_positions:
                effective_positions[symbol]['position'] += order['quantity']
            else:
                effective_positions[symbol] = {
                    'position': order['quantity'],
                    'marketPrice': order['price'],
                    'marketValue': order['quantity'] * order['price']
                }

        # Log effective positions (current + pending)
        logger.info("Effective positions (current + pending):")
        if effective_positions:
            for symbol, position in effective_positions.items():
                logger.info(f"  {symbol}: {position['position']} shares at ${position['marketPrice']:.2f}, value: ${position['marketValue']:.2f}")
        else:
            logger.info("  No effective positions")

        # Flatten allocation plan for easier processing
        flattened_allocation = {}
        for strategy, strategy_info in allocation_plan.items():
            for instrument, details in strategy_info['instruments'].items():
                flattened_allocation[instrument] = {
                    'strategy': strategy,
                    'target_value': details['target_value'],
                    'instrument_type': details['instrument_type'].strip(),
                    'exchange': details['exchange']
                }

        # Calculate total target value
        total_target = sum(target['target_value'] for target in flattened_allocation.values())
        logger.info(f"Total target value: ${total_target:.2f}")

        # Allocate cash proportionally
        orders = []
        remaining_cash = available_cash

        for instrument, target in flattened_allocation.items():
            logger.info(f"  Evaluating {instrument} ({target['instrument_type']} on {target['exchange']}):")

            # Calculate current value (including pending orders)
            current_value = 0
            if instrument in effective_positions:
                pos_info = effective_positions[instrument]
                current_value = pos_info['marketValue']
                logger.info(f"    Current position: {pos_info['position']} shares at ${pos_info['marketPrice']:.2f} = ${current_value:.2f}")
            else:
                logger.info(f"    No current position")

            # Calculate value difference
            value_diff = target['target_value'] - current_value
            logger.info(f"    Target value: ${target['target_value']:.2f}")
            logger.info(f"    Value difference: ${value_diff:.2f}")

            # Skip if value difference is below threshold
            threshold = target['target_value'] * self.investment_config['rebalance_threshold']
            if abs(value_diff) < threshold:
                logger.info(f"    SKIPPING: Difference is below threshold (${threshold:.2f})")
                continue

            # Calculate proportion of cash to allocate
            allocation_ratio = target['target_value'] / total_target
            allocated_cash = available_cash * allocation_ratio
            logger.info(f"    Allocated cash: ${allocated_cash:.2f}")

            # Get market price
            contract = Contract()
            contract.symbol = instrument
            contract.secType = target['instrument_type']
            contract.exchange = target['exchange']
            contract.currency = "USD" if contract.exchange in ["SMART", "NYSE", "NASDAQ"] else "SGD"

            market_price = self._get_market_price(contract)
            if market_price is None:
                logger.warning(f"    SKIPPING: Could not retrieve valid price for {instrument}")
                continue

            logger.info(f"    Market price: ${market_price:.2f}")

            # Calculate quantity to buy
            if market_price > 0:
                qty = int(allocated_cash / market_price)
                if qty <= 0:
                    logger.info(f"    SKIPPING: Calculated quantity is zero")
                    continue

                # Check if we have enough cash
                order_value = qty * market_price
                if order_value > remaining_cash:
                    logger.info(f"    Adjusting quantity - insufficient cash. Need: ${order_value:.2f}, Have: ${remaining_cash:.2f}")
                    qty = int(remaining_cash / market_price)
                    if qty <= 0:
                        logger.info(f"    SKIPPING: Insufficient cash for even 1 share")
                        continue
                    order_value = qty * market_price

                # Log the final order decision
                action = 'BUY' if qty > 0 else 'SELL'
                logger.info(f"    ADDING ORDER: {action} {abs(qty)} shares at ~${market_price:.2f} = ${abs(qty * market_price):.2f}")

                # Update remaining cash
                remaining_cash -= order_value
                logger.info(f"    Remaining cash after order: ${remaining_cash:.2f}")

                # Create order details
                order = {
                    'contract': contract,
                    'action': action,
                    'quantity': abs(qty),
                    'order_type': 'MKT',
                    'strategy': target['strategy'],
                    'target_value': target['target_value'],
                    'current_value': current_value,
                    'price': market_price,
                    'exchange': target['exchange']
                }
                orders.append(order)

        logger.info(f"Order calculation complete: {len(orders)} orders, ${remaining_cash:.2f} cash remaining")
        return orders
    
    def _generate_order_sheets(self, orders):
        """
        Generate order sheets for submission to IBKR with detailed logging
        
        Args:
            orders: List of orders to execute
            
        Returns:
            list: Order sheets with IBKR API compatible orders
        """
        logger.info(f"========== GENERATING ORDER SHEETS ==========")
        logger.info(f"Processing {len(orders)} orders")
        
        # Log distribution of orders by exchange
        exchanges = {}
        for order in orders:
            exchange = order['exchange']
            if exchange not in exchanges:
                exchanges[exchange] = 0
            exchanges[exchange] += 1
        
        logger.info("Order distribution by exchange:")
        for exchange, count in exchanges.items():
            logger.info(f"  {exchange}: {count} orders")
        
        order_sheets = []
        
        for i, order_data in enumerate(orders):
            # Log detailed order info
            logger.info(f"Processing order {i+1}:")
            logger.info(f"  Symbol: {order_data['contract'].symbol}")
            logger.info(f"  Type: {order_data['contract'].secType}")
            logger.info(f"  Exchange: {order_data['exchange']}")
            logger.info(f"  Action: {order_data['action']}")
            logger.info(f"  Quantity: {order_data['quantity']}")
            logger.info(f"  Price: ${order_data['price']:.2f}")
            logger.info(f"  Total value: ${order_data['quantity'] * order_data['price']:.2f}")
            logger.info(f"  Strategy: {order_data['strategy']}")
            
            # Create IBKR order object
            contract = order_data['contract']
            
            # Fix any space issues in contract
            contract.secType = contract.secType.strip()
            
            # Set proper currency for US stocks
            if contract.exchange == "SMART" or contract.exchange == "NYSE" or contract.exchange == "NASDAQ":
                contract.currency = "USD"
            
            # Create the order
            ibkr_order = self._create_order(
                action=order_data['action'],
                quantity=order_data['quantity'],
                order_type=order_data.get('order_type', 'MKT')
            )
            
            order_sheet = {
                'contract': contract,
                'order': ibkr_order,
                'strategy': order_data['strategy']
            }
            
            order_sheets.append(order_sheet)
            
            # Log order details to file
            order_log = {
                'timestamp': datetime.now().isoformat(),
                'symbol': contract.symbol,
                'secType': contract.secType,
                'exchange': contract.exchange,
                'action': order_data['action'],
                'quantity': order_data['quantity'],
                'price': order_data['price'],
                'value': order_data['quantity'] * order_data['price'],
                'strategy': order_data['strategy']
            }

            order_log_fields = [
                'timestamp', 'symbol', 'secType', 'exchange', 
                'action', 'quantity', 'price', 'value', 'strategy'
            ]
            
            # Append to order log file
            try:
                df = pd.DataFrame([order_log])
                
                # Ensure all fields are in the dataframe in the correct order
                df = df[order_log_fields]
                
                if os.path.exists(self.investment_config['order_log_path']):
                    # Check if file is empty
                    file_empty = os.path.getsize(self.investment_config['order_log_path']) == 0
                    
                    # If file exists and is not empty, append without header
                    if not file_empty:
                        df.to_csv(self.investment_config['order_log_path'], mode='a', header=False, index=False)
                    else:
                        # If file exists but is empty, write with header
                        df.to_csv(self.investment_config['order_log_path'], index=False)
                else:
                    # If file doesn't exist, create with header
                    df.to_csv(self.investment_config['order_log_path'], index=False)
            except Exception as e:
                logger.error(f"Error writing to order log: {e}")
        
        logger.info(f"Generated {len(order_sheets)} order sheets")
        
        return order_sheets
    
    def _execute_orders(self, order_sheets):
        """
        Execute orders via IBKR API with enhanced error handling
        
        Args:
            order_sheets: List of order sheets
            
        Returns:
            list: Execution results
        """
        logger.info(f"Executing {len(order_sheets)} orders via IBKR API")
        
        execution_results = []
        
        for i, order_sheet in enumerate(order_sheets):
            contract = order_sheet['contract']
            order = order_sheet['order']
            
            try:
                # Get next valid order ID from IBKR client
                order_id = None
                
                # Different ways to get the next order ID depending on the IBKR client implementation
                if hasattr(self.ibkr, 'wrapper') and hasattr(self.ibkr.wrapper, 'next_order_id'):
                    order_id = self.ibkr.wrapper.next_order_id
                    self.ibkr.wrapper.next_order_id += 1
                elif hasattr(self.ibkr, 'next_order_id'):
                    order_id = self.ibkr.next_order_id
                    self.ibkr.next_order_id += 1
                else:
                    # If we can't get a valid order ID, generate one
                    order_id = int(time.time() * 1000) + i
                    logger.warning(f"Could not get next valid order ID, using generated ID: {order_id}")
                
                # Log the order details
                logger.info(f"Placing order #{order_id}: {contract.symbol} {order.action} {order.totalQuantity} {order.orderType}")
                
                # Place the order via IBKR API - find the right method on the IBKR client
                if hasattr(self.ibkr, 'placeOrder'):
                    # Direct method
                    self.ibkr.placeOrder(order_id, contract, order)
                elif hasattr(self.ibkr, 'client') and hasattr(self.ibkr.client, 'placeOrder'):
                    # Nested method
                    self.ibkr.client.placeOrder(order_id, contract, order)
                else:
                    raise Exception("Could not find placeOrder method on IBKR client")
                
                # Record execution result
                execution_result = {
                    'order_id': order_id,
                    'symbol': contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'status': 'Submitted',
                    'time': datetime.now().isoformat(),
                    'retry_count': order_sheet.get('metadata', {}).get('retry_count', 0)
                }
                
                execution_results.append(execution_result)
                
                # In a real-world scenario, you would listen for execution callbacks
                # For the demo, we'll wait a short time to allow TWS to process
                time.sleep(1)
                
            except Exception as e:
                logger.error(f"Error executing order for {contract.symbol}: {e}", exc_info=True)
                
                execution_result = {
                    'symbol': contract.symbol,
                    'action': order.action,
                    'quantity': order.totalQuantity,
                    'status': 'Error',
                    'error': str(e),
                    'time': datetime.now().isoformat(),
                    'retry_count': order_sheet.get('metadata', {}).get('retry_count', 0)
                }
                
                execution_results.append(execution_result)
        
        return execution_results
    
    def rebalance_portfolio(self):
        """
        Enhanced rebalance method that respects pending orders
        
        Returns:
            dict: Results of rebalancing
        """
        logger.info("Starting portfolio rebalancing process")
        
        # Ensure account info is loaded
        if not self.investment_account:
            self.load_account_info()
        
        # Get account value
        account_info = self.investment_account['data']['account_info']
        
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
        
        # Process pending orders first
        retry_results = []
        updated_pending_orders = []
        
        if self.pending_orders:
            logger.info(f"Processing {len(self.pending_orders)} pending orders before rebalancing")
            
            for order_item in self.pending_orders:
                # Check if order has expired
                if order_item.get('retry_count', 0) >= self.investment_config['max_retry_attempts']:
                    logger.warning(f"Order {order_item.get('order_id', 'unknown')} expired after {order_item['retry_count']} attempts")
                    continue  # Skip expired orders
                
                # Update market price and adjust quantity
                updated_order = self._adjust_order_for_current_price(order_item)
                
                # Increment retry count
                updated_order['retry_count'] = order_item.get('retry_count', 0) + 1
                
                # Generate order sheet
                order_sheet = self._generate_order_sheet(updated_order)
                
                # Try to execute the order
                execution_result = self._execute_orders([order_sheet])[0]
                retry_results.append(execution_result)
                
                # If order failed, keep it in pending list
                if execution_result['status'] != 'Submitted':
                    updated_pending_orders.append(updated_order)
        
        # Calculate target allocation
        allocation_plan = self._calculate_target_allocation(total_value)
        
        # Get current positions
        current_positions = self._get_current_positions()
        
        # Calculate remaining reserved cash
        reserved_cash = self._calculate_reserved_cash(updated_pending_orders)
        
        # Calculate new orders (with 0 new cash, just rebalancing)
        # But need to account for reserved cash
        effective_cash = max(0, float(account_info.get('AvailableFunds_USD', 0)) - reserved_cash)
        orders = self._calculate_orders(allocation_plan, current_positions, effective_cash)
        
        # If no new orders and no retry orders, portfolio is balanced
        if not orders and not retry_results:
            logger.info("Portfolio is already balanced within threshold. No orders needed.")
            # Still update pending orders state
            self.pending_orders = updated_pending_orders
            self.reserved_cash = reserved_cash
            
            return {
                'status': 'Portfolio balanced',
                'allocation_plan': allocation_plan,
                'orders': [],
                'retry_orders': len(retry_results),
                'pending_orders': len(self.pending_orders)
            }
        
        # Generate order sheets for new orders
        order_sheets = self._generate_order_sheets(orders)
        
        # Execute new orders
        execution_results = self._execute_orders(order_sheets)
        
        # Update pending orders list with failed orders
        for i, result in enumerate(execution_results):
            if result['status'] != 'Submitted':
                # Add to pending orders
                order_data = orders[i].copy()
                order_data['retry_count'] = 1
                order_data['order_id'] = result.get('order_id', f"pending_{int(time.time())}")
                updated_pending_orders.append(order_data)
        
        # Update class state
        self.pending_orders = updated_pending_orders
        self.reserved_cash = self._calculate_reserved_cash(self.pending_orders)
        
        # Combine execution results
        all_results = retry_results + execution_results
        
        return {
            'status': 'Portfolio rebalanced',
            'allocation_plan': allocation_plan,
            'orders': orders,
            'retry_orders': len(retry_results),
            'execution_results': all_results,
            'pending_orders': len(self.pending_orders),
            'reserved_cash': self.reserved_cash
        }
    
    def receive_cash_transfer(self, amount):
        """
        Update investment account with cash transferred from cash account
        
        Args:
            amount: Amount transferred
            
        Returns:
            bool: Success status
        """
        logger.info(f"Receiving cash transfer of {amount} into investment account")
        
        if not self.investment_account:
            self.load_account_info()
        
        try:
            # Update cash values in account info
            account_info = self.investment_account['data']['account_info']
            
            # Update available funds
            for key in ['AvailableFunds_SGD', 'AvailableFunds']:
                if key in account_info:
                    current_value = float(account_info[key])
                    account_info[key] = str(current_value + amount)
            
            # Update cash values
            for key in ['TotalCashValue_SGD', 'TotalCashValue']:
                if key in account_info:
                    current_value = float(account_info[key])
                    account_info[key] = str(current_value + amount)
            
            # Update total values
            for key in ['NetLiquidation_SGD', 'NetLiquidation']:
                if key in account_info:
                    current_value = float(account_info[key])
                    account_info[key] = str(current_value + amount)
            
            logger.info(f"Updated investment account with {amount} cash")
            return True
            
        except Exception as e:
            logger.error(f"Error updating investment account with cash transfer: {e}")
            return False
    
    def get_order_status(self):
        """
        Get current status of pending orders
        
        Returns:
            dict: Status information about pending orders
        """
        return {
            'pending_count': len(self.pending_orders),
            'reserved_cash': self.reserved_cash,
            'pending_orders': [{
                'symbol': order['contract'].symbol,
                'action': order['action'],
                'quantity': order['quantity'],
                'retry_count': order.get('retry_count', 0),
                'order_id': order.get('order_id', 'unknown')
            } for order in self.pending_orders]
        }
    
    def get_portfolio_allocation_status(self):
        """
        Get current status of portfolio allocation versus target
        
        Returns:
            dict: Portfolio allocation status
        """
        if not self.investment_account or not self.investment_portfolio:
            return {'error': 'Account or portfolio data not loaded'}
        
        try:
            # Get current positions
            current_positions = self._get_current_positions()
            
            # Get total portfolio value
            account_info = self.investment_account['data']['account_info']
            value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
            
            total_value = None
            for key in value_keys:
                if key in account_info:
                    total_value = float(account_info[key])
                    break
            
            if total_value is None or total_value == 0:
                return {'error': 'Portfolio value not found or zero'}
            
            # Calculate target allocation
            allocation_plan = self._calculate_target_allocation(total_value)
            
            # Flatten target allocation
            target_allocations = {}
            for strategy, strategy_info in allocation_plan.items():
                for instrument, details in strategy_info['instruments'].items():
                    target_allocations[instrument] = {
                        'target_value': details['target_value'],
                        'target_percentage': details['target_value'] / total_value
                    }
            
            # Calculate current allocation percentages
            current_allocations = {}
            for symbol, position in current_positions.items():
                market_value = position['marketValue']
                current_allocations[symbol] = {
                    'current_value': market_value,
                    'current_percentage': market_value / total_value
                }
            
            # Combine and calculate deviation
            allocation_status = {}
            
            # First, process all symbols in target allocation
            for symbol, target in target_allocations.items():
                status = {
                    'target_percentage': target['target_percentage'],
                    'target_value': target['target_value'],
                    'current_percentage': 0,
                    'current_value': 0,
                    'deviation': -target['target_percentage'],  # Initially assume 100% negative deviation
                    'deviation_percentage': -100  # Initially assume 100% negative deviation
                }
                
                # If we have this position, update with actual values
                if symbol in current_allocations:
                    current = current_allocations[symbol]
                    status['current_percentage'] = current['current_percentage']
                    status['current_value'] = current['current_value']
                    status['deviation'] = current['current_percentage'] - target['target_percentage']
                    
                    if target['target_percentage'] > 0:
                        status['deviation_percentage'] = (status['deviation'] / target['target_percentage']) * 100
                
                allocation_status[symbol] = status
            
            # Then, add any positions we have that aren't in the target allocation
            for symbol, current in current_allocations.items():
                if symbol not in allocation_status:
                    allocation_status[symbol] = {
                        'target_percentage': 0,
                        'target_value': 0,
                        'current_percentage': current['current_percentage'],
                        'current_value': current['current_value'],
                        'deviation': current['current_percentage'],  # 100% positive deviation
                        'deviation_percentage': float('inf')  # Infinite deviation percentage
                    }
            
            return {
                'total_value': total_value,
                'allocations': allocation_status,
                'cash_percentage': float(account_info.get('AvailableFunds_SGD', 0)) / total_value,
                'reserved_cash_percentage': self.reserved_cash / total_value if total_value > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error getting portfolio allocation status: {e}")
            return {'error': f"Failed to calculate allocation status: {str(e)}"}