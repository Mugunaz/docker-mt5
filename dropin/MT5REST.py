from fastapi import FastAPI
import MetaTrader5 as mt5
from pydantic import BaseModel
import uvicorn
import os
from dotenv import load_dotenv
import pendulum
import pandas as pd
import time
from datetime import datetime, timedelta

# Load environment variables from .env file
load_dotenv()

# Initialize FastAPI
app = FastAPI(title="MT5 REST API")

MT5_Login = int(os.getenv('MT5_LOGIN'))
MT5_Password = os.getenv('MT5_PASSWORD')
MT5_Server = os.getenv('MT5_SERVER')

mt5.initialize(login=int(MT5_Login), password=MT5_Password, server=MT5_Server)
print(f"MT5 initialized with login {MT5_Login} on server {MT5_Server}")

# Connect to MetaTrader 5
if not mt5.initialize(login=MT5_Login, password=MT5_Password, server=MT5_Server):
    raise RuntimeError(f"MT5 initialize() failed, error: {mt5.last_error()}")

@app.get("/account")
def get_account_info():
    """Fetch account info"""
    account_info = mt5.account_info()
    if account_info is None:
        return {"error": mt5.last_error()}
    return account_info._asdict()


@app.get("/price/{symbol}")
def get_symbol_price(symbol: str):
    """Fetch latest symbol price"""
    print( f"Fetching price for symbol: {symbol}")
    tick = mt5.symbol_info_tick(symbol)
    print(tick)
    if tick is None:
        return {"error": f"Failed to get tick for {symbol}"}
    return {"symbol": symbol, "bid": tick.bid, "ask": tick.ask}


