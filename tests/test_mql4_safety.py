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
        self.assertIn("MathFloor(rawLots / lotStep", body)
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


if __name__ == "__main__":
    unittest.main()
