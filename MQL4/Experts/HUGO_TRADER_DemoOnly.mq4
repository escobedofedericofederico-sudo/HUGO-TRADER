//+------------------------------------------------------------------+
//| HUGO-TRADER Demo Only                                            |
//| Educational MA crossover EA. No real-account execution.          |
//+------------------------------------------------------------------+
#property strict
#property version   "0.1.3"
#property description "HUGO-TRADER demo-only SMA crossover Expert Advisor"

input bool   EnableDemoTrading = false; // Explicit opt-in; safe mode by default
input int    FastMAPeriod      = 5;
input int    SlowMAPeriod      = 20;
input double RiskPercent       = 0.5;   // Percent of current equity at the stop; max 1%
input double EstimatedRoundTurnCommissionPerLot = 0.0; // Account currency per lot, entry + exit
input int    StopLossPoints    = 300;   // Mandatory protective stop
input int    TakeProfitPoints  = 600;   // 0 disables take-profit
input int    MaxSpreadPoints   = 30;
input int    SlippagePoints    = 5;
input int    MagicNumber       = 26111501;

datetime g_lastBarTime = 0;
int g_lastUnprotectedTicket = -1;

#define STOP_STATUS_UNKNOWN -1
#define STOP_STATUS_INVALID 0
#define STOP_STATUS_VALID 1

// Strategy Tester is permitted because its orders are simulated.
// Outside the tester, the EA accepts demo accounts only.
bool TradingEnvironmentAllowed()
{
   return(IsDemo() || IsTesting());
}

int OnInit()
{
   if(FastMAPeriod < 1 || SlowMAPeriod <= FastMAPeriod)
   {
      Print("HUGO-TRADER: invalid moving-average periods.");
      return(INIT_PARAMETERS_INCORRECT);
   }

   if(!MathIsValidNumber(RiskPercent) ||
      !MathIsValidNumber(EstimatedRoundTurnCommissionPerLot) ||
      RiskPercent <= 0.0 || RiskPercent > 1.0 ||
      StopLossPoints <= 0 || TakeProfitPoints < 0 || MagicNumber <= 0 ||
      MaxSpreadPoints <= 0 || SlippagePoints < 0 ||
      EstimatedRoundTurnCommissionPerLot < 0.0)
   {
      Print("HUGO-TRADER: invalid risk or execution parameters.");
      return(INIT_PARAMETERS_INCORRECT);
   }

   if(!TradingEnvironmentAllowed())
   {
      Print("HUGO-TRADER BLOCKED: attach this EA only to a demo account or Strategy Tester.");
      return(INIT_FAILED);
   }

   if(!EnableDemoTrading)
      Print("HUGO-TRADER SAFE MODE: EnableDemoTrading=false; no orders will be sent.");

   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   Comment("");
}

bool MarketQuotesAreValid()
{
   // Cached prices can remain numerically valid after a live terminal disconnects.
   // Block live order operations until the server connection is restored.
   // Strategy Tester uses simulated quotes and is intentionally exempt.
   if(!IsTesting() && !IsConnected())
   {
      Print("HUGO-TRADER: terminal is disconnected; order operation blocked.");
      return(false);
   }

   RefreshRates();

   if(!MathIsValidNumber(Bid) || !MathIsValidNumber(Ask) ||
      !MathIsValidNumber(Point) || Bid <= 0.0 || Ask <= 0.0 ||
      Point <= 0.0 || Ask < Bid)
   {
      Print("HUGO-TRADER: invalid or unavailable market quotes; order operation blocked.");
      return(false);
   }

   return(true);
}

bool CrossedAbove()
{
   double fastPrevious = iMA(NULL, 0, FastMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   double slowPrevious = iMA(NULL, 0, SlowMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   double fastLatest   = iMA(NULL, 0, FastMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);
   double slowLatest   = iMA(NULL, 0, SlowMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);

   return(fastPrevious <= slowPrevious && fastLatest > slowLatest);
}

bool CrossedBelow()
{
   double fastPrevious = iMA(NULL, 0, FastMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   double slowPrevious = iMA(NULL, 0, SlowMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 2);
   double fastLatest   = iMA(NULL, 0, FastMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);
   double slowLatest   = iMA(NULL, 0, SlowMAPeriod, 0, MODE_SMA, PRICE_CLOSE, 1);

   return(fastPrevious >= slowPrevious && fastLatest < slowLatest);
}

bool FindOpenBuy(int &ticket)
{
   ticket = -1;

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
         continue;

      if(OrderSymbol() == Symbol() &&
         OrderMagicNumber() == MagicNumber &&
         OrderType() == OP_BUY)
      {
         ticket = OrderTicket();
         return(true);
      }
   }

   return(false);
}

bool HasConflictingOrder()
{
   // Block a new market entry if any market or pending order shares this
   // symbol/magic pair. Pending orders can later become market positions.
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         // An unreadable order makes the order state unknown. Fail closed:
         // do not assume the account is flat and do not send a new entry.
         Print("HUGO-TRADER WARNING: could not inspect an open order; order state unknown and new entries are blocked.");
         return(true);
      }

      if(OrderSymbol() == Symbol() &&
         OrderMagicNumber() == MagicNumber &&
         (OrderType() == OP_BUY ||
          OrderType() == OP_SELL ||
          OrderType() == OP_BUYLIMIT ||
          OrderType() == OP_SELLLIMIT ||
          OrderType() == OP_BUYSTOP ||
          OrderType() == OP_SELLSTOP))
         return(true);
   }

   return(false);
}

