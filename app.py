import json, math, time
from datetime import datetime, timezone
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title='BTC 5M Signal Model', page_icon='₿', layout='centered')
GAMMA='https://gamma-api.polymarket.com'
CLOB='https://clob.polymarket.com'
BINANCE='https://api.binance.com'
S=requests.Session(); S.headers.update({'User-Agent':'BTC5mSignalResearch/1.0'})

@st.cache_data(ttl=3, show_spinner=False)
def get_json(url, params=None):
    r=S.get(url, params=params, timeout=8); r.raise_for_status(); return r.json()

def current_market():
    now=int(time.time()); start=now-now%300; slug=f'btc-updown-5m-{start}'
    data=get_json(f'{GAMMA}/events', {'slug':slug})
    if not data: raise RuntimeError('Current 5-minute BTC market was not found on Polymarket yet.')
    event=data[0]; markets=event.get('markets') or []
    if not markets: raise RuntimeError('Market metadata did not include outcomes.')
    m=markets[0]
    outcomes=m.get('outcomes', ['Up','Down']); tokens=m.get('clobTokenIds')
    if isinstance(outcomes,str): outcomes=json.loads(outcomes)
    if isinstance(tokens,str): tokens=json.loads(tokens)
    if not tokens or len(tokens)<2: raise RuntimeError('Could not read UP/DOWN token IDs.')
    # Respect the actual outcome labels instead of assuming array order.
    labels=[str(x).lower() for x in outcomes]
    try: ui=next(i for i,x in enumerate(labels) if x in ('up','yes'))
    except StopIteration: ui=0
    try: di=next(i for i,x in enumerate(labels) if x in ('down','no'))
    except StopIteration: di=1
    return {'slug':slug,'event':event,'market':m,'up':tokens[ui],'down':tokens[di], 'end':start+300,'start':start}

def book(token):
    b=get_json(f'{CLOB}/book', {'token_id':token})
    bids=sorted(b.get('bids',[]), key=lambda x:float(x['price']), reverse=True)
    asks=sorted(b.get('asks',[]), key=lambda x:float(x['price']))
    bid=float(bids[0]['price']) if bids else None
    ask=float(asks[0]['price']) if asks else None
    mid=(bid+ask)/2 if bid is not None and ask is not None else (ask if ask is not None else bid)
    spread=ask-bid if ask is not None and bid is not None else None
    return {'bid':bid,'ask':ask,'mid':mid,'spread':spread}

@st.cache_data(ttl=4, show_spinner=False)
def btc_candles():
    rows=get_json(f'{BINANCE}/api/v3/klines', {'symbol':'BTCUSDT','interval':'1m','limit':60})
    df=pd.DataFrame(rows, columns=['t','o','h','l','c','v','ct','q','n','tb','tq','x'])
    for c in ['o','h','l','c','v']: df[c]=df[c].astype(float)
    return df

def rsi(series, period=14):
    d=series.diff(); gain=d.clip(lower=0).ewm(alpha=1/period, adjust=False).mean(); loss=(-d.clip(upper=0)).ewm(alpha=1/period, adjust=False).mean()
    rs=gain/(loss.replace(0,1e-12)); return float(100-(100/(1+rs.iloc[-1])))

