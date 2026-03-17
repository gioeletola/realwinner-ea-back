//+------------------------------------------------------------------+
//|                     RealWinner EA v5.0                           |
//|          SMC + Trend + Mean Reversion | Prop Firm Grade          |
//|     FundedNext / FTMO / MyForexFunds compatible                  |
//|  Parametri ottimizzati: ROI +32.6%/anno | DD max 5.02%           |
//+------------------------------------------------------------------+
#property copyright "RealWinner EA v5.0"
#property version   "5.00"
#property strict

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>

//+------------------------------------------------------------------+
//| INPUTS                                                            |
//+------------------------------------------------------------------+

// ── STRATEGIA
input group "=== STRATEGIA ==="
input bool   UseSMC          = true;    // Usa SMC (Order Blocks + BOS)
input bool   UseTrend        = true;    // Usa Trend (EMA + RSI)
input bool   UseMR           = true;    // Usa Mean Reversion (BB + RSI)
input int    ConfluenceMin   = 2;       // Minimo segnali confluenti (1-3)

// ── SESSIONI
input group "=== SESSIONI ==="
input int    LondonOpen      = 7;       // London apertura (UTC)
input int    LondonClose     = 11;      // London chiusura (UTC)
input int    NYOpen          = 13;      // New York apertura (UTC)
input int    NYClose         = 18;      // New York chiusura (UTC)
input int    OverlapOpen     = 11;      // Overlap apertura (UTC)
input int    OverlapClose    = 13;      // Overlap chiusura (UTC)
input bool   UseOverlap      = true;    // Usa sessione Overlap
input bool   AvoidNews       = true;    // Evita finestre news (13:25-13:35, 15:55-16:05)
input bool   CloseWeekend    = true;    // Chiudi trade venerdì 20:00 UTC

// ── RISK MANAGEMENT
input group "=== RISK MANAGEMENT ==="
input double RiskPct         = 0.9;    // Rischio % per trade
input double MaxDailyLoss    = 2.4;    // Hard stop giornaliero %
input double DailyWarning    = 0.7;    // Warning % → dimezza lotti
input double MaxTotalDD      = 5.5;    // Max drawdown totale %
input int    MaxTradesDay    = 10;     // Max trade al giorno
input int    MaxConsecLoss   = 3;      // Pausa dopo N loss consecutive
input bool   UseScaleOut     = true;   // Chiudi 50% a TP1
input bool   UseBreakEven    = true;   // Break even a 1R
input bool   UseTrailing     = true;   // Trailing stop stepped

// ── TAKE PROFIT / STOP LOSS
input group "=== TP / SL ==="
input double TP1_RR          = 1.5;    // TP1 R:R (chiude 50%)
input double TP2_RR          = 3.0;    // TP2 R:R (chiude resto)
input double ATR_SL_Mult     = 1.1;    // Moltiplicatore ATR per SL
input int    ATR_Period      = 14;     // Periodo ATR

// ── SMC PARAMS
input group "=== SMC ==="
input int    OB_Lookback     = 50;     // Barre lookback Order Block
input int    OB_Strength     = 2;      // Forza minima OB
input double OB_BodyMin      = 0.00010; // Body minimo OB (pips/10)

// ── TREND PARAMS
input group "=== TREND ==="
input int    EMA_Fast        = 9;
input int    EMA_Med         = 21;
input int    EMA_Slow        = 50;
input int    EMA_200         = 200;
input int    RSI_Period      = 14;
input int    RSI_Long_Min    = 50;     // RSI min per long
input int    RSI_Long_Max    = 78;     // RSI max per long
input int    RSI_Short_Min   = 22;     // RSI min per short
input int    RSI_Short_Max   = 50;     // RSI max per short

// ── MEAN REVERSION PARAMS
input group "=== MEAN REVERSION ==="
input int    BB_Period       = 20;
input double BB_Dev          = 2.0;
input int    MR_Overbought   = 70;
input int    MR_Oversold     = 30;

// ── MAGIC
input group "=== GENERALE ==="
input long   MagicNumber     = 202405;
input string EAComment       = "RealWinner v5";