int LotDigitsFromStep(double step)
{
   // Support non-power-of-ten steps such as 0.25 as well as 0.01 or 0.001.
   for(int digits = 0; digits <= 8; digits++)
   {
      if(MathAbs(step - NormalizeDouble(step, digits)) < 1e-8)
         return(digits);
   }
   return(8);
}

double CalculateLots(double spreadPoints)
{
   double tickValue      = MarketInfo(Symbol(), MODE_TICKVALUE);
   double tickSizePoints = MarketInfo(Symbol(), MODE_TICKSIZE);
   double lotStep        = MarketInfo(Symbol(), MODE_LOTSTEP);
   double minLot         = MarketInfo(Symbol(), MODE_MINLOT);
   double maxLot         = MarketInfo(Symbol(), MODE_MAXLOT);
   double equity         = AccountEquity();

   if(!MathIsValidNumber(spreadPoints) || spreadPoints < 0.0 ||
      !MathIsValidNumber(tickValue) || !MathIsValidNumber(tickSizePoints) ||
      !MathIsValidNumber(lotStep) || !MathIsValidNumber(minLot) ||
      !MathIsValidNumber(maxLot) || !MathIsValidNumber(equity) ||
      tickValue <= 0.0 || tickSizePoints <= 0.0 ||
      lotStep <= 0.0 || minLot <= 0.0 || maxLot < minLot || equity <= 0.0)
      return(0.0);

   // Include spread in the estimated loss from Ask entry to Bid stop.
   // Reserve for the entry spread and slippage on both entry and stop execution.
   // Add the broker's estimated round-turn commission when the user supplies it.
   double stopDistancePoints = StopLossPoints + spreadPoints + 2.0 * SlippagePoints;
   double estimatedLossPerLot = (stopDistancePoints / tickSizePoints) * tickValue
                                + EstimatedRoundTurnCommissionPerLot;
   if(!MathIsValidNumber(estimatedLossPerLot) || estimatedLossPerLot <= 0.0)
      return(0.0);

   double riskMoney = equity * (RiskPercent / 100.0);
   if(!MathIsValidNumber(riskMoney) || riskMoney <= 0.0)
      return(0.0);

   double rawLots = riskMoney / estimatedLossPerLot;
   if(!MathIsValidNumber(rawLots) || rawLots <= 0.0)
      return(0.0);

   // Cap first, then round down to the broker's step. Never force the minimum lot.
   double cappedLots = MathMin(rawLots, maxLot);
   double lots = MathFloor(cappedLots / lotStep + 1e-8) * lotStep;
   if(lots < minLot)
      return(0.0);

   return(NormalizeDouble(lots, LotDigitsFromStep(lotStep)));
}

int ProtectiveStopStatus(int ticket)
{
   // Distinguish a confirmed bad stop from an unreadable order/quote state.
   // Unknown must pause the EA; it must not be treated as proof of an invalid stop.
   if(!OrderSelect(ticket, SELECT_BY_TICKET))
      return(STOP_STATUS_UNKNOWN);

   if(OrderCloseTime() != 0 ||
      OrderSymbol() != Symbol() ||
      OrderMagicNumber() != MagicNumber ||
      OrderType() != OP_BUY ||
      !MathIsValidNumber(Point) || Point <= 0.0)
      return(STOP_STATUS_UNKNOWN);

   // Without reliable live quotes, the stop cannot be judged against current Bid.
   if(!MarketQuotesAreValid())
      return(STOP_STATUS_UNKNOWN);

   double stopLoss = OrderStopLoss();
   double openPrice = OrderOpenPrice();
   if(!MathIsValidNumber(stopLoss) || !MathIsValidNumber(openPrice) ||
      stopLoss <= 0.0 || stopLoss >= openPrice)
      return(STOP_STATUS_INVALID);

   // Allow only the configured entry-slippage reserve beyond the requested stop.
   double actualStopPoints = (openPrice - stopLoss) / Point;
   if(!MathIsValidNumber(actualStopPoints) ||
      actualStopPoints > StopLossPoints + SlippagePoints + 0.5 ||
      stopLoss >= Bid)
      return(STOP_STATUS_INVALID);

   return(STOP_STATUS_VALID);
}

