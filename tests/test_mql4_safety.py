import re
import unittest
from pathlib import Path


EA_PATH = (
    Path(__file__).resolve().parents[1]
    / "MQL4"
    / "Experts"
    / "HUGO_TRADER_DemoOnly.mq4"
)


def function_body(source: str, function_name: str) -> str:
    match = re.search(
        rf"\b(?:bool|int|void|double)\s+{re.escape(function_name)}\s*\([^)]*\)\s*\{{",
        source,
    )
    if not match:
        raise AssertionError(f"Function {function_name} was not found")

    start = match.end()
    depth = 1
    for index in range(start, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start:index]

    raise AssertionError(f"Function {function_name} has unbalanced braces")


class Mql4SafetySourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = EA_PATH.read_text(encoding="utf-8")

    def test_trading_is_disabled_by_default(self):
        self.assertRegex(
            self.source,
            r"input\s+bool\s+EnableDemoTrading\s*=\s*false\s*;",
        )

    def test_only_demo_accounts_or_strategy_tester_are_allowed(self):
        body = function_body(self.source, "TradingEnvironmentAllowed")
        self.assertIn("IsDemo()", body)
        self.assertIn("IsTesting()", body)
        self.assertRegex(body, r"return\s*\(\s*IsDemo\(\)\s*\|\|\s*IsTesting\(\)\s*\)")

    def test_initialization_rejects_non_demo_live_environment(self):
        body = function_body(self.source, "OnInit")
        self.assertIn("if(!TradingEnvironmentAllowed())", body)
        self.assertIn("return(INIT_FAILED);", body)

    def test_magic_number_must_be_positive_to_avoid_manual_orders(self):
        body = function_body(self.source, "OnInit")
        self.assertIn("MagicNumber <= 0", body)

    def test_tick_handler_fails_closed_when_trading_is_not_enabled(self):
        body = function_body(self.source, "OnTick")
        self.assertIn("if(!TradingEnvironmentAllowed())", body)
        self.assertIn("if(!EnableDemoTrading)", body)
        self.assertIn("return;", body)

    def test_every_order_operation_has_its_own_demo_guard(self):
        open_body = function_body(self.source, "OpenDemoBuy")
        close_body = function_body(self.source, "CloseDemoBuy")
        guard = "if(!TradingEnvironmentAllowed() || !EnableDemoTrading)"
        self.assertIn(guard, open_body)
        self.assertIn(guard, close_body)
        self.assertIn("OrderSend(", open_body)
        self.assertIn("OrderClose(", close_body)

    def test_risk_is_capped_and_stop_loss_is_mandatory(self):
        body = function_body(self.source, "OnInit")
        self.assertIn("RiskPercent > 1.0", body)
        self.assertIn("StopLossPoints <= 0", body)

    def test_position_size_rounds_down_and_never_forces_minimum_lot(self):
        body = function_body(self.source, "CalculateLots")
        self.assertIn("MathFloor(cappedLots / lotStep", body)
        self.assertIn("if(lots < minLot)", body)
        self.assertIn("return(0.0);", body)

    def test_risk_budget_uses_current_equity(self):
        body = function_body(self.source, "CalculateLots")
        self.assertIn("AccountEquity()", body)

    def test_risk_estimate_reserves_spread_slippage_and_commission(self):
        body = function_body(self.source, "CalculateLots")
        self.assertIn("StopLossPoints + spreadPoints + 2.0 * SlippagePoints", body)
        self.assertIn("+ EstimatedRoundTurnCommissionPerLot", body)

    def test_negative_commission_estimate_is_rejected(self):
        body = function_body(self.source, "OnInit")
        self.assertIn("EstimatedRoundTurnCommissionPerLot < 0.0", body)

    def test_lot_step_precision_handles_fractional_steps(self):
        body = function_body(self.source, "LotDigitsFromStep")
        self.assertIn("NormalizeDouble(step, digits)", body)
        self.assertIn("MathAbs", body)

    def test_existing_buy_or_sell_position_blocks_duplicate_entry(self):
        body = function_body(self.source, "HasOpenPosition")
        self.assertIn("OrderType() == OP_BUY", body)
        self.assertIn("OrderType() == OP_SELL", body)
        tick = function_body(self.source, "OnTick")
        self.assertIn("if(HasOpenPosition())", tick)

    def test_broker_stop_level_validation_accounts_for_spread(self):
        body = function_body(self.source, "OpenDemoBuy")
        self.assertIn("StopLossPoints - spreadPoints", body)
        self.assertIn("stopDistanceFromBid < stopLevel", body)

    def test_successful_entry_verifies_the_broker_kept_a_protective_stop(self):
        verify = function_body(self.source, "ProtectiveStopIsValid")
        self.assertIn("OrderStopLoss()", verify)
        self.assertIn("OrderOpenPrice()", verify)
        self.assertIn("OrderCloseTime() != 0", verify)
        self.assertIn(
            "actualStopPoints <= StopLossPoints + SlippagePoints + 0.5",
            verify,
        )

        open_body = function_body(self.source, "OpenDemoBuy")
        self.assertIn("if(!ProtectiveStopIsValid(orderTicket))", open_body)
        self.assertIn("CloseUnprotectedPosition(orderTicket)", open_body)

    def test_emergency_close_is_demo_gated_and_limited_to_our_open_buy(self):
        body = function_body(self.source, "CloseUnprotectedPosition")
        self.assertIn(
            "if(!TradingEnvironmentAllowed() || !EnableDemoTrading)",
            body,
        )
        self.assertIn("OrderCloseTime() != 0", body)
        self.assertIn("OrderSymbol() != Symbol()", body)
        self.assertIn("OrderMagicNumber() != MagicNumber", body)
        self.assertIn("OrderType() != OP_BUY", body)
        self.assertIn("OrderClose(", body)
        self.assertIn("Manual terminal check required", body)

    def test_no_unreviewed_order_mutation_or_pending_order_api_is_used(self):
        forbidden = (
            "OrderModify(",
            "OrderDelete(",
            "OrderCloseBy(",
            "OrderSendAsync(",
        )
        for operation in forbidden:
            with self.subTest(operation=operation):
                self.assertNotIn(operation, self.source)

    def test_live_demo_order_paths_require_a_server_connection(self):
        body = function_body(self.source, "MarketQuotesAreValid")
        self.assertIn("if(!IsTesting() && !IsConnected())", body)
        self.assertIn("terminal is disconnected; order operation blocked", body)
        self.assertLess(body.index("IsConnected()"), body.index("RefreshRates()"))

    def test_market_quote_guard_rejects_non_finite_or_crossed_quotes(self):
        body = function_body(self.source, "MarketQuotesAreValid")
        self.assertIn("MathIsValidNumber(Bid)", body)
        self.assertIn("MathIsValidNumber(Ask)", body)
        self.assertIn("MathIsValidNumber(Point)", body)
        self.assertIn("Ask < Bid", body)
        self.assertIn("Point <= 0.0", body)

    def test_all_order_paths_check_market_quotes(self):
        for name in ("OpenDemoBuy", "CloseDemoBuy", "CloseUnprotectedPosition"):
            with self.subTest(function=name):
                self.assertIn("MarketQuotesAreValid()", function_body(self.source, name))

    def test_entry_rechecks_for_an_existing_position_before_order_send(self):
        body = function_body(self.source, "OpenDemoBuy")
        self.assertIn("if(HasOpenPosition())", body)
        self.assertLess(body.index("if(HasOpenPosition())"), body.index("OrderSend("))

    def test_margin_check_rejects_non_finite_or_non_positive_result(self):
        body = function_body(self.source, "OpenDemoBuy")
        self.assertIn("MathIsValidNumber(freeMarginAfterTrade)", body)
        self.assertIn("freeMarginAfterTrade <= 0.0", body)

    def test_normal_close_rejects_already_closed_ticket(self):
        body = function_body(self.source, "CloseDemoBuy")
        self.assertIn("OrderCloseTime() != 0", body)

    def test_maximum_lot_is_capped_then_rounded_down_to_step(self):
        body = function_body(self.source, "CalculateLots")
        self.assertIn("MathMin(rawLots, maxLot)", body)
        self.assertIn("MathFloor(cappedLots / lotStep", body)

    def test_risk_inputs_must_be_finite(self):
        body = function_body(self.source, "OnInit")
        self.assertIn("MathIsValidNumber(RiskPercent)", body)
        self.assertIn("MathIsValidNumber(EstimatedRoundTurnCommissionPerLot)", body)

    def test_protective_stop_validation_rejects_invalid_prices_and_point(self):
        body = function_body(self.source, "ProtectiveStopIsValid")
        self.assertIn("MathIsValidNumber(Point)", body)
        self.assertIn("MathIsValidNumber(stopLoss)", body)
        self.assertIn("MathIsValidNumber(openPrice)", body)


    def test_protective_stop_must_remain_below_current_bid(self):
        body = function_body(self.source, "ProtectiveStopIsValid")
        self.assertIn("MarketQuotesAreValid()", body)
        self.assertIn("stopLoss < Bid", body)

    def test_open_buy_protection_is_checked_before_the_new_bar_gate(self):
        monitor = function_body(self.source, "MonitorOpenBuyProtection")
        self.assertIn("OrdersTotal()", monitor)
        self.assertIn("OrderSelect(i, SELECT_BY_POS, MODE_TRADES)", monitor)
        self.assertIn("ProtectiveStopIsValid(ticket)", monitor)
        self.assertIn("CloseUnprotectedPosition(ticket)", monitor)

        tick = function_body(self.source, "OnTick")
        self.assertIn("if(!MonitorOpenBuyProtection())", tick)
        self.assertLess(
            tick.index("if(!MonitorOpenBuyProtection())"),
            tick.index("if(Bars < SlowMAPeriod + 3"),
        )

    def test_protection_monitor_is_scoped_to_this_symbol_magic_and_buy(self):
        body = function_body(self.source, "MonitorOpenBuyProtection")
        self.assertIn("OrderSymbol() != Symbol()", body)
        self.assertIn("OrderMagicNumber() != MagicNumber", body)
        self.assertIn("OrderType() != OP_BUY", body)

    def test_protection_monitor_runs_even_when_entry_trading_is_disabled(self):
        tick = function_body(self.source, "OnTick")
        monitor_index = tick.index("if(!MonitorOpenBuyProtection())")
        safe_mode_index = tick.index("if(!EnableDemoTrading)")
        self.assertLess(monitor_index, safe_mode_index)

    def test_safe_mode_only_observes_and_never_sends_emergency_close(self):
        body = function_body(self.source, "MonitorOpenBuyProtection")
        self.assertIn(
            "if(EnableDemoTrading && !CloseUnprotectedPosition(ticket))",
            body,
        )
        self.assertIn("Safe mode is active; no automatic close will be sent", body)


if __name__ == "__main__":
    unittest.main()