@app.get("/range/{ticker}/{DR_start}/{DR_end}")
def get_range(ticker: str, DR_start: str, DR_end: str) -> tuple:
    """
    Calculate price range for a given symbol using DR_start and DR_end from config/session.
    Args:
        ticker (str): The symbol to calculate range for
        DR_start (str): Start time of the defining range (e.g., '03:00')
        DR_end (str): End time of the defining range (e.g., '03:55')
        timeframe (int): Timeframe in minutes (default: 5)
        num_bars (int): Number of bars to consider (default: 100)
    Returns:
        tuple: (high, low)
    """
    try:
        print(f"Calculating range for {ticker} from {DR_start} to {DR_end}")
        
        symbol_info = mt5.symbol_info(ticker)
        time_dif = symbol_info.time - int(pendulum.now('UTC').timestamp())
        rates = (mt5.copy_rates_from_pos(ticker, mt5.TIMEFRAME_M5, 0, 300))

        df = pd.DataFrame(rates)
        # Round to the nearest 300-second (5-minute) interval
        df['time'] = ((df['time'] - time_dif) // 300) * 300
        df['time'] = pd.to_datetime(df['time'], unit='s', utc=True).dt.tz_convert('America/New_York')
        df = df[df['time'].dt.date == pendulum.now('America/New_York').date()]
        df.set_index('time', inplace=True)
        df['open'] = df['open'] + symbol_info.point * df['spread']/2
        df['close'] = df['close'] + symbol_info.point * df['spread']/2
        df['high'] = df['high'] + symbol_info.point * df['spread']/2
        df['low'] = df['low'] + symbol_info.point * df['spread']/2
        # Get the DR session data
        ohlcDR = df.between_time(DR_start, DR_end)
        high = max(ohlcDR['close'].max(), ohlcDR['open'].max())
        low = min(ohlcDR['close'].min(), ohlcDR['open'].min())

        # Recursively try to get valid range values up to 5 times if NaN
        attempts = 0
        while (pd.isna(high) or pd.isna(low)) and attempts < 5:
            attempts += 1
            time.sleep(3)
            high, low = get_range(ticker, DR_start, DR_end, timeframe, num_bars)

        if pd.isna(high) or pd.isna(low):
            print("Failed to get valid range values after 5 attempts")
            return 0.0, 0.0
        return high, low
    
    except Exception as e:
        print(f"Error in get_range: {str(e)}")
        return 0.0, 0.0


def position_size(ticker: str, Entry: float, Stop: float, riskDollar: float) -> float:
    """
    Calculate position size based on risk parameters.
    
    Args:
        ticker (str): The symbol to calculate position size for
        Entry (float): Entry price
        Stop (float): Stop loss price
        
    Returns:
        float: Calculated position size in lots
        
    The method considers:
    - Risk amount per trade
    - Stop loss distance
    - Symbol-specific multipliers
    - Minimum lot size requirements
    """

    step = mt5.symbol_info(ticker).volume_step

    try:
        info = mt5.symbol_info(ticker)
        if info is None:
            return 0.0
        
        stopPip = (abs(Entry-Stop) + info.spread * info.trade_tick_size) / info.trade_tick_size
        tickValue = info.trade_tick_value
        
        position_size = riskDollar / (stopPip * tickValue)
        decimal_places = len(str(step).split('.')[-1]) if '.' in str(step) else 0
        rounded_size = round(position_size, decimal_places)

        return rounded_size 
    except Exception as e:
        return 0.0

@app.post("/order/{symbol}/{direction}/{entry}/{stop}/{profit}/{IRU}/{IRL}/{risk}")
def send_order(symbol: str, direction: str, entry: float, stop: float, profit: float, IRU: float, IRL: float, risk: float):

    if entry is None or stop is None or profit is None:
        return {"retcode": -1, "comment": "Missing order values"}
    
    # Get IRU and IRL from the order data
    iru = IRU
    irl = IRL
    mt5_symbol = symbol
    bot = {"risk": risk}

    if iru is None or irl is None:
        return {"retcode": -1, "comment": "Missing IRU or IRL values"}
    
    if mt5_symbol == 'USDJPY':

        if direction == 'long': direction = 'short'
        else: direction = 'long'
    
    # Add spread adjustment
    spread = mt5.symbol_info(mt5_symbol).spread * mt5.symbol_info(mt5_symbol).point
    if direction == 'long':
        entry_price = iru + (entry / 100) * (iru - irl)
        stop_price = iru + (stop / 100) * (iru - irl)
        profit_price = iru + (profit / 100) * (iru - irl)
        entry_price += spread/2
    else:
        entry_price = irl - (entry / 100) * (iru - irl)
        stop_price = irl - (stop / 100) * (iru - irl)
        profit_price = irl - (profit / 100) * (iru - irl)
        stop_price += spread/2

    riskDollar = bot.get('risk')
    lot = position_size(mt5_symbol, entry_price, stop_price, riskDollar)
    
    cutoff = '15:59:50'
    try:
        request = {
            "action": mt5.TRADE_ACTION_PENDING,
            "symbol": mt5_symbol,
            "volume": float(lot),
            "type": mt5.ORDER_TYPE_BUY_LIMIT if direction == 'long' else mt5.ORDER_TYPE_SELL_LIMIT,
            "price": float(entry_price),
            "tp": float(profit_price),
            "sl": float(stop_price), 
            "type_filling": mt5.ORDER_FILLING_IOC,
            "type_time": mt5.ORDER_TIME_SPECIFIED,
            "expiration": int(pd.to_datetime((pd.to_datetime(cutoff).tz_localize('US/Eastern').tz_convert('EET').strftime('%H:%M:%S'))).timestamp())}

        result = mt5.order_send(request)
        
        if result.retcode == 10015:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": mt5_symbol,
                "volume": float(lot),
                "type": mt5.ORDER_TYPE_BUY if direction == 'long' else mt5.ORDER_TYPE_SELL,
                "price": mt5.symbol_info_tick(mt5_symbol).ask if direction == 'long' else mt5.symbol_info_tick(mt5_symbol).bid,
                "tp": float(profit_price),
                "sl": float(stop_price), 
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC
            }

            return mt5.order_send(request)

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return {"retcode": result.retcode, "comment": result.comment}
        else:
            return result
    
    except Exception as e:
        return {"retcode": -1, "comment": str(e)}