bool CloseUnprotectedPosition(int ticket)
{
   if(!TradingEnvironmentAllowed() || !EnableDemoTrading)
      return(false);

   if(!IsTradeAllowed() || !OrderSelect(ticket, SELECT_BY_TICKET))
      return(false);

   if(OrderCloseTime() != 0 ||
      OrderSymbol() != Symbol() ||
      OrderMagicNumber() != MagicNumber ||
      OrderType() != OP_BUY)
      return(false);

   if(!MarketQuotesAreValid())
      return(false);

   ResetLastError();
   bool closed = OrderClose(ticket, OrderLots(), Bid, SlippagePoints, clrRed);
   if(!closed)
   {
      int errorCode = GetLastError();
      Print("HUGO-TRADER CRITICAL: emergency close failed. Manual terminal check required. Error=", errorCode);
      return(false);
   }

   Print("HUGO-TRADER: position without a valid protective stop was immediately closed. Ticket=", ticket);
   return(true);
}

bool MonitorOpenBuyProtection()
{
   // Without a live quote stream, the current-Bid protection check is unavailable.
   // Pause the EA instead of classifying positions as unprotected or retrying
   // emergency closes that cannot be executed while the terminal is disconnected.
   if(!IsTesting() && !IsConnected())
   {
      if(g_lastUnprotectedTicket != -2)
         Print("HUGO-TRADER WARNING: terminal disconnected; entries and protection checks are paused until reconnection.");
      g_lastUnprotectedTicket = -2;
      return(false);
   }

   bool allProtected = true;
   int firstUnprotectedTicket = -1;

   // Run on every tick, including safe mode. Safe mode observes and warns,
   // but never sends an emergency close order.
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES))
      {
         // Do not skip an order that could not be inspected: it may be one
         // of ours and its protective stop state is unknown.
         if(g_lastUnprotectedTicket != -3)
            Print("HUGO-TRADER WARNING: could not inspect an open order; protection state unknown and entries are paused.");
         g_lastUnprotectedTicket = -3;
         return(false);
      }

      if(OrderSymbol() != Symbol() ||
         OrderMagicNumber() != MagicNumber ||
         OrderType() != OP_BUY)
         continue;

      int ticket = OrderTicket();
      int protectionStatus = ProtectiveStopStatus(ticket);

      if(protectionStatus == STOP_STATUS_UNKNOWN)
      {
         // Unknown is not the same as invalid. Pause entries and do not send a
         // speculative close while the order or quote state cannot be verified.
         if(ticket != g_lastUnprotectedTicket)
            Print("HUGO-TRADER WARNING: open BUY protection state is unknown; no emergency close was sent. Check MT4 order/quote state before resuming. Ticket=", ticket);
         g_lastUnprotectedTicket = ticket;
         return(false);
      }

      if(protectionStatus == STOP_STATUS_INVALID)
      {
         allProtected = false;
         if(firstUnprotectedTicket < 0)
            firstUnprotectedTicket = ticket;

         if(ticket != g_lastUnprotectedTicket)
         {
            if(EnableDemoTrading)
               Print("HUGO-TRADER CRITICAL: open BUY has a confirmed invalid protective stop. Attempting demo-only emergency close. Ticket=", ticket);
            else
               Print("HUGO-TRADER WARNING: open BUY has a confirmed invalid protective stop. Safe mode is active; no automatic close will be sent. Check the MT4 terminal. Ticket=", ticket);
         }

         if(EnableDemoTrading && !CloseUnprotectedPosition(ticket))
            Print("HUGO-TRADER CRITICAL: emergency close failed. Check the MT4 terminal immediately. Ticket=", ticket);
      }
   }

   if(allProtected)
      g_lastUnprotectedTicket = -1;
   else
      g_lastUnprotectedTicket = firstUnprotectedTicket;

   return(allProtected);
}