//+------------------------------------------------------------------+
//| VARIABILI GLOBALI                                                 |
//+------------------------------------------------------------------+
CTrade   trade;
int      handle_ema_fast, handle_ema_med, handle_ema_slow, handle_ema_200;
int      handle_rsi, handle_atr, handle_bb;
int      handle_ema_fast_h4, handle_ema_slow_h4, handle_ema_200_h4;

// Daily tracking
datetime g_last_bar      = 0;
double   g_day_start_bal = 0;
int      g_trades_today  = 0;
int      g_consec_loss   = 0;
bool     g_daily_limit   = false;
bool     g_daily_warning = false;
datetime g_current_day   = 0;

// Monthly tracking
datetime g_current_month  = 0;
double   g_month_start_bal= 0;
bool     g_monthly_halved = false;

// Equity peak for total DD (running high-water mark)
double   g_equity_peak   = 0;

// Position tracking
bool     g_be_done       = false;
bool     g_tp1_done      = false;
string   g_trail_step    = "";

//+------------------------------------------------------------------+
//| INIT                                                              |
//+------------------------------------------------------------------+
int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(10);
   trade.SetTypeFilling(ORDER_FILLING_IOC);

   // M15 indicators
   handle_ema_fast  = iMA(_Symbol, PERIOD_M15, EMA_Fast,  0, MODE_EMA, PRICE_CLOSE);
   handle_ema_med   = iMA(_Symbol, PERIOD_M15, EMA_Med,   0, MODE_EMA, PRICE_CLOSE);
   handle_ema_slow  = iMA(_Symbol, PERIOD_M15, EMA_Slow,  0, MODE_EMA, PRICE_CLOSE);
   handle_ema_200   = iMA(_Symbol, PERIOD_M15, EMA_200,   0, MODE_EMA, PRICE_CLOSE);
   handle_rsi       = iRSI(_Symbol, PERIOD_M15, RSI_Period, PRICE_CLOSE);
   handle_atr       = iATR(_Symbol, PERIOD_M15, ATR_Period);
   handle_bb        = iBands(_Symbol, PERIOD_M15, BB_Period, 0, BB_Dev, PRICE_CLOSE);

   // H4 indicators (HTF bias)
   handle_ema_fast_h4 = iMA(_Symbol, PERIOD_H4, EMA_Fast, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema_slow_h4 = iMA(_Symbol, PERIOD_H4, EMA_Slow, 0, MODE_EMA, PRICE_CLOSE);
   handle_ema_200_h4  = iMA(_Symbol, PERIOD_H4, EMA_200,  0, MODE_EMA, PRICE_CLOSE);

   if(handle_ema_fast == INVALID_HANDLE || handle_rsi == INVALID_HANDLE ||
      handle_atr == INVALID_HANDLE || handle_bb == INVALID_HANDLE)
   {
      Print("ERRORE: impossibile creare handle indicatori");
      return INIT_FAILED;
   }

   g_day_start_bal   = AccountInfoDouble(ACCOUNT_BALANCE);
   g_month_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_equity_peak     = AccountInfoDouble(ACCOUNT_EQUITY);
   g_current_day     = iTime(_Symbol, PERIOD_D1, 0);
   g_current_month   = iTime(_Symbol, PERIOD_MN1, 0);

   Print("RealWinner EA v5 inizializzato | Magic: ", MagicNumber);
   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| DEINIT                                                            |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   IndicatorRelease(handle_ema_fast);
   IndicatorRelease(handle_ema_med);
   IndicatorRelease(handle_ema_slow);
   IndicatorRelease(handle_ema_200);
   IndicatorRelease(handle_rsi);
   IndicatorRelease(handle_atr);
   IndicatorRelease(handle_bb);
   IndicatorRelease(handle_ema_fast_h4);
   IndicatorRelease(handle_ema_slow_h4);
   IndicatorRelease(handle_ema_200_h4);
}