@app.post("/close_all")
def close_all() -> list:
    """
    Close all open positions for the account.
    
    Args:
        bot (Dict): Bot configuration dictionary
    
    Returns:
        list: List of closed position details
    """
    try:
        orders = mt5.orders_get()

        print("Current orders: %s", orders)

        for order in orders:

            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket
            }

            mt5.order_send(request)

        positions = mt5.positions_get()
        
        if positions is None or len(positions) == 0:
            print("No positions to close.")
            return []
            
        closed_positions = []
            
        for position in positions:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": position.symbol,
                "position": position.ticket,
                "volume": position.volume,
                "type": mt5.ORDER_TYPE_SELL if position.type == 0 else mt5.ORDER_TYPE_BUY,
                "price": mt5.symbol_info_tick(position.symbol).bid if position.type == 0 else mt5.symbol_info_tick(position.symbol).ask,
                "type_filling": 1,
                "deviation": 10,
                "type_time": mt5.ORDER_TIME_GTC
            }
            result = mt5.order_send(request)
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                print("Closed position: %s, ticket: %s", position.symbol, position.ticket)
                
                # Create position detail dict for notification
                pos_detail = {
                    'symbol': position.symbol,
                    'profit': position.profit,
                    'type': position.type,
                    'volume': position.volume
                }
                closed_positions.append(pos_detail)
            else:
                print("Failed to close position: %s, ticket: %s", position.symbol, position.ticket)
                if result:
                    print("Return code: %s", getattr(result, 'retcode', None))

        return closed_positions
        
    except Exception as e:
        print("Error in close_all: %s", str(e))
        return []

@app.get("/open_positions")
def get_open_positions():
    '''
    Get all open positions and format them as JSON
    '''        
    try:
        # Get account info first
        account_info = mt5.account_info()
        if account_info is None:
            print("No account info found")
            return []
            
        positions = mt5.positions_get()
        
        if positions is None or len(positions) == 0:
            return []
        
        formatted_positions = []
        for pos in positions:
            # Get current market price
            symbol_info = mt5.symbol_info_tick(pos.symbol)
            current_price = symbol_info.bid if pos.type == 0 else symbol_info.ask
            
            position_info = {
                "id": pos.ticket,
                "account_id": f"{account_info.login}",
                "symbol": pos.symbol,
                "side": "LONG" if pos.type == 0 else "SHORT",
                "quantity": pos.volume,
                "price": round(pos.price_open, 2),
                "current_price": round(current_price, 2),
                "tp": round(pos.tp, 2) if pos.tp != 0 else None,
                "sl": round(pos.sl, 2) if pos.sl != 0 else None,
                "entry_time": datetime.fromtimestamp(pos.time).strftime("%Y-%m-%d %H:%M:%S"),
                "profit": round(pos.profit, 2),
                "swap": round(pos.swap, 2),
                "type": "POSITION"
            }
            formatted_positions.append(position_info)
        
        return formatted_positions
        
    except Exception as e:
        print("Error in get_open_positions: %s", str(e))
        return []

@app.get('/orders')
def get_pending_orders():
    '''
    Get all pending orders and format them as JSON
    '''
    
    try:
        # Get account info first
        account_info = mt5.account_info()
        if account_info is None:
            print("No account info found")
            return []
            
        orders = mt5.orders_get()
        
        if orders is None or len(orders) == 0:
            print("No pending orders found")
            return []
        
        formatted_orders = []
        for order in orders:
            order_info = {
                "id": order.ticket,
                "account_id": f"{account_info.login}",
                "symbol": order.symbol,
                "side": "LONG" if order.type % 2 == 0 else "SHORT",
                "quantity": order.volume_initial,
                "price": round(order.price_open, 2),
                "tp": round(order.tp, 2) if order.tp != 0 else None,
                "sl": round(order.sl, 2) if order.sl != 0 else None,
                "entry_time": datetime.fromtimestamp(order.time_setup).strftime("%Y-%m-%d %H:%M:%S"),
                "expiration": datetime.fromtimestamp(order.time_expiration).strftime("%Y-%m-%d %H:%M:%S") if order.time_expiration else None,
                "type": "ORDER"
            }
            formatted_orders.append(order_info)
        
        return formatted_orders
        
    except Exception as e:
        print("Error in get_pending_orders: %s", str(e))
        return []

