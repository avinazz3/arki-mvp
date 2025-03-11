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
    'config_path': 'config'
}

# Configuration
def load_config():
    """Load application configuration"""
    
    config_file = os.path.join(app_state['config_path'], 'client_portal_config.json')
    default_config = {
        'ibkr': {
            'host': '127.0.0.1',
            'port': 7497,  # 7497 for TWS demo, 4002 for Gateway demo
            'client_id': 2  # Different from scheduler
        },
        'accounts': {
            'cash_account_id': 'DU3915301',
            'investment_account_id': 'DU67890'
        },
        'dashboard': {
            'refresh_interval': 60,  # Seconds
            'charts': ['asset_allocation', 'performance']
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
        logger.info(f"Loaded client portal configuration from {config_file}")
        return config
    except Exception as e:
        logger.error(f"Error loading client portal configuration: {e}", exc_info=True)
        return default_config

# Initialize IBKR client and managers
def initialize_components():
    """Initialize IBKR client and portfolio managers"""
    
    if app_state['ibkr_app'] is None:
        config = load_config()
        ibkr_config = config['ibkr']
        
        # Create IBKR client
        app_state['ibkr_app'] = IBKRApp(
            host=ibkr_config['host'],
            port=ibkr_config['port'],
            client_id=ibkr_config['client_id']
        )
        
        # Create portfolio manager
        app_state['portfolio_manager'] = PortfolioManager(app_state['ibkr_app'])
        app_state['portfolio_manager'].config_path = app_state['config_path']
        
        # Create investment manager
        app_state['investment_manager'] = InvestmentManager(app_state['portfolio_manager'])

# Connect to IBKR in a separate thread
def connect_ibkr_async():
    """Connect to IBKR in a separate thread"""
    
    def connect_job():
        try:
            initialize_components()
            success = app_state['ibkr_app'].connect()
            app_state['connected'] = success
            
            if success:
                logger.info("Connected to IBKR successfully")
                
                # Load account information
                app_state['portfolio_manager'].load_account_info()
                app_state['portfolio_manager'].load_portfolio_allocations()
            else:
                logger.error("Failed to connect to IBKR")
        except Exception as e:
            logger.error(f"Error connecting to IBKR: {e}", exc_info=True)
            app_state['connected'] = False
    
    # Start connection in a separate thread
    thread = Thread(target=connect_job)
    thread.daemon = True
    thread.start()
    return thread

# Disconnect from IBKR
def disconnect_ibkr():
    """Disconnect from IBKR"""
    
    if app_state['ibkr_app'] and app_state['ibkr_app'].isConnected():
        logger.info("Disconnecting from IBKR")
        app_state['ibkr_app'].disconnect()
        app_state['connected'] = False

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
    
    if not app_state['connected']:
        flash('Please connect to IBKR first', 'warning')
        return redirect(url_for('index'))
    
    # Get account information
    account_data = {
        'cash_account': app_state['portfolio_manager'].cash_account,
        'investment_account': app_state['portfolio_manager'].investment_account
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
        performance_chart=performance_chart
    )

@app.route('/portfolio')
def portfolio():
    """Portfolio details page"""
    
    if not app_state['connected']:
        flash('Please connect to IBKR first', 'warning')
        return redirect(url_for('index'))
    
    # Get portfolio data
    cash_portfolio = app_state['portfolio_manager'].cash_portfolio
    investment_portfolio = app_state['portfolio_manager'].investment_portfolio
    
    # Get current positions
    cash_positions = app_state['portfolio_manager'].cash_account['positions']
    investment_positions = app_state['portfolio_manager'].investment_account['positions']
    
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
    
    config = load_config()
    
    if request.method == 'POST':
        # Update cash thresholds
        min_cash_level = request.form.get('min_cash_level')
        transfer_threshold = request.form.get('transfer_threshold')
        
        if min_cash_level and transfer_threshold:
            app_state['portfolio_manager'].config['min_cash_level'] = float(min_cash_level)
            app_state['portfolio_manager'].config['transfer_threshold'] = float(transfer_threshold)
            
            flash('Settings updated successfully', 'success')
        
        return redirect(url_for('settings'))
    
    # Get current settings
    settings_data = {
        'min_cash_level': app_state['portfolio_manager'].config['min_cash_level'],
        'transfer_threshold': app_state['portfolio_manager'].config['transfer_threshold'],
        'allocation_tolerance': app_state['portfolio_manager'].config.get('allocation_tolerance', 0.02),
        'ibkr_host': config['ibkr']['host'],
        'ibkr_port': config['ibkr']['port']
    }
    
    return render_template('settings.html', settings=settings_data)

@app.route('/api/account_data')
def api_account_data():
    """API endpoint for account data"""
    
    if not app_state['connected']:
        return jsonify({'error': 'Not connected to IBKR'})
    
    # Refresh account data
    app_state['portfolio_manager'].load_account_info()
    
    # Format response data
    response = {
        'cash_account': {
            'id': app_state['portfolio_manager'].cash_account['id'],
            'cash_balance': get_cash_balance(app_state['portfolio_manager'].cash_account),
            'total_value': get_account_value(app_state['portfolio_manager'].cash_account)
        },
        'investment_account': {
            'id': app_state['portfolio_manager'].investment_account['id'],
            'cash_balance': get_cash_balance(app_state['portfolio_manager'].investment_account),
            'total_value': get_account_value(app_state['portfolio_manager'].investment_account)
        },
        'cash_level': app_state['portfolio_manager'].check_cash_level(),
        'timestamp': datetime.now().isoformat()
    }
    
    return jsonify(response)

# Helper functions
def generate_allocation_chart():
    """Generate asset allocation chart"""
    
    if not app_state['connected'] or not app_state['portfolio_manager'].investment_account:
        return None
    
    # Get position data
    positions = app_state['portfolio_manager'].investment_account['positions']
    
    # Prepare data for chart
    allocation_data = {}
    for key, position in positions.items():
        parts = key.split('_')
        if len(parts) >= 2:
            symbol = parts[0]
            market_value = position.get('marketValue', 0)
            
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
    dates = pd.date_range(start='2023-01-01', end='2023-12-31', freq='M')
    
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
    
    if not account or 'data' not in account or 'account_info' not in account['data']:
        return 0
    
    account_info = account['data']['account_info']
    
    # Look for cash balance keys
    cash_keys = ['TotalCashValue_SGD', 'AvailableFunds_SGD', 'TotalCashValue', 'AvailableFunds']
    
    for key in cash_keys:
        if key in account_info:
            return float(account_info[key])
    
    return 0

def get_account_value(account):
    """Get total account value"""
    
    if not account or 'data' not in account or 'account_info' not in account['data']:
        return 0
    
    account_info = account['data']['account_info']
    
    # Look for value keys
    value_keys = ['NetLiquidation_SGD', 'GrossPositionValue_SGD', 'NetLiquidation', 'GrossPositionValue']
    
    for key in value_keys:
        if key in account_info:
            return float(account_info[key])
    
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
            <p>Arki Portfolio Management &copy; 2023</p>
        </div>
    </footer>
    
    <script src="https://code.jquery.com/jquery-3.5.1.slim.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.0/dist/js/bootstrap.bundle.min.js"></script>
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    {% block scripts %}{% endblock %}
</body>
</html>
    '''
    
    # Index page
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
    <div class="col-md-4">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Portfolio Dashboard</h5>
                <p class="card-text">View your portfolio dashboard with real-time account information and charts.</p>
                <a href="/dashboard" class="btn btn-primary">View Dashboard</a>
            </div>
        </div>
    </div>
    <div class="col-md-4">
        <div class="card">
            <div class="card-body">
                <h5 class="card-title">Portfolio Details</h5>
                <p class="card-text">Explore detailed information about your portfolio allocations and positions.</p>
                <a href="/portfolio" class="btn btn-primary">View Portfolio</a>
            </div>
        </div>
    </div>
    <div class="col-md-4">
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
    <div class="col-md-6">
        <div class="card metrics-card">
            <div class="card-header">
                <h5>Cash Account</h5>
            </div>
            <div class="card-body">
                {% if account_data.cash_account %}
                    <p><strong>Account ID:</strong> {{ account_data.cash_account.id }}</p>
                    <p><strong>Cash Balance:</strong> ${{ "%.2f"|format(account_data.cash_account.data.account_info.get('TotalCashValue_SGD', 0)|float) }}</p>
                    <p><strong>Min Cash Level:</strong> ${{ "%.2f"|format(cash_info.min_cash_level) }}</p>
                    <p><strong>Excess Cash:</strong> ${{ "%.2f"|format(cash_info.excess_cash) }}</p>
                    <p><strong>Transfer Threshold:</strong> ${{ "%.2f"|format(cash_info.transfer_threshold) }}</p>
                    <p><strong>Should Transfer:</strong> {{ "Yes" if cash_info.should_transfer else "No" }}</p>
                {% else %}
                    <p>Cash account data not available</p>
                {% endif %}
            </div>
        </div>
    </div>
    
    <div class="col-md-6">
        <div class="card metrics-card">
            <div class="card-header">
                <h5>Investment Account</h5>
            </div>
            <div class="card-body">
                {% if account_data.investment_account %}
                    <p><strong>Account ID:</strong> {{ account_data.investment_account.id }}</p>
                    <p><strong>Cash Balance:</strong> ${{ "%.2f"|format(account_data.investment_account.data.account_info.get('TotalCashValue_SGD', 0)|float) }}</p>
                    <p><strong>Portfolio Value:</strong> ${{ "%.2f"|format(account_data.investment_account.data.account_info.get('NetLiquidation_SGD', 0)|float) }}</p>
                    <p><strong>Number of Positions:</strong> {{ account_data.investment_account.positions|length }}</p>
                {% else %}
                    <p>Investment account data not available</p>
                {% endif %}
            </div>
        </div>
    </div>
</div>

<div class="row mt-4">
    <div class="col-md-6">
        <div class="card">
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
    
    <div class="col-md-6">
        <div class="card">
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
</script>
{% endblock %}
    '''
    
    # Portfolio page
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
                        {% if investment_portfolio %}
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
        'settings.html': settings_html
    }
    
    for filename, content in templates.items():
        file_path = os.path.join(templates_dir, filename)
        if not os.path.exists(file_path):
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
    app.run(debug=True, host='0.0.0.0', port=5000)