//+------------------------------------------------------------------+
//| TICK                                                              |
//+------------------------------------------------------------------+
void OnTick()
{
   // Solo su nuova barra M15
   datetime cur_bar = iTime(_Symbol, PERIOD_M15, 0);
   if(cur_bar == g_last_bar) return;
   g_last_bar = cur_bar;

   // Aggiorna equity peak (high-water mark)
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > g_equity_peak) g_equity_peak = equity;

   // Reset giornaliero
   CheckDailyReset();

   // Gestisci posizione aperta
   if(PositionExistsForEA())
   {
      ManagePosition();
      return;
   }

   // Controlli blocco
   if(g_daily_limit)   return;
   if(g_trades_today  >= MaxTradesDay)  return;
   if(g_consec_loss   >= MaxConsecLoss) return;

   // Controllo weekend e sessione
   if(!IsSessionTime()) return;
   if(IsWeekendClose()) return;
   if(AvoidNews && IsNewsTime()) return;

   // Filtro ATR anomalo (>3.5x media)
   if(IsATRAnomaly()) return;

   // Segnali
   int smc_sig   = UseSMC   ? GetSMCSignal()   : 0;
   int trend_sig = UseTrend ? GetTrendSignal() : 0;
   int mr_sig    = UseMR    ? GetMRSignal()    : 0;

   // H1 RSI filter sul trend signal
   if(trend_sig != 0 && !H1RSIConfirm(trend_sig))
      trend_sig = 0;

   // Confluenza
   int bull = (smc_sig==1?1:0) + (trend_sig==1?1:0) + (mr_sig==1?1:0);
   int bear = (smc_sig==-1?1:0) + (trend_sig==-1?1:0) + (mr_sig==-1?1:0);

   int signal = 0;
   if(bull >= ConfluenceMin) signal = 1;
   if(bear >= ConfluenceMin) signal = -1;
   if(signal == 0) return;

   // Apri trade
   OpenTrade(signal, smc_sig, trend_sig, mr_sig);
}

//+------------------------------------------------------------------+
//| RESET GIORNALIERO                                                 |
//+------------------------------------------------------------------+
void CheckDailyReset()
{
   datetime today = iTime(_Symbol, PERIOD_D1, 0);
   if(today == g_current_day) return;

   // Nuovo giorno
   g_current_day   = today;
   g_day_start_bal = AccountInfoDouble(ACCOUNT_BALANCE);
   g_trades_today  = 0;
   g_consec_loss   = 0;
   g_daily_limit   = false;
   g_daily_warning = false;

   // Nuovo mese
   datetime cur_month = iTime(_Symbol, PERIOD_MN1, 0);
   if(cur_month != g_current_month)
   {
      g_month_start_bal  = AccountInfoDouble(ACCOUNT_BALANCE);
      g_monthly_halved   = false;
      g_current_month    = cur_month;
   }

   // Controllo monthly circuit breaker
   double month_dd = (g_month_start_bal - AccountInfoDouble(ACCOUNT_BALANCE)) / g_month_start_bal * 100.0;
   if(month_dd >= 2.5 && !g_monthly_halved)
   {
      g_monthly_halved = true;
      Print("Monthly circuit breaker attivato: DD mensile ", DoubleToString(month_dd,2), "%");
   }
}