@app.get('/trades')
def get_trades():
    '''
    Get all trades for the current day and format them as JSON
    '''
    
    # Get today's date range in NY timezone for consistency
    ny_now = pendulum.now('America/New_York')
    today = datetime(ny_now.year, ny_now.month, ny_now.day, 0, 0, 0)
    tomorrow = today + timedelta(days=1)
        
    try:
        # Get account info first
        account_info = mt5.account_info()
        if account_info is None:
            print("No account info found")
            return []
            
        # Get deals for today using mt5 API
        deals = mt5.history_deals_get(today, tomorrow)
        
        if deals is None or len(deals) == 0:
            print("No deals found")
            return []

        print("Found %d total deals", len(deals))

        # Convert deals to the requested format
        formatted_trades = []
        trade_id = 1
        
        # Group deals by position_id to match entry and exit
        position_deals = {}
        
        # First, convert deal times to NY timezone for consistent filtering
        ny_tz = pendulum.timezone('America/New_York')
        
        for deal in deals:
            if not hasattr(deal, 'position_id'):
                print("Skipping deal without position_id: %s", deal)
                continue
                
            # Convert deal time to NY timezone for filtering
            deal_time = pendulum.from_timestamp(deal.time).in_timezone(ny_tz)
            
            # Only include deals from today
            if deal_time.date() != ny_now.date():
                print("Skipping deal from different date: %s", deal_time)
                continue
                
            if deal.position_id not in position_deals:
                position_deals[deal.position_id] = []
            position_deals[deal.position_id].append(deal)

        print("Found %d positions after filtering", len(position_deals))

        # Process each position's deals
        for position_id, position_deals_list in position_deals.items():
            if len(position_deals_list) < 2:  # Skip if we don't have both entry and exit
                print("Skipping position %s: only has %d deals", position_id, len(position_deals_list))
                continue
                
            # Sort deals by time
            position_deals_list.sort(key=lambda x: x.time)
            
            # Get entry and exit deals
            entry_deal = position_deals_list[0]
            exit_deal = position_deals_list[-1]
            
            # Convert deal times to NY timezone for verification
            entry_time = pendulum.from_timestamp(entry_deal.time).in_timezone(ny_tz)
            exit_time = pendulum.from_timestamp(exit_deal.time).in_timezone(ny_tz)
            
            # Skip if either deal has zero price
            if entry_deal.price == 0 or exit_deal.price == 0:
                print("Skipping position %s: has zero price", position_id)
                continue

            print("Processing position %s: Entry at %s, Exit at %s", position_id, entry_time, exit_time)

            # Determine side
            side = "LONG" if entry_deal.type == 0 else "SHORT"
            
            # Create trade info with timezone-aware timestamps
            trade_info = {
                "id": trade_id,
                "account_id": f"{account_info.login}",
                "symbol": entry_deal.symbol,
                "side": side,
                "quantity": entry_deal.volume,
                "price": round(entry_deal.price, 2),
                "close_price": round(exit_deal.price, 2),
                "tp": None,  # MT5 API doesn't provide this in history
                "sl": None,  # MT5 API doesn't provide this in history
                "entry_time": entry_time.strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": exit_time.strftime("%Y-%m-%d %H:%M:%S"),
                "profit": round(exit_deal.profit, 2),
                "fee": round(exit_deal.commission + exit_deal.swap, 2)  # Including swap costs
            }

            print("Added trade: %s - %s - %s", entry_time.strftime('%Y-%m-%d'), entry_deal.symbol, side)

            formatted_trades.append(trade_info)
            trade_id += 1
        
        return formatted_trades
        
    except Exception as e:
        print("Error in get_trades: %s", str(e))
        return []

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)
