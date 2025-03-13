# Portfolio Management Application POC

This application is a portfolio management system for handling cash and investment accounts. It features automatic transfers between accounts, email notifications, and a web-based dashboard.

## Features

- Dashboard for monitoring cash and investment accounts
- Automated cash transfers based on configurable thresholds
- Email notifications for transfers
- Portfolio allocation management
- Transaction history tracking

## Prerequisites

- Python 3.9+
- IBKR account (for production use)
- Resend account (for email notifications)

## Installation

1. Clone the repository

```bash
git clone https://github.com/avinashparthiban/arki-mvp.git
cd arki-mvp
```

2. Create and activate a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

## Configuration

1. Configure your email notification settings in `config/client_portal_config.json`:

```json
"email": {
    "recipient_email": "youremail@example.com",
    "email_service": "resend",
    "resend_api_key": "your_resend_api_key",
    "resend_from_email": "onboarding@resend.dev",
    "verified_email": "youremail@gmail.com"
}
```

2. Adjust cash management thresholds:

```json
"cash_management": {
    "min_cash_level": 10000.0,
    "transfer_threshold": 5000.0,
    "allocation_tolerance": 0.02
}
```

3. Configure account IDs:

```json
"accounts": {
    "cash_account_id": "DU12345",
    "investment_account_id": "DU4184147"
}
```

## Email Notifications Setup

This application uses Resend for email notifications. Important notes:

1. **Testing Mode**: When using the default `onboarding@resend.dev` sender, emails can only be sent to the verified email address.
    - Right now emails can only be sent to my personal email. But once we can do a 2FA, I can add your email too.

2. **For Production**: You'll need to:
   - Verify a domain with Resend
   - Change the `resend_from_email` to use your verified domain (e.g., `transfers@yourdomain.com`)

3. **Changing the Verified Email**: If someone else is running the application, they should update the `verified_email` field in the configuration to their own email address.

## Running the Application

Start the Flask web server:

```bash
python client_portal.py
```

The dashboard will be available at http://localhost:5001

## Using the Application

1. **View Dashboard**: See account balances, asset allocation, and performance charts
2. **Deposit Funds**: Add funds to the cash account via the deposit page
3. **Automatic Transfers**: When cash exceeds the threshold, funds automatically transfer to the investment account
4. **Portfolio Management**: View and modify portfolio allocations in the settings

## Common Issues

1. **Email Notification Errors**: If using Resend's testing mode, ensure the `verified_email` matches the email associated with your Resend account.

2. **Transfer Failures**: Check that account IDs match between the configuration and what's used in the portfolio manager.

---

# Investment Demo System

This system provides an automated investment management interface that connects to Interactive Brokers (IBKR) to execute trades based on predefined portfolio allocations.

## Prerequisites

- Python 3.7+
- Interactive Brokers TWS (Trader Workstation) or IB Gateway
- IBKR demo or live account

## Installation

1. Clone this repository:
   ```
   git clone https://github.com/yourusername/investment-demo.git
   cd investment-demo
   ```

2. Install required dependencies:
   ```
   pip install pandas ibapi logging
   ```

3. Create required directories:
   ```
   mkdir -p logs config
   ```

4. Make sure TWS (Trader Workstation) or IB Gateway is running and API connectivity is enabled.

## Configuration

1. Create a `config.json` file in the `config` directory:
   ```json
   {
     "ibkr": {
       "host": "127.0.0.1",
       "port": 7497,
       "client_id": 1
     },
     "accounts": {
       "investment_account_id": "YOUR_IBKR_ACCOUNT_ID"
     }
   }
   ```

2. Create a portfolio allocation file (optional) at `config/portfolio_allocation.csv`:
   ```csv
   account_type,strategy,instrument,target_percentage,instrument_type,exchange
   investment,growth,AAPL,0.3,STK,SMART
   investment,growth,MSFT,0.3,STK,SMART
   investment,growth,AMZN,0.4,STK,SMART
   investment,income,JNJ,0.5,STK,SMART
   investment,income,PG,0.5,STK,SMART
   ```

## Running the Application

Run the main script:
```
python investment_demo.py
```

## Expected Behavior

1. **Initialization**:
   - The system will attempt to connect to IBKR TWS/Gateway
   - It will load configuration and portfolio allocations
   - A command-line interface will appear with available commands
   - Ignore all market data related warnings/errors: the program will work as intended.

2. **Commands Available**:
   - `deposit <amount>`: Simulate a cash deposit and allocate it according to the portfolio strategy
   - `balance`: Display your current account balance and portfolio value
   - `exit`: Safely exit the program

3. **Cash Deposit Process**:
   - When you deposit cash using the `deposit` command, the system will:
     - Update your account balance
     - Calculate how to allocate the funds according to your portfolio allocation
     - Place market orders to purchase the required securities
     - Show you a summary of the executed trades
     - View the ordersheet in the `logs/orders.csv` file

4. **Scheduler**:
   - The system runs a scheduler that periodically:
     - Processes any pending cash deposits
     - Can be configured to automatically rebalance your portfolio

5. **Error Handling**:
   - If TWS is not running, you'll receive appropriate error messages
   - The system will log all operations and errors to the `logs` directory

## Additional Files

- **logs/main.log**: Contains detailed system logs
- **logs/orders.csv**: Records all order details for auditing

## Notes

- This is a demo system and uses default portfolio allocations if none are provided
- The system primarily uses market orders for simplicity
- Portfolio rebalancing is available but disabled by default
- The system caches market data for performance

## Troubleshooting

- Ensure TWS/IB Gateway is running before starting the application
- Check the port settings in TWS (Edit > Global Configuration > API > Settings)
- Verify your IBKR account ID is correct in the config file
- Review logs for detailed error information

---

## Milestones

### Milestone 1 and 3:
- Run the `client_portal.py` and test out the deposit function.
- 

### Milestone 2 and 3:
- Run the `investment_demo.py` to test the automated investment management system.

---