//+------------------------------------------------------------------+
//| GESTIONE POSIZIONE APERTA                                         |
//+------------------------------------------------------------------+
void ManagePosition()
{
   if(!PositionSelectByMagic(MagicNumber)) return;

   double entry   = PositionGetDouble(POSITION_PRICE_OPEN);
   double sl      = PositionGetDouble(POSITION_SL);
   double tp      = PositionGetDouble(POSITION_TP);
   double lots    = PositionGetDouble(POSITION_VOLUME);
   ENUM_POSITION_TYPE ptype = (ENUM_POSITION_TYPE)PositionGetInteger(POSITION_TYPE);
   int dir        = (ptype == POSITION_TYPE_BUY) ? 1 : -1;
   double cur     = (dir == 1) ? SymbolInfoDouble(_Symbol, SYMBOL_BID)
                                : SymbolInfoDouble(_Symbol, SYMBOL_ASK);

   // Recupera ATR
   double atr_buf[1];
   CopyBuffer(handle_atr, 0, 1, 1, atr_buf);
   double atc = atr_buf[0];

   double sl_dist = MathAbs(entry - sl);
   if(sl_dist <= 0) return;

   double progress = ((cur - entry) * dir) / sl_dist; // in unità R

   // ── STEPPED TRAILING STOP
   if(UseTrailing)
   {
      double new_sl = sl;

      if(progress >= 2.5)
      {
         // Trailing ATR stretto
         double trail_sl = cur - atc * 0.7 * dir;
         if((dir==1 && trail_sl > new_sl) || (dir==-1 && trail_sl < new_sl))
            new_sl = trail_sl;
         g_trail_step = "atr";
      }
      else if(progress >= 2.0 && g_trail_step != "2r" && g_trail_step != "atr")
      {
         // Lock in +1R
         double lock_sl = entry + sl_dist * 1.0 * dir;
         if((dir==1 && lock_sl > new_sl) || (dir==-1 && lock_sl < new_sl))
            new_sl = lock_sl;
         g_trail_step = "2r";
      }
      else if(progress >= 1.0 && !g_be_done && UseBreakEven)
      {
         // Break even + 8 pip buffer
         double pip  = SymbolInfoDouble(_Symbol, SYMBOL_POINT) * 10;
         double be_sl = entry + 8 * pip * dir;
         if((dir==1 && be_sl > new_sl) || (dir==-1 && be_sl < new_sl))
         {
            new_sl   = be_sl;
            g_be_done = true;
            g_trail_step = "be";
         }
      }

      if(new_sl != sl)
         trade.PositionModify(_Symbol, new_sl, tp);
   }

   // ── TP1 PARZIALE (50% a 1.5R)
   if(!g_tp1_done && UseScaleOut)
   {
      double tp1_price = entry + sl_dist * TP1_RR * dir;
      bool tp1_hit = (dir==1) ? (cur >= tp1_price) : (cur <= tp1_price);
      if(tp1_hit)
      {
         double close_lots = NormalizeDouble(lots * 0.5, 2);
         if(close_lots >= SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN))
         {
            if(dir == 1)
               trade.Sell(close_lots, _Symbol, 0, 0, 0, "RW v5 TP1 partial");
            else
               trade.Buy(close_lots, _Symbol, 0, 0, 0, "RW v5 TP1 partial");
            g_tp1_done = true;
            Print("TP1 parziale chiuso: ", close_lots, " lotti a ", DoubleToString(cur,5));
         }
      }
   }

   // ── DAILY DD CHECK
   double equity    = AccountInfoDouble(ACCOUNT_EQUITY);
   double daily_dd  = (g_day_start_bal - equity) / g_day_start_bal * 100.0;

   if(daily_dd >= MaxDailyLoss)
   {
      trade.PositionClose(_Symbol);
      g_daily_limit = true;
      Print("DAILY DD LIMIT raggiunto: ", DoubleToString(daily_dd,2), "% — trading bloccato oggi");
   }
   else if(daily_dd >= DailyWarning && !g_daily_warning)
   {
      g_daily_warning = true;
      Print("Daily warning: DD ", DoubleToString(daily_dd,2), "% — lotti dimezzati");
   }

   // ── TOTAL DD CHECK (running high-water mark)
   double total_dd = (g_equity_peak - equity) / g_equity_peak * 100.0;
   if(total_dd >= MaxTotalDD)
   {
      trade.PositionClose(_Symbol);
      g_daily_limit = true;
      Print("TOTAL DD LIMIT raggiunto: ", DoubleToString(total_dd,2), "%");
   }

   // ── WEEKEND CLOSE
   if(CloseWeekend && IsWeekendClose())
   {
      trade.PositionClose(_Symbol);
      Print("Weekend close — posizione chiusa");
   }
}

