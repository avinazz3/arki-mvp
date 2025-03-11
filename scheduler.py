import os
import logging
import time
import json
import datetime
import schedule
from pathlib import Path

# Import our modules
from ibkr_client import IBKRApp
from portfolio_manager import PortfolioManager
from investment_manager import InvestmentManager

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class PortfolioScheduler:
    """
    Scheduler for portfolio management tasks
    
    This class handles the scheduling of portfolio management tasks:
    - Cash management
    - Investment allocation
    - Portfolio rebalancing
    """
    
    def __init__(self, config_path="config"):
        """
        Initialize the scheduler
        
        Args:
            config_path: Path to configuration files
        """
        self.config_path = config_path
        self.ibkr_app = None
        self.portfolio_manager = None
        self.investment_manager = None
        
        # Load scheduler configuration
        self.config = self._load_config()
        
        # Initialize execution state
        self.last_execution = {}
        self.is_running = False
        
        # Ensure state directory exists
        os.makedirs(os.path.join(config_path, 'state'), exist_ok=True)
        
        # Load execution state
        self._load_state()
    
    def _load_config(self):
        """Load scheduler configuration"""
        
        config_file = os.path.join(self.config_path, 'scheduler_config.json')
        default_config = {
            'ibkr': {
                'host': '127.0.0.1',
                'port': 7497,  # 7497 for TWS demo, 4002 for Gateway demo
                'client_id': 1
            },
            'schedule': {
                'cash_management': {
                    'time': ['10:00', '14:00'],  # Run twice daily
                    'days': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                },
                'portfolio_rebalance': {
                    'time': ['10:30', '14:30'],  # Run twice daily, after cash management
                    'days': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
                }
            }
        }
        
        # Create default config if it doesn't exist
        if not os.path.exists(config_file):
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Created default scheduler configuration at {config_file}")
            return default_config
        
        # Load existing config
        try:
            with open(config_file, 'r') as f:
                config = json.load(f)
            logger.info(f"Loaded scheduler configuration from {config_file}")
            return config
        except Exception as e:
            logger.error(f"Error loading scheduler configuration: {e}", exc_info=True)
            return default_config
    
    def _load_state(self):
        """Load execution state from file"""
        
        state_file = os.path.join(self.config_path, 'state', 'scheduler_state.json')
        
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r') as f:
                    self.last_execution = json.load(f)
                logger.info(f"Loaded scheduler state from {state_file}")
            except Exception as e:
                logger.error(f"Error loading scheduler state: {e}", exc_info=True)
                self.last_execution = {}
    
    def _save_state(self):
        """Save execution state to file"""
        
        state_file = os.path.join(self.config_path, 'state', 'scheduler_state.json')
        
        try:
            with open(state_file, 'w') as f:
                json.dump(self.last_execution, f, indent=4)
            logger.info(f"Saved scheduler state to {state_file}")
        except Exception as e:
            logger.error(f"Error saving scheduler state: {e}", exc_info=True)
    
    def _initialize_components(self):
        """Initialize IBKR client and portfolio managers"""
        
        if self.ibkr_app is None:
            # Create IBKR client
            ibkr_config = self.config['ibkr']
            self.ibkr_app = IBKRApp(
                host=ibkr_config['host'],
                port=ibkr_config['port'],
                client_id=ibkr_config['client_id']
            )
            
            # Create portfolio manager
            self.portfolio_manager = PortfolioManager(self.ibkr_app)
            
            # Create investment manager
            self.investment_manager = InvestmentManager(self.portfolio_manager)
    
    def _connect_ibkr(self):
        """Connect to IBKR"""
        
        if self.ibkr_app is None:
            self._initialize_components()
        
        if not self.ibkr_app.isConnected():
            logger.info("Connecting to IBKR")
            return self.ibkr_app.connect()
        
        return True
    
    def _disconnect_ibkr(self):
        """Disconnect from IBKR"""
        
        if self.ibkr_app and self.ibkr_app.isConnected():
            logger.info("Disconnecting from IBKR")
            self.ibkr_app.disconnect()
    
    def run_cash_management(self):
        """Run cash management process"""
        
        if self.is_running:
            logger.warning("Another task is already running. Skipping cash management.")
            return
        
        self.is_running = True
        logger.info("Starting cash management process")
        
        try:
            if self._connect_ibkr():
                # Run cash management
                result = self.portfolio_manager.handle_cash_management()
                
                # Record execution
                self.last_execution['cash_management'] = {
                    'timestamp': datetime.datetime.now().isoformat(),
                    'result': result
                }
                self._save_state()
                
                logger.info(f"Cash management completed: {result}")
                
                # If cash was transferred to investment account, run investment allocation
                if result.get('status') == 'Cash transferred to investment account':
                    amount = result.get('amount', 0)
                    logger.info(f"Running investment allocation for transferred cash: {amount}")
                    
                    # Run investment allocation
                    invest_result = self.investment_manager.handle_excess_cash_investment(amount)
                    
                    # Record execution
                    self.last_execution['investment_allocation'] = {
                        'timestamp': datetime.datetime.now().isoformat(),
                        'result': invest_result
                    }
                    self._save_state()
                    
                    logger.info(f"Investment allocation completed: {invest_result}")
            else:
                logger.error("Failed to connect to IBKR")
        except Exception as e:
            logger.error(f"Error in cash management: {e}", exc_info=True)
        finally:
            self._disconnect_ibkr()
            self.is_running = False
    
    def run_portfolio_rebalance(self):
        """Run portfolio rebalance process"""
        
        if self.is_running:
            logger.warning("Another task is already running. Skipping portfolio rebalance.")
            return
        
        self.is_running = True
        logger.info("Starting portfolio rebalance process")
        
        try:
            if self._connect_ibkr():
                # Run portfolio rebalance
                result = self.investment_manager.rebalance_portfolio()
                
                # Record execution
                self.last_execution['portfolio_rebalance'] = {
                    'timestamp': datetime.datetime.now().isoformat(),
                    'result': result
                }
                self._save_state()
                
                logger.info(f"Portfolio rebalance completed: {result}")
            else:
                logger.error("Failed to connect to IBKR")
        except Exception as e:
            logger.error(f"Error in portfolio rebalance: {e}", exc_info=True)
        finally:
            self._disconnect_ibkr()
            self.is_running = False
    
    def setup_schedule(self):
        """Set up the scheduler with tasks"""
        
        schedule_config = self.config['schedule']
        
        # Schedule cash management tasks
        cash_times = schedule_config['cash_management']['time']
        cash_days = schedule_config['cash_management']['days']
        
        for time_str in cash_times:
            for day in cash_days:
                schedule_job = getattr(schedule.every(), day.lower())
                schedule_job.at(time_str).do(self.run_cash_management)
                logger.info(f"Scheduled cash management for {day} at {time_str}")
        
        # Schedule portfolio rebalance tasks
        rebalance_times = schedule_config['portfolio_rebalance']['time']
        rebalance_days = schedule_config['portfolio_rebalance']['days']
        
        for time_str in rebalance_times:
            for day in rebalance_days:
                schedule_job = getattr(schedule.every(), day.lower())
                schedule_job.at(time_str).do(self.run_portfolio_rebalance)
                logger.info(f"Scheduled portfolio rebalance for {day} at {time_str}")
    
    def run(self):
        """Run the scheduler"""
        
        logger.info("Starting portfolio management scheduler")
        
        # Set up scheduled tasks
        self.setup_schedule()
        
        # Initialize components
        self._initialize_components()
        
        # Run the scheduler loop
        try:
            while True:
                schedule.run_pending()
                time.sleep(60)  # Check every minute
                
        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
        except Exception as e:
            logger.error(f"Error in scheduler: {e}", exc_info=True)
        finally:
            self._disconnect_ibkr()
            logger.info("Scheduler stopped")


# Main entry point
if __name__ == "__main__":
    scheduler = PortfolioScheduler()
    scheduler.run()