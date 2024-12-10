# main.py
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import yfinance as yf
from datetime import datetime, timedelta
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, Float, String, Date
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
from datetime import datetime, timedelta
import pandas as pd

app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your Vercel frontend URL in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database setup
DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ETFFlow(Base):
    __tablename__ = "etf_flows"
    
    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date)
    ticker = Column(String)
    type = Column(String)  # 'BTC' or 'ETH'
    daily_flow = Column(Float)
    cumulative_flow = Column(Float)
    aum = Column(Float)

Base.metadata.create_all(bind=engine)

# ETF lists
BTC_ETFS = ['IBIT', 'FBTC', 'BITB', 'ARKB', 'BTCO', 'EZBC', 'BRRR', 'HODL', 'BTCW', 'GBTC', 'BTC']
ETH_ETFS = ['ETHA', 'FETH', 'ETHW', 'CETH', 'ETHV', 'QETH', 'EZET', 'ETHE', 'ETH']

def get_business_days(n_days: int) -> List[datetime]:
    end_date = datetime.now()
    dates = []
    current_date = end_date
    while len(dates) < n_days:
        if current_date.weekday() < 5:  # Monday = 0, Friday = 4
            dates.append(current_date)
        current_date -= timedelta(days=1)
    return dates[::-1]  # Reverse to get chronological order

@app.get("/api/flows/{crypto_type}")
async def get_flows(crypto_type: str, days: Optional[int] = 14):
    if crypto_type.upper() not in ['BTC', 'ETH']:
        raise HTTPException(status_code=400, detail="Invalid crypto type")
    
    etf_list = BTC_ETFS if crypto_type.upper() == 'BTC' else ETH_ETFS
    business_days = get_business_days(days)
    
    db = SessionLocal()
    try:
        # Get data for each ETF
        results = []
        for etf in etf_list:
            flows = db.query(ETFFlow).filter(
                ETFFlow.ticker == etf,
                ETFFlow.date.in_([d.date() for d in business_days])
            ).all()
            
            etf_data = {
                'ticker': etf,
                'daily_flows': [flow.daily_flow for flow in flows],
                'cumulative_flows': [flow.cumulative_flow for flow in flows],
                'aum': flows[-1].aum if flows else 0
            }
            results.append(etf_data)
        
        # Calculate totals
        total_flows = {
            'daily': [sum(etf['daily_flows'][i] for etf in results) for i in range(len(business_days))],
            'cumulative': [sum(etf['cumulative_flows'][i] for etf in results) for i in range(len(business_days))],
            'total_aum': sum(etf['aum'] for etf in results)
        }
        
        return {
            'dates': [d.strftime('%Y-%m-%d') for d in business_days],
            'etfs': results,
            'totals': total_flows
        }
    finally:
        db.close()

@app.get("/api/update")
async def update_flows():
    """
    Update ETF flow data - should be called daily via cron job
    """
    db = SessionLocal()
    try:
        for etf_list, crypto_type in [(BTC_ETFS, 'BTC'), (ETH_ETFS, 'ETH')]:
            for ticker in etf_list:
                # Fetch data from yfinance
                etf = yf.Ticker(ticker)
                hist = etf.history(period="1d")
                
                if not hist.empty:
                    # Calculate flows (simplified - you'll need to add your actual flow calculation logic)
                    daily_flow = hist['Volume'].iloc[-1] * hist['Close'].iloc[-1] / 1e6  # Convert to millions
                    
                    # Get previous cumulative flow
                    prev_flow = db.query(ETFFlow).filter(
                        ETFFlow.ticker == ticker
                    ).order_by(ETFFlow.date.desc()).first()
                    
                    cumulative_flow = (prev_flow.cumulative_flow if prev_flow else 0) + daily_flow
                    
                    # Create new record
                    new_flow = ETFFlow(
                        date=datetime.now().date(),
                        ticker=ticker,
                        type=crypto_type,
                        daily_flow=daily_flow,
                        cumulative_flow=cumulative_flow,
                        aum=hist['Close'].iloc[-1] * hist['Volume'].iloc[-1] / 1e6
                    )
                    db.add(new_flow)
        
        db.commit()
        return {"status": "success"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()