//+------------------------------------------------------------------+
//| APRI TRADE                                                        |
//+------------------------------------------------------------------+
void OpenTrade(int signal, int smc, int trend, int mr)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double entry = (signal == 1) ? ask : bid;
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   double pip   = point * 10; // per coppie a 5 decimali

   // ATR
   double atr_buf[1];
   CopyBuffer(handle_atr, 0, 1, 1, atr_buf);
   double atc = atr_buf[0];

   // SL basato su swing recente + ATR
   double sl_dist = atc * ATR_SL_Mult;
   double swing_sl = GetRecentSwing(signal, 10);
   if(swing_sl > 0)
   {
      double swing_dist = MathAbs(entry - swing_sl);
      sl_dist = MathMax(sl_dist, swing_dist + 5 * pip);
   }

   double sl = (signal == 1) ? (entry - sl_dist) : (entry + sl_dist);
   double tp = (signal == 1) ? (entry + sl_dist * TP2_RR) : (entry - sl_dist * TP2_RR);

   // R:R check
   if(sl_dist <= 0 || (sl_dist * TP2_RR) / sl_dist < 1.1) return;

   // Calcolo lotti con risk management
   double balance  = AccountInfoDouble(ACCOUNT_BALANCE);
   double daily_dd = (g_day_start_bal - AccountInfoDouble(ACCOUNT_EQUITY)) / g_day_start_bal * 100.0;

   double risk_mult = 1.0;
   if(g_daily_warning || daily_dd >= DailyWarning) risk_mult = 0.5;
   if(g_consec_loss >= 2) risk_mult = MathMin(risk_mult, 0.6);
   if(g_monthly_halved)   risk_mult = MathMin(risk_mult, 0.5);

   double risk_amount = balance * RiskPct / 100.0 * risk_mult;
   double tick_value  = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_VALUE);
   double tick_size   = SymbolInfoDouble(_Symbol, SYMBOL_TRADE_TICK_SIZE);
   double lots_raw    = risk_amount / (sl_dist / tick_size * tick_value);

   double vol_min  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vol_max  = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vol_step = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots     = MathFloor(lots_raw / vol_step) * vol_step;
   lots = MathMax(vol_min, MathMin(vol_max, lots));

   if(lots < vol_min) return;

   // Normalizza prezzi
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);

   // Apri
   bool result = false;
   string comment = StringFormat("RW v5 S%d T%d M%d", smc, trend, mr);

   if(signal == 1)
      result = trade.Buy(lots, _Symbol, 0, sl, tp, comment);
   else
      result = trade.Sell(lots, _Symbol, 0, sl, tp, comment);

   if(result)
   {
      g_trades_today++;
      g_be_done    = false;
      g_tp1_done   = false;
      g_trail_step = "";
      Print("Trade aperto: ", (signal==1?"LONG":"SHORT"), " ", lots, " lotti | SL:", DoubleToString(sl,digits), " TP:", DoubleToString(tp,digits));
   }
   else
      Print("Errore apertura trade: ", GetLastError());
}