def evaluate(df, up, down, seconds_left):
    close=df.c; ema9=close.ewm(span=9, adjust=False).mean().iloc[-1]; ema21=close.ewm(span=21, adjust=False).mean().iloc[-1]
    ema50=close.ewm(span=50, adjust=False).mean().iloc[-1]; last=float(close.iloc[-1]); prev=float(close.iloc[-2])
    ret1=(last/prev-1)*10000; ret3=(last/float(close.iloc[-4])-1)*10000; ret5=(last/float(close.iloc[-6])-1)*10000
    vol=float(df.v.iloc[-5:].mean()); base=float(df.v.iloc[-30:].mean()); vol_ratio=vol/base if base else 1
    rv=float(close.pct_change().tail(10).std()*10000)
    score=0.0; reasons=[]
    if ema9>ema21: score+=1; reasons.append('1m EMA 9 above EMA 21')
    else: score-=1; reasons.append('1m EMA 9 below EMA 21')
    if ema21>ema50: score+=0.7
    else: score-=0.7
    if ret1>0.8: score+=0.6
    elif ret1< -0.8: score-=0.6
    if ret3>1.2: score+=0.8
    elif ret3< -1.2: score-=0.8
    if ret5>1.8: score+=0.8
    elif ret5< -1.8: score-=0.8
    momentum_rsi=rsi(close)
    if 52<=momentum_rsi<=70: score+=0.4
    elif 30<=momentum_rsi<=48: score-=0.4
    if vol_ratio>1.25: score*=1.12; reasons.append('recent volume elevated')
    # Require a meaningful edge over the contract's ask, rather than chase expensive shares.
    direction='UP' if score>=1.25 else ('DOWN' if score<=-1.25 else 'NO TRADE')
    selected=up if direction=='UP' else down if direction=='DOWN' else None
    ask=selected['ask'] if selected else None; spread=selected['spread'] if selected else None
    if selected and (ask is None or ask>=0.88 or ask<=0.03 or (spread is not None and spread>0.08)):
        direction='NO TRADE'; reasons.append('contract price/spread is unattractive or unavailable')
    if seconds_left<25:
        direction='NO TRADE'; reasons.append('too little time remains for a fresh entry')
    if rv>18:
        direction='NO TRADE'; reasons.append('very high short-term volatility')
    return {'direction':direction,'score':score,'rsi':momentum_rsi,'ret1':ret1,'ret3':ret3,'ret5':ret5,'vol_ratio':vol_ratio,'rv':rv,'last':last,'ema9':ema9,'ema21':ema21,'ask':ask,'spread':spread,'reasons':reasons}

st.title('₿ BTC 5-Minute Signal Model')
st.caption('Polymarket market data + BTC momentum research model • manual trading only')
if st.button('Refresh live data', use_container_width=True): st.cache_data.clear()
try:
    m=current_market(); up=book(m['up']); down=book(m['down']); df=btc_candles()
    left=max(0,m['end']-time.time()); result=evaluate(df,up,down,left)
    st.caption(f"Market: {m['slug']} · refresh timestamp {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}")
    c1,c2,c3=st.columns(3); c1.metric('Time left',f'{int(left//60):02d}:{int(left%60):02d}'); c2.metric('BTC spot proxy',f"${result['last']:,.2f}"); c3.metric('Model score',f"{result['score']:+.2f}")
    st.divider()
    color={'UP':'🟢','DOWN':'🔴','NO TRADE':'⚪'}[result['direction']]
    st.subheader(f"{color} SIGNAL: {result['direction']}")
    a,b=st.columns(2)
    a.metric('UP best bid / ask',f"{up['bid']:.3f}" if up['bid'] is not None else '—',f"ask {up['ask']:.3f}" if up['ask'] is not None else 'No ask')
    b.metric('DOWN best bid / ask',f"{down['bid']:.3f}" if down['bid'] is not None else '—',f"ask {down['ask']:.3f}" if down['ask'] is not None else 'No ask')
    st.markdown('**Why the model decided this**')
    for x in result['reasons']: st.write('• '+x)
    st.divider(); st.subheader('Momentum diagnostics')
    x,y,z=st.columns(3); x.metric('RSI (14)',f"{result['rsi']:.1f}"); y.metric('1m return',f"{result['ret1']:+.2f} bps"); z.metric('5m return',f"{result['ret5']:+.2f} bps")
    st.caption(f"3m return {result['ret3']:+.2f} bps · volume ratio {result['vol_ratio']:.2f}x · short-term volatility {result['rv']:.2f} bps")
    st.info('BTC spot comes from Binance as a proxy; Polymarket settlement uses its specified Chainlink reference/TWAP. This model is experimental, not trained or validated, and does not calculate a verified win probability. Do not treat signals as financial advice.')
except Exception as e:
    st.error(f'Live data unavailable: {e}')
    st.caption('Try Refresh live data. If this repeats, check Polymarket/API availability.')

st.caption('Read-only: no wallet connection, no order placement, no private keys.')