bool OpenDemoBuy()
{
   if(!TradingEnvironmentAllowed() || !EnableDemoTrading)
      return(false);

   if(!IsTradeAllowed())
   {
      Print("HUGO-TRADER: terminal trading is not currently allowed.");
      return(false);
   }

   // Re-check immediately before sizing/sending to reduce duplicate-entry races.
   if(HasConflictingOrder())
   {
      Print("HUGO-TRADER: existing market position detected immediately before entry; order blocked.");
      return(false);
   }

   if(!MarketQuotesAreValid())
      return(false);

   double spreadPoints = (Ask - Bid) / Point;
   if(spreadPoints > MaxSpreadPoints)
   {
      Print("HUGO-TRADER: spread filter blocked entry.");
      return(false);
   }

   int stopLevel = (int)MarketInfo(Symbol(), MODE_STOPLEVEL);
   double stopDistanceFromBid = StopLossPoints - spreadPoints;
   double takeProfitDistanceFromBid = TakeProfitPoints + spreadPoints;
   if(stopDistanceFromBid <= 0.0 || stopDistanceFromBid < stopLevel ||
      (TakeProfitPoints > 0 && takeProfitDistanceFromBid < stopLevel))
   {
      Print("HUGO-TRADER: stop distance is below the broker stop level after spread.");
      return(false);
   }

   double lots = CalculateLots(spreadPoints);
   if(lots <= 0.0)
   {
      Print("HUGO-TRADER: calculated size is below broker minimum or symbol data is invalid.");
      return(false);
   }

   double freeMarginAfterTrade = AccountFreeMarginCheck(Symbol(), OP_BUY, lots);
   if(!MathIsValidNumber(freeMarginAfterTrade) || freeMarginAfterTrade <= 0.0)
   {
      Print("HUGO-TRADER: insufficient or invalid free-margin result; entry blocked.");
      return(false);
   }

   double stopLoss = NormalizeDouble(Ask - StopLossPoints * Point, Digits);
   double takeProfit = 0.0;
   if(TakeProfitPoints > 0)
      takeProfit = NormalizeDouble(Ask + TakeProfitPoints * Point, Digits);

   ResetLastError();
   int orderTicket = OrderSend(
      Symbol(), OP_BUY, lots, Ask, SlippagePoints,
      stopLoss, takeProfit, "HUGO-TRADER DEMO ONLY",
      MagicNumber, 0, clrBlue
   );

   if(orderTicket < 0)
   {
      int errorCode = GetLastError();
      Print("HUGO-TRADER: demo OrderSend failed. Error=", errorCode);
      return(false);
   }

   Print("HUGO-TRADER: demo buy opened. Ticket=", orderTicket, " lots=", lots);

   int protectionStatus = ProtectiveStopStatus(orderTicket);
   if(protectionStatus != STOP_STATUS_VALID)
   {
      if(protectionStatus == STOP_STATUS_INVALID)
      {
         Print("HUGO-TRADER CRITICAL: entry has a confirmed invalid protective stop. Attempting immediate demo-only close.");
         if(!CloseUnprotectedPosition(orderTicket))
            Print("HUGO-TRADER CRITICAL: emergency close failed. Check the MT4 terminal immediately. Ticket=", orderTicket);
      }
      else
      {
         // Do not guess that the stop is invalid when order/quote state is unreadable.
         // The broker received a stop with OrderSend; require manual verification.
         Print("HUGO-TRADER CRITICAL: protective stop state could not be verified after entry. No automatic close was attempted because order/quote state is unknown. Inspect the MT4 terminal immediately. Ticket=", orderTicket);
      }
      return(false);
   }

   return(true);
}

bool CloseDemoBuy(int ticket)
{
   if(!TradingEnvironmentAllowed() || !EnableDemoTrading)
      return(false);

   if(!IsTradeAllowed() || !OrderSelect(ticket, SELECT_BY_TICKET))
      return(false);

   if(OrderCloseTime() != 0 ||
      OrderSymbol() != Symbol() ||
      OrderMagicNumber() != MagicNumber ||
      OrderType() != OP_BUY)
      return(false);

   if(!MarketQuotesAreValid())
      return(false);

   ResetLastError();
   bool closed = OrderClose(ticket, OrderLots(), Bid, SlippagePoints, clrBlue);
   if(!closed)
   {
      int errorCode = GetLastError();
      Print("HUGO-TRADER: demo OrderClose failed. Error=", errorCode);
   }

   return(closed);
}

void OnTick()
{
   if(!TradingEnvironmentAllowed())
   {
      Comment("HUGO-TRADER BLOCKED: demo account or Strategy Tester required.");
      return;
   }

   Comment("HUGO-TRADER DEMO ONLY | no real-account execution");

   // Protection remains observable in safe mode, but safe mode never closes orders.
   if(!MonitorOpenBuyProtection())
   {
      if(!EnableDemoTrading)
         Comment("HUGO-TRADER SAFE MODE WARNING: open BUY protection is invalid or unverified; check the MT4 terminal.");
      return;
   }

   if(!EnableDemoTrading)
   {
      Comment("HUGO-TRADER SAFE MODE: entries disabled; open BUY protection monitored read-only.");
      return;
   }

   if(Bars < SlowMAPeriod + 3 || Time[0] == g_lastBarTime)
      return;

   g_lastBarTime = Time[0];

   int ticket = -1;
   if(FindOpenBuy(ticket))
   {
      if(CrossedBelow())
         CloseDemoBuy(ticket);
      return;
   }

   if(HasConflictingOrder())
   {
      Print("HUGO-TRADER: existing market position with this symbol/magic; new entry blocked.");
      return;
   }

   if(CrossedAbove())
      OpenDemoBuy();
}