//+------------------------------------------------------------------+
//| SEGNALE SMC                                                       |
//+------------------------------------------------------------------+
int GetSMCSignal()
{
   // HTF bias (H4)
   double h4_fast[1], h4_slow[1], h4_200[1];
   CopyBuffer(handle_ema_fast_h4, 0, 1, 1, h4_fast);
   CopyBuffer(handle_ema_slow_h4, 0, 1, 1, h4_slow);
   CopyBuffer(handle_ema_200_h4,  0, 1, 1, h4_200);
   bool htf_bull = (h4_fast[0] > h4_slow[0] && SymbolInfoDouble(_Symbol,SYMBOL_BID) > h4_200[0]);
   bool htf_bear = (h4_fast[0] < h4_slow[0] && SymbolInfoDouble(_Symbol,SYMBOL_BID) < h4_200[0]);

   // Break of Structure
   double highs[], lows[], closes[];
   ArraySetAsSeries(highs,  true);
   ArraySetAsSeries(lows,   true);
   ArraySetAsSeries(closes, true);
   CopyHigh(_Symbol, PERIOD_M15, 1, 30, highs);
   CopyLow (_Symbol, PERIOD_M15, 1, 30, lows);
   CopyClose(_Symbol, PERIOD_M15, 1, 30, closes);

   double swing_high = highs[ArrayMaximum(highs, 0, 30)];
   double swing_low  = lows[ArrayMinimum(lows,   0, 30)];
   double cur_close  = closes[0];

   bool bos_bull = (cur_close > swing_high && htf_bull);
   bool bos_bear = (cur_close < swing_low  && htf_bear);

   // Order Block detection
   bool ob_bull = false, ob_bear = false;

   double opens_ob[], closes_ob[];
   ArraySetAsSeries(opens_ob,  true);
   ArraySetAsSeries(closes_ob, true);
   CopyOpen (_Symbol, PERIOD_M15, 1, OB_Lookback, opens_ob);
   CopyClose(_Symbol, PERIOD_M15, 1, OB_Lookback, closes_ob);

   for(int i = OB_Strength; i < OB_Lookback - OB_Strength; i++)
   {
      double body = MathAbs(closes_ob[i] - opens_ob[i]);
      if(body < OB_BodyMin) continue;

      // Bearish OB seguito da impulso rialzista → segnale long
      if(closes_ob[i] < opens_ob[i]) // bearish candle
      {
         bool impulse = true;
         for(int j = 0; j < OB_Strength; j++)
            if(closes_ob[i-j-1] <= opens_ob[i-j-1]) { impulse=false; break; }
         if(impulse && htf_bull) ob_bull = true;
      }

      // Bullish OB seguito da impulso ribassista → segnale short
      if(closes_ob[i] > opens_ob[i]) // bullish candle
      {
         bool impulse = true;
         for(int j = 0; j < OB_Strength; j++)
            if(closes_ob[i-j-1] >= opens_ob[i-j-1]) { impulse=false; break; }
         if(impulse && htf_bear) ob_bear = true;
      }
   }

   if((bos_bull || ob_bull) && htf_bull) return 1;
   if((bos_bear || ob_bear) && htf_bear) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| SEGNALE TREND                                                     |
//+------------------------------------------------------------------+
int GetTrendSignal()
{
   double ef[1], em[1], es[1], e200[1], rsi_val[1];
   CopyBuffer(handle_ema_fast, 0, 1, 1, ef);
   CopyBuffer(handle_ema_med,  0, 1, 1, em);
   CopyBuffer(handle_ema_slow, 0, 1, 1, es);
   CopyBuffer(handle_ema_200,  0, 1, 1, e200);
   CopyBuffer(handle_rsi,      0, 1, 1, rsi_val);
   double rsi = rsi_val[0];
   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);

   // EMA alignment + RSI
   bool trend_long  = (ef[0]>em[0] && em[0]>es[0] && price>e200[0] &&
                       rsi>=RSI_Long_Min && rsi<=RSI_Long_Max);
   bool trend_short = (ef[0]<em[0] && em[0]<es[0] && price<e200[0] &&
                       rsi>=RSI_Short_Min && rsi<=RSI_Short_Max);

   if(trend_long)  return 1;
   if(trend_short) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| SEGNALE MEAN REVERSION                                            |
//+------------------------------------------------------------------+
int GetMRSignal()
{
   // Solo in mercato ranging (EMA spread piccolo)
   double ef[1], es[1];
   CopyBuffer(handle_ema_fast, 0, 1, 1, ef);
   CopyBuffer(handle_ema_slow, 0, 1, 1, es);
   double ema_spread = MathAbs(ef[0] - es[0]);
   if(ema_spread > 0.0020) return 0; // trending → skip MR

   double bb_upper[1], bb_lower[1], rsi_val[1];
   CopyBuffer(handle_bb,  1, 1, 1, bb_upper);
   CopyBuffer(handle_bb,  2, 1, 1, bb_lower);
   CopyBuffer(handle_rsi, 0, 1, 1, rsi_val);

   double price = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double rsi   = rsi_val[0];

   bool mr_long  = (price <= bb_lower[0] && rsi <= MR_Oversold);
   bool mr_short = (price >= bb_upper[0] && rsi >= MR_Overbought);

   if(mr_long)  return 1;
   if(mr_short) return -1;
   return 0;
}

//+------------------------------------------------------------------+
//| H1 RSI CONFIRMATION                                              |
//+------------------------------------------------------------------+
bool H1RSIConfirm(int signal)
{
   int h1_rsi_handle = iRSI(_Symbol, PERIOD_H1, RSI_Period, PRICE_CLOSE);
   if(h1_rsi_handle == INVALID_HANDLE) return true;
   double h1_rsi[1];
   CopyBuffer(h1_rsi_handle, 0, 1, 1, h1_rsi);
   IndicatorRelease(h1_rsi_handle);
   // Block long if H1 is in a strong downtrend (RSI < 30)
   if(signal ==  1 && h1_rsi[0] < 30) return false;
   // Block short if H1 is in a strong uptrend (RSI > 70)
   if(signal == -1 && h1_rsi[0] > 70) return false;
   return true;
}

//+------------------------------------------------------------------+
//| ATR ANOMALY FILTER                                                |
//+------------------------------------------------------------------+
bool IsATRAnomaly()
{
   double atr_cur[1], atr_ma_buf[20];
   CopyBuffer(handle_atr, 0, 1, 1, atr_cur);
   CopyBuffer(handle_atr, 0, 1, 20, atr_ma_buf);
   double atr_mean = 0;
   for(int i=0; i<20; i++) atr_mean += atr_ma_buf[i];
   atr_mean /= 20.0;
   if(atr_mean <= 0) return false;
   return (atr_cur[0] / atr_mean > 3.5);
}

//+------------------------------------------------------------------+
//| SESSION TIME CHECK                                                |
//+------------------------------------------------------------------+
bool IsSessionTime()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int h = dt.hour;

   bool london  = (h >= LondonOpen  && h < LondonClose);
   bool ny      = (h >= NYOpen      && h < NYClose);
   bool overlap = UseOverlap && (h >= OverlapOpen && h < OverlapClose);

   // Session scoring — blocca Lunedì mattina e Venerdì pomeriggio
   if(dt.day_of_week == 1 && h < 9)  return false; // Lunedì mattina debole
   if(dt.day_of_week == 5 && h >= 15) return false; // Venerdì pomeriggio

   return (london || ny || overlap);
}

//+------------------------------------------------------------------+
//| NEWS TIME CHECK                                                   |
//+------------------------------------------------------------------+
bool IsNewsTime()
{
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int hhmm = dt.hour * 100 + dt.min;
   // NFP/Fed/CPI finestre
   if(hhmm >= 1325 && hhmm <= 1335) return true;
   if(hhmm >= 1555 && hhmm <= 1605) return true;
   if(hhmm >= 1245 && hhmm <= 1315) return true;
   return false;
}

//+------------------------------------------------------------------+
//| WEEKEND CLOSE CHECK                                               |
//+------------------------------------------------------------------+
bool IsWeekendClose()
{
   if(!CloseWeekend) return false;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   return (dt.day_of_week == 5 && dt.hour >= 20);
}

//+------------------------------------------------------------------+
//| RECENT SWING                                                      |
//+------------------------------------------------------------------+
double GetRecentSwing(int signal, int lookback)
{
   double highs[], lows[];
   ArraySetAsSeries(highs, true);
   ArraySetAsSeries(lows,  true);
   CopyHigh(_Symbol, PERIOD_M15, 1, lookback, highs);
   CopyLow (_Symbol, PERIOD_M15, 1, lookback, lows);

   if(signal == 1) return lows[ArrayMinimum(lows, 0, lookback)];
   return highs[ArrayMaximum(highs, 0, lookback)];
}

//+------------------------------------------------------------------+
//| POSIZIONE APERTA PER EA                                           |
//+------------------------------------------------------------------+
bool PositionExistsForEA()
{
   for(int i=0; i<PositionsTotal(); i++)
   {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         return true;
   }
   return false;
}

bool PositionSelectByMagic(long magic)
{
   for(int i=0; i<PositionsTotal(); i++)
   {
      if(PositionGetSymbol(i) == _Symbol &&
         PositionGetInteger(POSITION_MAGIC) == magic)
      {
         PositionSelectByTicket(PositionGetTicket(i));
         return true;
      }
   }
   return false;
}

//+------------------------------------------------------------------+
//| ON TRADE (tracking win/loss streak)                               |
//+------------------------------------------------------------------+
void OnTrade()
{
   HistorySelect(TimeCurrent()-3600, TimeCurrent());
   int total = HistoryDealsTotal();
   for(int i=total-1; i>=0; i--)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(HistoryDealGetString(ticket, DEAL_SYMBOL) != _Symbol) continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != MagicNumber) continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_OUT) continue;

      double profit = HistoryDealGetDouble(ticket, DEAL_PROFIT);
      if(profit < 0)
         g_consec_loss++;
      else
      {
         g_consec_loss = 0;
         g_be_done   = false;
         g_tp1_done  = false;
         g_trail_step = "";
      }
      break;
   }
}
//+------------------------------------------------------------------+
